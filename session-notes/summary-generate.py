from pathlib import Path
import openai
from datetime import date;


DATE = date.today().isoformat()

# Initialize the OpenAI client
client = openai.OpenAI()  # requires OPENAI_API_KEY in environment

# Paths to your files
files_to_add = [
    "sessions/instructions-and-state.txt",
    f"sessions/{DATE}-notes.md",
    f"sessions/{DATE}-transcript.md",
    f"sessions/{DATE}-chat-log.md",
]

# Read file contents
file_contents = {}
for file_path in files_to_add:
    path = Path(file_path)
    if path.exists():
        file_contents[file_path] = path.read_text(encoding="utf-8")
    else:
        print(f"Warning: {file_path} does not exist.")
        file_contents[file_path] = ""

# System and user prompts
system_prompt = (
    "You are a DND session summarizer bot. "
    "You read the instructions and state and determine what to do. "
    "You use your knowledge of the 2024 rules to generate your summaries. "
)
user_prompt = "follow the instructions in instructions-and-state.txt"

# Combine file contents for context
context_text = "\n\n".join(f"--- {fname} ---\n{content}" for fname, content in file_contents.items())

# Call the Chat API
response = client.chat.completions.create(
    model="gpt-4.1-mini",
    max_tokens=800,
    # store=True,
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"{user_prompt}\n\n{context_text}"}
    ],
)

# Extract summary
summary_text = response.choices[0].message.content

# Save to file
summary_path = Path(f"sessions/{DATE}-summary.md")
summary_path.write_text(summary_text, encoding="utf-8")

print(f"Summary written to {summary_path}")
