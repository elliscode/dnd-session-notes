import json
import traceback
import glob
import hashlib
from pathlib import Path
from openai import OpenAI
import chromadb
from chromadb.utils import embedding_functions
from chromadb.config import Settings
from tiktoken import get_encoding
import boto3
import zipfile
import os
import shutil

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


DATA_FOLDER = "/tmp/session-notes"          # folder containing your .md files
CHROMA_PATH = "/tmp/chroma_data"       # persistent ChromaDB directory

download_s3_directory("daniel-townsend-dnd-notes-userspace", "session-notes/", DATA_FOLDER)
s3.download_file("daniel-townsend-dnd-notes-userspace", "chromadb.zip", "/tmp/chromadb.zip")
unzip_file("/tmp/chromadb.zip", CHROMA_PATH)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

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

        body = {}
        if isinstance(event['body'], dict):
            body = event['body']
        elif event['body'].startswith("{"):
            body = json.loads(event['body'])

        query = body['query']

        # Search top 5 relevant chunks
        results = collection.query(
            query_texts=[query],
            n_results=5,
        )

        context = ""
        for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
            print(f"📄 From {meta['source']}, chunk {meta['chunk']}")
            print(doc[:300] + "...\n")
            context += f"<SOURCE><NAME>{meta['source']}</NAME><TEXT>{doc}</TEXT></SOURCE>"

        # Build prompt for LLM
        system_prompt = """
        You are a Dungeons & Dragons campaign assistant.
        The question you will answer relates to a DND campaign.
        There is no speaker or narrator, as this is a collective storytelling exercise with 7 participants.
        Always return a list of <SOURCE>s used to determine your answer by listing the <NAME>s with a short summary of the <TEXT>s, in a markdown-style list
        """
        user_prompt = f"""
        <CONTEXT>{context}</CONTEXT>
        <QUESTION>{query}</QUESTION>"""

        # Ask GPT-4o-mini (for example)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        return {"statusCode": 200, "body": response.choices[0].message.content}
    except Exception:
        traceback.print_exc()
        return {"statusCode": 500, "body": f"Internal server error"}