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

S3_BUCKET = os.environ.get("S3_BUCKET")
S3_PREFIX = os.environ.get("S3_PREFIX")
S3_PENDING = os.path.join("gemini.pending")
FILE_SEARCH_STORE_NAME = os.environ.get("FILE_SEARCH_STORE_NAME")
LAMBDA_TASK_ROOT = os.environ.get("LAMBDA_TASK_ROOT")
HASH_CHUNK_SIZE = 4096

logger = logging.getLogger()
logger.setLevel(logging.INFO)

handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.INFO)

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)

if not logger.handlers:
    logger.addHandler(handler)


def calculate_s3_hash(s3_client, bucket: str, key: str) -> str:
    ## 1. Primary Check: Retrieve ETag (Metadata Only)
    try:
        head_response = s3_client.head_object(Bucket=bucket, Key=key)
        # S3 ETags are wrapped in double quotes, so we strip them
        etag = head_response['ETag'].strip('"')
    except Exception as e:
        # Handle the key not found case
        if e.response['Error']['Code'] == '404':
            logger.info(f"Error: Key not found at s3://{bucket}/{key}")
            return None
        raise  # Re-raise other errors (permissions, etc.)

    ## 2. ETag Analysis (The optimization)
    # ETag for a single-part upload IS the MD5 hash.
    # ETag for a multipart upload CONTAINS a hyphen ('-').
    if '-' not in etag:
        # Single-part: ETag is the MD5. Return it immediately.
        return etag

    ## 3. Fallback: Multipart Upload (Streaming calculation required)
    logger.info(f"Key is a multipart upload ({etag}). Falling back to streaming calculation...")

    # Initialize the MD5 hasher for the fallback
    hasher = hashlib.md5()

    try:
        s3_object = s3_client.get_object(Bucket=bucket, Key=key)
        with s3_object['Body'] as body:
            # Use the efficient chunking method from your original code
            for chunk in iter(lambda: body.read(HASH_CHUNK_SIZE), b''):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception as e:
        logger.info(f"Error streaming multipart file {key}: {e}")
        return None


def list_local_files() -> dict:
    output = {}
    local_folder = Path("../../" + S3_PREFIX).resolve()
    for file_path in glob.glob(os.path.join(local_folder, "**/*.md"), recursive=True):
        with open(file_path, 'rb') as f:
            file_hash = hashlib.md5(f.read()).hexdigest()
        key_path = str(Path(file_path).relative_to(local_folder))
        output[key_path] = {
            'key': key_path,
            'hash': file_hash,
            'filename': Path(file_path).name
        }
    return output

def list_s3_files(s3_client, bucket: str, prefix: str) -> dict:
    s3_map = {}
    paginator = s3_client.get_paginator('list_objects_v2')
    pages = paginator.paginate(Bucket=bucket, Prefix=prefix)

    for page in pages:
        if 'Contents' not in page:
            continue

        for content in page['Contents']:
            key: str = content['Key']
            if not key.endswith(".md") or key.endswith('/'):
                continue

            unique_id = key.removeprefix(S3_PREFIX)
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
    remote_map = {}

    try:
        pager = gemini_client.file_search_stores.documents.list(parent=store_name)

        for document in pager:
            unique_id = document.display_name

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
                    'name': document.name,
                    'hash': content_hash,
                    's3_key': s3_key,
                }

    except Exception as e:
        logger.error(f"Error listing remote documents: {e}")

    logger.info(f"Found {len(remote_map)} documents in File Search Store.")
    return remote_map

