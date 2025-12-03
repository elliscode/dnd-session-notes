import os
from google import genai
from google.genai import types
from datetime import date

DATE = date.today().isoformat()

# --- Configuration ---
# You can change the model if you prefer (e.g., 'gemini-2.5-pro')
MODEL_NAME = 'gemini-2.5-flash'
OUTPUT_FILE = f"sessions/{DATE}-summary.md"

# List of files to upload and include in the prompt
FILE_PATHS = [
    "sessions/instructions-and-state.txt",
    f"sessions/{DATE}-notes.md",
    f"sessions/{DATE}-transcript.md",
    f"sessions/{DATE}-chat-log.md",
]

SYSTEM_INSTRUCTION = (
    "You are a DND session summarizer bot. "
    "You read the instructions and state and determine what to do. "
    "You use your knowledge of the 2024 rules to generate your summaries."
)

PROMPT_TEXT = "follow the instructions in instructions-and-state.txt"


def get_mime_type(file_path):
    """Determines the appropriate MIME type based on file extension."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".md":
        return "text/markdown"
    elif ext == ".txt":
        # The API often prefers text/plain for simple text files
        return "text/plain"
    # For any other type, let the SDK try to guess (though we manually cover the known issues)
    return None

def summarize_dnd_session():
    """
    Uploads files, calls the Gemini API with a system prompt, and saves the result.
    """
    print("✨ Initializing Gemini client...")
    try:
        # The client will automatically pick up the GEMINI_API_KEY environment variable.
        client = genai.Client()
    except Exception as e:
        print(f"🛑 Error initializing client: {e}")
        print("Please ensure your GEMINI_API_KEY environment variable is set.")
        return

    # --- 1. Upload Files ---
    print("\n⬆️ Uploading files...")
    uploaded_files = []

    # We will also track the files we need to include in the final prompt.
    prompt_parts = []

    try:
        for file_path in FILE_PATHS:
            if not os.path.exists(file_path):
                print(f"⚠️ File not found: {file_path}. Skipping upload.")
                continue

            print(f"   - Uploading: {file_path}")

            # Determine the MIME type
            mime_type = get_mime_type(file_path)

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

    except Exception as e:
        print(f"\n🛑 Error during file upload: {e}")
        # Clean up files that were uploaded before the error
        for f in uploaded_files:
            client.files.delete(name=f.name)
        return

    # --- 2. Construct the Full Prompt and Call the API ---
    # Append the final text prompt to the parts list
    prompt_parts.append(PROMPT_TEXT)

    print("\n🧠 Calling Gemini API...")

    # Configuration for the API call
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION
    )

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt_parts,
            config=config,
        )

        # --- 3. Save the Result ---
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(response.text)

        print(f"\n✅ Success!")
        print(f"Summary saved to: {OUTPUT_FILE}")

    except Exception as e:
        print(f"\n🛑 Error during API call: {e}")

    finally:
        # --- 4. Clean Up Uploaded Files ---
        print("\n🗑️ Cleaning up uploaded files...")
        for file in uploaded_files:
            # Delete the file from the Gemini API service
            client.files.delete(name=file.name)
            print(f"   - Deleted: {file.display_name}")


if __name__ == "__main__":
    # Create the required directory structure if it doesn't exist
    os.makedirs("sessions", exist_ok=True)

    # Create placeholder files so the script can run without errors
    # In a real scenario, these files would contain your actual session data
    for path in FILE_PATHS:
        if not os.path.exists(path):
            print(f"📝 Creating placeholder file: {path}")
            with open(path, "w") as f:
                f.write(f"This is the content of {os.path.basename(path)}.")

    summarize_dnd_session()