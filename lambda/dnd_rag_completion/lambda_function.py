import json
import traceback

from openai import OpenAI
import chromadb
from chromadb.utils import embedding_functions
import boto3
import zipfile
import os

s3 = boto3.client("s3")

S3_BUCKET = os.environ.get("S3_BUCKET")

DATA_FOLDER = "/tmp/session-notes"
CHROMA_PATH = "/tmp/chroma_data"

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# This is where I would copy files from S3 to my /tmp/chroma_data directory
COLLECTION_NAME = "dnd_sessions"
EMBED_MODEL = "text-embedding-3-small"  # low-cost, high-quality model
client = None
collection = None

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
    global client, collection
    if client is not None and collection is not None:
        print("Already initialized, skipping initialization portion")
        return
    print("Initializing...")

    s3.download_file(S3_BUCKET, "chromadb.zip", "/tmp/chromadb.zip")
    unzip_file("/tmp/chromadb.zip", CHROMA_PATH)

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
        print(response)
        output ={"statusCode": 200, "body": response.choices[0].message.content}
        print(json.dumps(output))
        return output
    except Exception:
        traceback.print_exc()
        return {"statusCode": 500, "body": f"Internal server error"}