def synchronize_files(gemini_client, s3_client, s3_map: dict, remote_map: dict):
    store_name = FILE_SEARCH_STORE_NAME

    for unique_id, s3_data in s3_map.items():
        s3_hash = s3_data['hash']

        if unique_id not in remote_map:
            logger.info(f"ACTION: Uploading NEW file: {unique_id}")

            temp_path = f"/tmp/{s3_data['filename']}"
            s3_client.download_file(S3_BUCKET, s3_data['key'], temp_path)

            try:
                operation = gemini_client.file_search_stores.upload_to_file_search_store(
                    file=temp_path,
                    file_search_store_name=store_name,
                    config={
                        "display_name":unique_id,
                        "custom_metadata":[
                            types.CustomMetadata(key="content_hash", string_value=s3_hash),
                            types.CustomMetadata(key="s3_key", string_value=s3_data['key'])
                        ]
                    }
                )

                while not operation.done:
                    logger.info(f"Indexing {unique_id}... Status: {operation.name}")
                    time.sleep(0.5)
                    operation = gemini_client.operations.get(operation=operation)

                logger.info(f"Upload and indexing COMPLETE for: {unique_id}")
            except Exception as e:
                logger.error(f"Failed to upload/index {unique_id}: {e}")
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                    pass

        else:
            remote_hash = remote_map[unique_id]['hash']
            remote_doc_name = remote_map[unique_id]['name']

            if s3_hash != remote_hash:
                logger.info(f"ACTION: Hash mismatch for {unique_id}. Deleting old document and uploading new one.")

                try:
                    gemini_client.file_search_stores.documents.delete(
                        name=remote_doc_name,
                        config={'force': True},
                    )
                    logger.info(f"Deleted old document: {remote_doc_name}")
                except Exception as e:
                    logger.error(f"Failed to delete old document {remote_doc_name}: {e}")
                    continue

                temp_path = f"/tmp/{s3_data['filename']}"
                s3_client.download_file(S3_BUCKET, s3_data['key'], temp_path)

                try:
                    operation = gemini_client.file_search_stores.upload_to_file_search_store(
                        file=temp_path,
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
                        os.remove(temp_path)
                        pass

            else:
                logger.info(f"SKIP: Hashes match for {unique_id}. No action needed.")

    for unique_id, remote_data in remote_map.items():
        if unique_id not in s3_map:
            remote_doc_name = remote_data['name']
            logger.info(f"ACTION: File missing from S3. Deleting remote document: {unique_id}")

            try:
                gemini_client.file_search_stores.documents.delete(
                    name=remote_doc_name,
                    config={'force': True},
                )
                logger.info(f"Successfully DELETED document: {remote_doc_name}")
            except Exception as e:
                logger.error(f"Failed to delete document {remote_doc_name}: {e}")

    logger.info("Synchronization complete.")



def lambda_handler(event, context):
    logger.info(event)
    s3_client = boto3.client('s3')
    try:
        gemini_client = genai.Client()

        if 'Contents' in s3_client.list_objects_v2(Bucket=S3_BUCKET, Prefix=S3_PENDING, MaxKeys=1):
            message = 'Already running, skipping this invocation...'
            logger.info(message)
            return {
                'statusCode': 201,
                'body': json.dumps({'message': message})
            }

        logger.info(f"Writing '.pending' file to : {S3_BUCKET}, Prefix: {S3_PREFIX}")
        s3_client.put_object(Bucket=S3_BUCKET, Key=S3_PENDING, Body="".encode('utf-8'))

        logger.info(f"Starting sync from S3 Bucket: {S3_BUCKET}, Prefix: {S3_PREFIX}")
        logger.info(f"Target File Search Store: {FILE_SEARCH_STORE_NAME}")

        if LAMBDA_TASK_ROOT:
            s3_map = list_s3_files(s3_client, S3_BUCKET, S3_PREFIX)
        else:
            s3_map = list_local_files()

        remote_map = list_remote_documents(gemini_client, FILE_SEARCH_STORE_NAME)

        synchronize_files(gemini_client, s3_client, s3_map, remote_map)

        s3_client.delete_object(Bucket=S3_BUCKET, Key=S3_PENDING)

        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'File synchronization completed successfully.'})
        }

    except Exception as e:
        logger.error(f"FATAL ERROR in Lambda execution: {e}", exc_info=True)
        s3_client.delete_object(Bucket=S3_BUCKET, Key=S3_PENDING)
        return {
            'statusCode': 500,
            'body': json.dumps({'error': f'Synchronization failed: {str(e)}'})
        }

if __name__ == '__main__':
    lambda_handler({}, None)