import os
import logging
import sys
import json

from google import genai
from google.genai import types
from google.genai.errors import APIError
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
FILE_SEARCH_STORE_NAME = "fileSearchStores/dd-session-notes-rag-store-vksej7ft2qat"
MODEL_NAME = "gemini-2.5-flash"
LAMBDA_TASK_ROOT = os.environ.get("LAMBDA_TASK_ROOT")
API_KEY = os.environ.get("GEMINI_API_KEY")

logger = logging.getLogger()
logger.setLevel(logging.INFO)

handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.INFO)

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)

if not logger.handlers:
    logger.addHandler(handler)

def extract_unique_file_titles(response: types.GenerateContentResponse) -> list[str]:
    unique_file_titles = set()
    grounding_metadata = (
        response.candidates[0].grounding_metadata
        if response.candidates and response.candidates[0].grounding_metadata
        else None
    )

    if grounding_metadata and grounding_metadata.grounding_chunks:
        for chunk in grounding_metadata.grounding_chunks:
            if chunk.retrieved_context and chunk.retrieved_context.title:
                file_title = chunk.retrieved_context.title
                unique_file_titles.add(file_title)
    return list(unique_file_titles)

def lambda_handler(event, context):
    query = None
    try:
        print(json.dumps(event))
        print(context)

        body = {}
        if isinstance(event['body'], dict):
            body = event['body']
        elif event['body'].startswith("{"):
            body = json.loads(event['body'])

        query = body.get('query')
        user = body.get('user')
        if not query:
            logging.warning("Request body missing 'query' field.")
            return {
                'statusCode': 400,
                'body': json.dumps({"message": "Query is required in the request body."})
            }
        logging.info(f"Received RAG request. User: {user}. Query: '{query}'")

        if not API_KEY:
            error_msg = "GEMINI_API_KEY environment variable not set."
            logging.error(error_msg)
            return {
                'statusCode': 500,
                'body': json.dumps({"message": error_msg})
            }

        client = genai.Client(api_key=API_KEY)
        rag_tool = types.Tool(
            file_search=types.FileSearch(
                file_search_store_names=[FILE_SEARCH_STORE_NAME]
            )
        )
        config = types.GenerateContentConfig(
            tools=[rag_tool],
            system_instruction=(
                "You are a Dungeons & Dragons campaign assistant."
                "The question you will answer relates to a DND campaign."
                "There is no speaker or narrator, as this is a collective storytelling exercise."
                "Files with the word 'transcript' in the filename are the least reliable"
                "Files with the word 'chat-log' in the filename are only to be used to validate combat encounters"
                "All other files are preferred"
                "When answering questions about 'who', try to figure out which characters were involved"
                "When formatting your answers, prefer markdown formatting and bulleted lists"
                "When answering questions about abilities, reference the filenames with 'sheets' in them"
                "If you deem a source to be unrelated, please ignore it and do not reference it in your output."
            ),
            temperature=2.0,
        )
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=[query],
            config=config,
        )
        response_text = response.text
        logging.info("Gemini RAG call successful.")

        return {
            'statusCode': 200,
            'body': json.dumps({
                "query": query,
                "response": response_text,
                "sources": extract_unique_file_titles(response),
                "model": MODEL_NAME,
                "store_used": FILE_SEARCH_STORE_NAME
            })
        }

    except APIError as e:
        error_msg = f"Gemini API Error: {e}"
        logging.error(error_msg)
        return {
            'statusCode': 200,
            'body': json.dumps({"message": error_msg, "query": query})
        }
    except Exception as e:
        error_msg = f"An unexpected error occurred: {e}"
        logging.error(error_msg)
        return {
            'statusCode': 200,
            'body': json.dumps({"message": error_msg, "query": query})
        }

if __name__ == '__main__':
    if not API_KEY:
        print("\n--- ERROR ---")
        print("Please set the GEMINI_API_KEY environment variable to run this example.")
        print("---")
    else:
        mock_event = {"body": {"csrf": "some_token", "query": "How did neiro get to the desert with Jeffers?", "user": "5556152345"}}
        mock_context = {}

        print(f"--- Calling get_completion_gemini_route with query: '{mock_event['body']['query']}' ---")

        result = lambda_handler(mock_event, mock_context)

        print("\n--- Function Output ---")
        import json
        print(json.dumps(result, indent=4))
        print("-----------------------")