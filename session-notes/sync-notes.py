#!/usr/bin/env python3
import boto3
import os
import hashlib
import json
import time
import argparse
import difflib
from pathlib import Path
from datetime import datetime

LOCAL_DIR = Path(".")
BUCKET = "daniel-townsend-dnd-notes-userspace"
PREFIX = "session-notes/"

STATE_FILE = Path(".sync-state.json")
BACKUP_DIR = Path(".session-sync-backups")
IGNORE_SUFFIXES = [".ignore.md"]


def should_ignore(path: Path) -> bool:
    bad_suffix = any(str(path).endswith(sfx) for sfx in IGNORE_SUFFIXES)
    bad_prefix = Path(path).resolve().is_relative_to(Path(BACKUP_DIR).resolve())
    return bad_suffix or bad_prefix


def sha256_of_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_of_bytes(data):
    return hashlib.sha256(data).hexdigest()


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"files": {}}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def prompt(options, question):
    print("\n" + question)
    print("Choices:")
    for key, desc in options.items():
        print(f"  {key}) {desc}")
    while True:
        choice = input("> ").strip().lower()
        if choice in options:
            return choice
        print("Invalid choice, try again.")


def backup_file(path):
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = BACKUP_DIR / ts
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / path.name
    print(f"[backup] {path} → {dest}")
    dest.write_bytes(path.read_bytes())


def main(dryrun=False, verbose=False):
    s3 = boto3.client("s3")

    print("Loading state...")
    state = load_state()
    known = state["files"]

    print("Scanning local directory...")
    local_files = {}
    for path in LOCAL_DIR.rglob("*.md"):
        if should_ignore(path):
            continue
        rel = str(path.relative_to(LOCAL_DIR))
        local_files[rel] = {
            "path": path,
            "mtime": path.stat().st_mtime,
            "hash": sha256_of_file(path),
        }

    print("Scanning S3...")
    s3_files = {}
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=PREFIX):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.endswith(".md"):
                continue
            rel = key[len(PREFIX):]
            data = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
            s3_files[rel] = {
                "key": key,
                "mtime": obj["LastModified"].timestamp(),
                "data": data,
                "hash": sha256_of_bytes(data),
            }

    all_files = sorted(set(local_files.keys()) | set(s3_files.keys()))

    for rel in all_files:
        local = local_files.get(rel)
        remote = s3_files.get(rel)
        known_hash = known.get(rel, {}).get("hash")

        # CASE 1: File only on S3
        if local is None:
            print(f"[remote-only] {rel}")
            choice = prompt(
                {"d": "download", "s": "skip"},
                f"File '{rel}' exists on S3 but not locally."
            )
            if choice == "d":
                dest = LOCAL_DIR / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dryrun:
                    dest.write_bytes(remote["data"])
                print(f"[downloaded] {rel}")
                known[rel] = {"hash": remote["hash"]}
            continue

        # CASE 2: File only locally
        if remote is None:
            print(f"[local-only] {rel}")
            choice = prompt(
                {"u": "upload", "s": "skip"},
                f"File '{rel}' exists locally but not on S3."
            )
            if choice == "u":
                if not dryrun:
                    s3.put_object(
                        Bucket=BUCKET,
                        Key=PREFIX + rel,
                        Body=local["path"].read_bytes(),
                    )
                print(f"[uploaded] {rel}")
                known[rel] = {"hash": local["hash"]}
            continue

        # CASE 3: Exists on both sides → check for conflict
        local_hash = local["hash"]
        remote_hash = remote["hash"]

        if local_hash == remote_hash:
            if verbose:
                print(f"[same] {rel}")
            known[rel] = {"hash": local_hash}
            continue

        # Conflict
        print(f"[conflict] {rel}")
        print(f"Local mtime:  {datetime.fromtimestamp(local['mtime'])}")
        print(f"Remote mtime: {datetime.fromtimestamp(remote['mtime'])}")

        choice = prompt(
            {
                "dl": "download remote → overwrite local",
                "ul": "upload local → overwrite remote",
                "b": "backup both",
                "df": "show diff",
                "s": "skip"
            },
            "Conflict detected: what do you want to do?"
        )

        if choice == "df":
            local_text = local["path"].read_text().splitlines()
            remote_text = remote["data"].decode("utf-8").splitlines()
            diff = difflib.unified_diff(
                local_text, remote_text,
                fromfile="local/"+rel,
                tofile="remote/"+rel,
                lineterm=""
            )
            print("\n".join(diff))
            continue  # re-prompt next run

        if choice == "b":
            backup_file(local["path"])
            print("[skipped after backup]")
            continue

        if choice == "dl":
            if not dryrun:
                backup_file(local["path"])
                local["path"].write_bytes(remote["data"])
            print(f"[downloaded] {rel}")
            known[rel] = {"hash": remote_hash}
            continue

        if choice == "ul":
            if not dryrun:
                backup_file(local["path"])
                s3.put_object(
                    Bucket=BUCKET,
                    Key=PREFIX + rel,
                    Body=local["path"].read_bytes(),
                )
            print(f"[uploaded] {rel}")
            known[rel] = {"hash": local_hash}
            continue

        print(f"[skip] {rel}")

    print("Saving state...")
    save_state(state)
    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dryrun", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    main(dryrun=args.dryrun, verbose=args.verbose)
