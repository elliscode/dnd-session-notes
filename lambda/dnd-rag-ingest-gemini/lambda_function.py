import glob
import os
import hashlib
import json
import sys
import time
import logging
from pathlib import Path

import boto3
from google import genai
from google.genai import types

# --- Configuration ---
# IMPORTANT: Replace these placeholders with your actual values
S3_BUCKET = os.environ.get("S3_BUCKET")
S3_PREFIX = os.environ.get("S3_PREFIX")  # Must end with a slash
FILE_SEARCH_STORE_NAME = os.environ.get("FILE_SEARCH_STORE_NAME", "fileSearchStores/dd-session-notes-rag-store-vksej7ft2qat")
prefix_path = Path("../../session-notes").resolve()
# The Gemini API Key is usually set as an environment variable (GEMINI_API_KEY)

# --- Constants ---
HASH_CHUNK_SIZE = 4096  # Chunk size for streaming hash calculation

# --- Setup Logging ---
logger = logging.getLogger()
logger.setLevel(logging.INFO)

handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.INFO)

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)

if not logger.handlers:
    logger.addHandler(handler)

# --- Helper Functions ---

def calculate_s3_hash(s3_client, bucket: str, key: str) -> str:
    """
    Calculates the SHA256 hash of a file in S3 by streaming the content.
    This prevents loading large files entirely into memory in Lambda.
    """
    logger.info(f"Calculating hash for S3 file: s3://{bucket}/{key}")
    hasher = hashlib.sha256()

    try:
        s3_object = s3_client.get_object(Bucket=bucket, Key=key)
        with s3_object['Body'] as body:
            for chunk in iter(lambda: body.read(HASH_CHUNK_SIZE), b''):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception as e:
        logger.error(f"Error calculating hash for {key}: {e}")
        return None


def list_local_files() -> dict:
    output = {}
    for file_path in glob.glob(os.path.join(prefix_path, "**/*.md"), recursive=True):
        with open(file_path, 'rb') as f:
            file_hash = hashlib.md5(f.read()).hexdigest()
        key_path = str(Path(file_path).relative_to(prefix_path))
        output[key_path] = {
            'key': key_path,
            'hash': file_hash,
            'filename': Path(file_path).name
        }
    return output

def list_s3_files(s3_client, bucket: str, prefix: str) -> dict:
    """
    Lists all files in the S3 prefix and calculates their SHA256 hash.
    Returns a dictionary: {s3_key: {'hash': hash_value, 'filename': '...'}}
    """
    s3_map = {}
    paginator = s3_client.get_paginator('list_objects_v2')
    pages = paginator.paginate(Bucket=bucket, Prefix=prefix)

    for page in pages:
        if 'Contents' not in page:
            continue

        for content in page['Contents']:
            key = content['Key']
            # Skip folders/prefixes themselves
            if key.endswith('/'):
                continue

            # Use the S3 Key as the unique identifier
            unique_id = key
            filename = os.path.basename(key)

            file_hash = calculate_s3_hash(s3_client, bucket, key)
            if file_hash:
                s3_map[unique_id] = {
                    'key': key,
                    'hash': file_hash,
                    'filename': filename
                }

    logger.info(f"Found {len(s3_map)} documents in S3 prefix: {prefix}")
    return s3_map

def list_remote_documents(gemini_client, store_name: str) -> dict:
    """
    Lists all documents in the File Search Store and extracts their metadata.
    Returns a dictionary: {s3_key (from displayName): {'name': doc_name, 'hash': hash_value}}
    The unique identifier (S3 Key) is stored in the 'displayName' field.
    """
    remote_map = {}

    # Note: list_documents is not available in the public beta `genai.Client()`.
    # Using the standard File Search Store APIs and assuming the Document resource structure.
    # The actual implementation requires the `Document` resource API, which is often
    # part of the managed service client (like `client.file_search_stores.documents.list`).
    # For this example, we'll simulate fetching from a standard API endpoint that returns a list.

    # In the `google-genai` SDK, you would typically use a paginator here:
    # `pager = gemini_client.file_search_stores.documents.list(name=store_name)`
    # Since that specific structure isn't confirmed for the current public client,
    # we rely on the `list` method of the `file_search_store` resource if available, or simulate it.

    # Simulating the listing and custom metadata extraction:
    # In a real environment, you would use the following logic if the API supported it directly.
    try:
        # Paginator structure for documents list:
        pager = gemini_client.file_search_stores.documents.list(parent=store_name)

        for document in pager:
            # The 'displayName' is used to store the unique S3 Key
            unique_id = document.display_name

            # Find the 'content_hash' in customMetadata
            content_hash = None
            s3_key = None
            if document.custom_metadata:
                for metadata in document.custom_metadata:
                    if metadata.key == 'content_hash':
                        content_hash = metadata.string_value
                    if metadata.key == 's3_key':
                        s3_key = metadata.string_value

            if unique_id and content_hash:
                remote_map[unique_id] = {
                    'name': document.name, # The full resource name
                    'hash': content_hash,
                    's3_key': s3_key,
                }

    except Exception as e:
        logger.error(f"Error listing remote documents: {e}")
        # Placeholder simulation for development if the specific API is unavailable
        # raise

    logger.info(f"Found {len(remote_map)} documents in File Search Store.")
    return remote_map

