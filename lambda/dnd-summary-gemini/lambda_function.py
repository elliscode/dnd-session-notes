import os
import logging
import sys
import boto3
import json
import traceback

from google import genai
from google.genai import types
from google.genai.errors import APIError
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
MODEL_NAME = "gemini-2.5-flash"
LAMBDA_TASK_ROOT = os.environ.get("LAMBDA_TASK_ROOT")
API_KEY = os.environ.get("GEMINI_API_KEY")
S3_BUCKET = os.environ.get("S3_BUCKET")
s3 = boto3.client("s3")

SYSTEM_INSTRUCTION = (
    "You are a DND session summarizer bot. "
    "You read the instructions and state and determine what to do. "
    "You use your knowledge of the 2024 rules to generate your summaries."
)

PROMPT_TEXT = "follow the instructions in instructions.md"

logger = logging.getLogger()
logger.setLevel(logging.INFO)

handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.INFO)

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)

if not logger.handlers:
    logger.addHandler(handler)

def lambda_handler(event, context):
    query = None
    try:
        logger.info(json.dumps(event))
        logger.info(context)

        if not API_KEY:
            error_msg = "GEMINI_API_KEY environment variable not set."
            logging.error(error_msg)
            return {
                'statusCode': 500,
                'body': json.dumps({"message": error_msg})
            }

        body = {}
        if isinstance(event['body'], dict):
            body = event['body']
        elif event['body'].startswith("{"):
            body = json.loads(event['body'])

        date = body.get('date')
        user = body.get('user')
        if not date:
            logging.warning("Request body missing 'date' field.")
            return {
                'statusCode': 400,
                'body': json.dumps({"message": "Date is required in the request body."})
            }
        logging.info(f"Received Summary request. User: {user}. Date: '{date}'")
        file_names = [
            {"prefix": "", "name": f"instructions.md"},
            {"prefix": "sessions/", "name": f"{date}-chat-log.md"},
            {"prefix": "sessions/", "name": f"{date}-notes.md"},
            {"prefix": "sessions/", "name": f"{date}-transcript.md"},
        ]

        print("✨ Initializing Gemini client...")
        try:
            # The client will automatically pick up the GEMINI_API_KEY environment variable.
            client = genai.Client()
        except Exception as e:
            print(f"🛑 Error initializing client: {e}")
            print("Please ensure your GEMINI_API_KEY environment variable is set.")
            return

        file_paths = []
        for file_name in file_names:
            if LAMBDA_TASK_ROOT:
                file_path = f"/tmp/{file_name['name']}"
            else:
                file_path = f"{file_name['name']}"
            s3.download_file(Bucket=S3_BUCKET, Key=f"session-notes/{file_name['prefix']}{file_name['name']}", Filename=file_path)
            file_paths.append(file_path)

        # --- 1. Upload Files ---
        print("\n⬆️ Uploading files...")
        uploaded_files = []

        # We will also track the files we need to include in the final prompt.
        prompt_parts = []

        for file_path in file_paths:
            if not os.path.exists(file_path):
                print(f"⚠️ File not found: {file_path}. Skipping upload.")
                continue

            print(f"   - Uploading: {file_path}")

            # Determine the MIME type
            mime_type = 'text/markdown'

            print(f"   - Uploading: {file_path} (MIME: {mime_type})")

            # Pass the mime_type argument to the upload call
            file = client.files.upload(file=file_path, config={'mime_type': mime_type})

            uploaded_files.append(file)

            # Add the file reference itself to the list of prompt parts
            prompt_parts.append(file)

            # Add a descriptive label to the prompt for context
            prompt_parts.append(f"\n--- {os.path.basename(file_path)} ---\n")

        if not uploaded_files:
            print("\n🛑 No files were successfully uploaded. Aborting.")
            return

        # --- 2. Construct the Full Prompt and Call the API ---
        # Append the final text prompt to the parts list
        prompt_parts.append(PROMPT_TEXT)

        print("\n🧠 Calling Gemini API...")

        # Configuration for the API call
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION
        )

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt_parts,
            config=config,
        )
        response_text = response.text
        logging.info("Gemini Summary call successful.")

        for file_path in file_paths:
            os.remove(file_path)


        print("\n🗑️ Cleaning up uploaded files...")
        for file in uploaded_files:
            # Delete the file from the Gemini API service
            client.files.delete(name=file.name)
            print(f"   - Deleted: {file.display_name}")

        return {
            'statusCode': 200,
            'body': json.dumps({
                "date": date,
                "response": response_text,
                "model": "Gemini",
            })
        }

    except APIError as e:
        error_msg = f"Gemini API Error: {e}"
        logging.error(error_msg)
    except Exception as e:
        error_msg = f"An unexpected error occurred: {e}"
        logging.error(error_msg)
    return {
        'statusCode': 200,
        'body': json.dumps({"message": error_msg, "query": query})
    }

if __name__ == '__main__':
    if not API_KEY:
        logger.info("\n--- ERROR ---")
        logger.info("Please set the GEMINI_API_KEY environment variable to run this example.")
        logger.info("---")
    else:
        mock_event = {"body": {"date": "2025-11-25", "user": "5556152345"}}
        mock_context = {}

        logger.info(f"--- Calling get_completion_gemini_route with query: '{mock_event['body']}' ---")

        result = lambda_handler(mock_event, mock_context)

        logger.info("\n--- Function Output ---")
        logger.info(json.dumps(result, indent=4))
        logger.info("-----------------------")