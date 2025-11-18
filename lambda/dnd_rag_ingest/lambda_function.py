import json
import traceback
import glob
import hashlib
from pathlib import Path
from openai import OpenAI
import chromadb
from chromadb.utils import embedding_functions
from tiktoken import get_encoding
import boto3
import zipfile
import os
import shutil

STARTING_FILE = "dnd_rag_ingest.STARTING"

s3 = boto3.client("s3")

S3_BUCKET = os.environ.get("S3_BUCKET")

s3.upload_file(Bucket=S3_BUCKET, Key=STARTING_FILE)

DATA_FOLDER = "/tmp/session-notes"
CHROMA_PATH = "/tmp/chroma_data"

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

def zip_directory(folder, zip_path):
    """
    Create a ZIP file from a folder.
    Result: zip_path (e.g., /tmp/chroma.zip)
    """
    # zip_path must not end in .zip for make_archive base_name
    base = zip_path.replace(".zip", "")
    shutil.make_archive(base, 'zip', folder)
    print(f"Zipped {folder} → {zip_path}")
    return zip_path

def unzip_file(zip_path, extract_to):
    """
    Unzips a ZIP file into the given directory.
    Creates the target directory if it doesn't exist.
    """
    os.makedirs(extract_to, exist_ok=True)

    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_to)

    print(f"Unzipped {zip_path} → {extract_to}")

s3 = boto3.client("s3")

def download_s3_directory(bucket, prefix, local_path="/tmp"):
    """
    Recursively download an S3 prefix (directory) into a local folder.
    Example:
        download_s3_directory("mybucket", "notes/", "/tmp/notes")
    """
    paginator = s3.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]

            # Skip "directory" placeholders if present
            if key.endswith("/"):
                continue

            # Build local path
            rel_path = key[len(prefix):] if key.startswith(prefix) else key
            local_file_path = os.path.join(local_path, rel_path)

            # Ensure directory exists
            os.makedirs(os.path.dirname(local_file_path), exist_ok=True)

            # Download the file
            s3.download_file(bucket, key, local_file_path)
            print(f"Downloaded: s3://{bucket}/{key} → {local_file_path}")

download_s3_directory(S3_BUCKET, "session-notes/", DATA_FOLDER)
s3.download_file(S3_BUCKET, "chromadb.zip", "/tmp/chromadb.zip")
unzip_file("/tmp/chromadb.zip", CHROMA_PATH)

# This is where I would copy files from S3 to my /tmp/chroma_data directory
COLLECTION_NAME = "dnd_sessions"
EMBED_MODEL = "text-embedding-3-small"  # low-cost, high-quality model

# Initialize clients
client = OpenAI(api_key=OPENAI_API_KEY)
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
embed_fn = embedding_functions.OpenAIEmbeddingFunction(
    api_key=OPENAI_API_KEY,
    model_name=EMBED_MODEL,
)

collection = chroma_client.get_or_create_collection(
    name=COLLECTION_NAME,
    embedding_function=embed_fn,
)

s3.delete_object(Bucket=S3_BUCKET, Key=STARTING_FILE)

# Helper to chunk text
def chunk_text(text, chunk_size=300, overlap=75):
    tokens = get_encoding("cl100k_base").encode(text)
    chunks = []
    start = 0
    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        chunk = get_encoding("cl100k_base").decode(tokens[start:end])
        chunks.append(chunk)
        start += chunk_size - overlap
    return chunks

# Compute a stable hash for each file (for deduplication)
def file_hash(path):
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()

def lambda_handler(event, context):
    try:
        print(json.dumps(event))
        print(context)

        # Load existing IDs to avoid re-uploading
        existing_docs = {m["file_id"]: m for m in collection.get()["metadatas"]} if collection.count() > 0 else {}

        # Process all markdown files
        md_files = glob.glob(os.path.join(DATA_FOLDER, "*.md"))
        print(md_files)
        added_chunks = 0

        file_ids = []
        for file_path in md_files:
            file_name = Path(file_path).name
            file_id = file_name + file_hash(file_path)
            file_ids.append(file_id)
            if file_id in existing_docs:
                print(f"Skipping {Path(file_path).name} (already embedded)")
                continue

            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()

            chunks = chunk_text(text)
            ids = [f"{file_id}_{i}" for i in range(len(chunks))]
            metadatas = [{"file_id": file_id, "source": file_name, "chunk": i} for i in range(len(chunks))]

            if len(chunks) > 0:
                collection.upsert(
                    documents=chunks,
                    ids=ids,
                    metadatas=metadatas
                )

            print(f"✅ Added {len(chunks)} chunks from {file_name}")
            added_chunks += len(chunks)

        ids_to_delete = []
        results = collection.get(include=["metadatas"])
        for i, meta in enumerate(results["metadatas"]):
            if not meta:
                continue
            # print(meta['file_id'])
            if meta['file_id'] not in file_ids:
                ids_to_delete.append(results["ids"][i])
        # Step 4. Delete them
        if ids_to_delete:
            print(f"🗑️ Deleting {len(ids_to_delete)} entries (stale files removed from sessions/)")
            collection.delete(ids=ids_to_delete)
        else:
            print("✅ No stale entries to delete.")

        print(f"\n🎉 Done. {added_chunks} new chunks embedded and stored in '{COLLECTION_NAME}'.")
        print(f"Total records in collection: {collection.count()}")

        # Step 2 — ZIP updated Chroma snapshot
        zip_file = "/tmp/chroma_snapshot.zip"
        zip_directory("/tmp/chroma_data", zip_file)

        # Step 3 — Upload the ZIP back to S3
        s3.upload_file(zip_file, S3_BUCKET, "chromadb.zip")
        print(f"Uploaded {zip_file} → s3://daniel-townsend-dnd-notes-userspace/chromadb.zip")

        return {"statusCode": 200, "body": f"Updated the chromadb files and changed the environment variable in the dnd_rag_api, you should be good to go now"}
    except Exception:
        traceback.print_exc()
        return {"statusCode": 500, "body": f"Internal server error"}