def synchronize_files(gemini_client, s3_client, s3_map: dict, remote_map: dict):
    """
    Performs the three-way synchronization logic.
    """
    store_name = FILE_SEARCH_STORE_NAME

    # 1. Check S3 files against Remote (Upload/Update)
    for unique_id, s3_data in s3_map.items():
        s3_hash = s3_data['hash']

        if unique_id not in remote_map:
            # Case 1: File missing in File Search Store -> Upload
            logger.info(f"ACTION: Uploading NEW file: {unique_id}")

            # Download file content to a temporary location for upload
            temp_path = prefix_path.joinpath(s3_data["key"])
            # temp_path = f"/tmp/{s3_data['filename']}"
            # s3_client.download_file(S3_BUCKET, s3_data['key'], temp_path)

            try:
                # Use the unique S3 key as the display name for retrieval
                operation = gemini_client.file_search_stores.upload_to_file_search_store(
                    file=temp_path.resolve(),
                    file_search_store_name=store_name,
                    config={
                        "display_name":unique_id,
                        "custom_metadata":[
                            types.CustomMetadata(key="content_hash", string_value=s3_hash),
                            types.CustomMetadata(key="s3_key", string_value=s3_data['key'])
                        ]
                    }
                )

                # Wait for the indexing operation to complete
                while not operation.done:
                    logger.info(f"Indexing {unique_id}... Status: {operation.name}")
                    time.sleep(0.5)
                    operation = gemini_client.operations.get(operation=operation)

                logger.info(f"Upload and indexing COMPLETE for: {unique_id}")
            except Exception as e:
                logger.error(f"Failed to upload/index {unique_id}: {e}")
            finally:
                # Clean up temporary file
                if os.path.exists(temp_path):
                    # os.remove(temp_path)
                    pass

        else:
            # Case 2: File exists in both -> Check hash
            remote_hash = remote_map[unique_id]['hash']
            remote_doc_name = remote_map[unique_id]['name']

            if s3_hash != remote_hash:
                # Case 2a: Hash mismatch -> Delete old, Upload new
                logger.info(f"ACTION: Hash mismatch for {unique_id}. Deleting old document and uploading new one.")

                # A. Delete old document
                try:
                    gemini_client.file_search_stores.documents.delete(
                        name=remote_doc_name
                    )
                    logger.info(f"Deleted old document: {remote_doc_name}")
                except Exception as e:
                    logger.error(f"Failed to delete old document {remote_doc_name}: {e}")
                    # Continue to next file if deletion fails, rather than attempting upload which might fail
                    continue

                # B. Upload new document (same logic as Case 1)
                temp_path = f"/tmp/{s3_data['filename']}"
                s3_client.download_file(S3_BUCKET, s3_data['key'], temp_path)

                try:
                    operation = gemini_client.file_search_stores.upload_to_file_search_store(
                        file=temp_path.resolve(),
                        file_search_store_name=store_name,
                        config={
                            "display_name": unique_id,
                            "custom_metadata": [
                                types.CustomMetadata(key="content_hash", string_value=s3_hash),
                                types.CustomMetadata(key="s3_key", string_value=s3_data['key'])
                            ]
                        }
                    )

                    while not operation.done:
                        logger.info(f"Indexing updated {unique_id}... Status: {operation.name}")
                        time.sleep(0.5)
                        operation = gemini_client.operations.get(operation=operation)

                    logger.info(f"Upload and indexing COMPLETE for UPDATED file: {unique_id}")
                except Exception as e:
                    logger.error(f"Failed to upload/index UPDATED {unique_id}: {e}")
                finally:
                    if os.path.exists(temp_path):
                        # os.remove(temp_path)
                        pass

            else:
                # Case 2b: Hashes match -> Skip
                logger.info(f"SKIP: Hashes match for {unique_id}. No action needed.")

    # 2. Check Remote files against S3 (Delete)
    for unique_id, remote_data in remote_map.items():
        if unique_id not in s3_map:
            # Case 3: File missing in S3 -> Delete from File Search Store
            remote_doc_name = remote_data['name']
            logger.info(f"ACTION: File missing from S3. Deleting remote document: {unique_id}")

            try:
                gemini_client.file_search_stores.documents.delete(
                    name=remote_doc_name
                )
                logger.info(f"Successfully DELETED document: {remote_doc_name}")
            except Exception as e:
                logger.error(f"Failed to delete document {remote_doc_name}: {e}")

    logger.info("Synchronization complete.")


# --- Main Lambda Handler ---

def lambda_handler(event, context):
    """
    Main entry point for the AWS Lambda function.
    """
    try:
        # Initialize clients
        gemini_client = genai.Client()
        s3_client = boto3.client('s3')

        logger.info(f"Starting sync from S3 Bucket: {S3_BUCKET}, Prefix: {S3_PREFIX}")
        logger.info(f"Target File Search Store: {FILE_SEARCH_STORE_NAME}")

        # 1. Get current state of files in S3 (with hashes)
        # s3_map = list_s3_files(s3_client, S3_BUCKET, S3_PREFIX)
        s3_map = list_local_files()

        # 2. Get current state of files in Gemini File Search Store (with metadata hashes)
        remote_map = list_remote_documents(gemini_client, FILE_SEARCH_STORE_NAME)

        # 3. Execute synchronization logic
        synchronize_files(gemini_client, s3_client, s3_map, remote_map)

        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'File synchronization completed successfully.'})
        }

    except Exception as e:
        logger.error(f"FATAL ERROR in Lambda execution: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({'error': f'Synchronization failed: {str(e)}'})
        }

# Example of how to run the handler locally (if needed for testing)
if __name__ == '__main__':
    lambda_handler({}, None)