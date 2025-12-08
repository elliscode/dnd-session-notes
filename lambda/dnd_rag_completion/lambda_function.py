import json
import traceback

from datetime import datetime

from openai import OpenAI
import chromadb
from chromadb.utils import embedding_functions
import boto3
import zipfile
import os
import time

s3 = boto3.client("s3")

S3_BUCKET = os.environ.get("S3_BUCKET")
MODEL_NAME = os.environ.get("MODEL_NAME", "gpt-4o-mini")

CHROMA_PATH = "/tmp/chroma_data"

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# This is where I would copy files from S3 to my /tmp/chroma_data directory
COLLECTION_NAME = "dnd_sessions"
EMBED_MODEL = "text-embedding-3-small"  # low-cost, high-quality model
client = None
collection = None
zip_timestamp = None
current_chroma_path: str | None = None

def unzip_file(zip_path, extract_to):
    """
    Unzips a ZIP file into the given directory.
    Creates the target directory if it doesn't exist.
    """
    os.makedirs(extract_to, exist_ok=True)

    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_to)

    print(f"Unzipped {zip_path} → {extract_to}")

def init():
    global client, collection, zip_timestamp, current_chroma_path
    should_not_init = False
    if client is not None and collection is not None and zip_timestamp is not None and current_chroma_path is not None:
        response = s3.head_object(
            Bucket=S3_BUCKET,
            Key="chromadb.zip",
        )
        last_modified = response['LastModified']
        if zip_timestamp >= last_modified:
            should_not_init = True
        else:
            zip_timestamp = last_modified
    if should_not_init:
        print("Already initialized, skipping initialization portion")
        return
    print("Initializing...")

    # Kill references
    client = None
    collection = None

    if current_chroma_path is not None and os.path.exists(current_chroma_path):
        for root, dirs, files in os.walk(current_chroma_path, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))
    if os.path.exists("/tmp/chromadb.zip"):
        os.remove("/tmp/chromadb.zip")

    response = s3.head_object(
        Bucket=S3_BUCKET,
        Key="chromadb.zip",
    )
    zip_timestamp = response['LastModified']

    s3.download_file(S3_BUCKET, "chromadb.zip", "/tmp/chromadb.zip")
    current_chroma_path = CHROMA_PATH + "_" + str(int(time.time()))
    unzip_file("/tmp/chromadb.zip", current_chroma_path)

    # Initialize clients
    client = OpenAI(api_key=OPENAI_API_KEY)
    chroma_client = chromadb.PersistentClient(path=current_chroma_path)
    embed_fn = embedding_functions.OpenAIEmbeddingFunction(
        api_key=OPENAI_API_KEY,
        model_name=EMBED_MODEL,
    )

    collection = chroma_client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embed_fn,
    )


def lambda_handler(event, context):
    try:
        print(json.dumps(event))
        print(context)
        init()

        body = {}
        if isinstance(event['body'], dict):
            body = event['body']
        elif event['body'].startswith("{"):
            body = json.loads(event['body'])

        query = body.get('query')

        if query is None:
            output = {"statusCode": 201, "body": "Successful ping, lambda is now warm" }
            print(json.dumps(output))
            return output

        # Search top 5 relevant chunks
        results = collection.query(
            query_texts=[query],
            n_results=5,
        )

        context = ""
        for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
            print(f"📄 From {meta['source']}, chunk {meta['chunk']}")
            print(doc[:100] + "...\n")
            context += f"<SOURCE><NAME>{meta['source']}</NAME><TEXT>{doc}</TEXT></SOURCE>"

        # Build prompt for LLM
        system_prompt = f"""
You are a Dungeons & Dragons campaign assistant.
The question you will answer relates to a DND campaign.
There is no speaker or narrator, as this is a collective storytelling exercise.
The <QUESTION> you will answer will be accompanied by <SOURCE>s from a RAG application using ChromaDB.
Always return a list of <SOURCE>s used to determine your answer by listing the <NAME>s with a short summary of the <TEXT>s, in a markdown-style list.
If you deem a <SOURCE> to be unrelated, please ignore it and do not list it in the <SOURCE>s."""
        user_prompt = f"""
<CONTEXT>{context}</CONTEXT>
<QUESTION>{query}</QUESTION>"""

        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        print(response)
        output ={"statusCode": 200, "body": response.choices[0].message.content}
        print(json.dumps(output))
        return output
    except Exception:
        traceback.print_exc()
        return {"statusCode": 500, "body": f"Internal server error"}