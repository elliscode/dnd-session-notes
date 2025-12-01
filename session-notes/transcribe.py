from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI

client = OpenAI()

chunks = [
    "2025-11-25-03.mp3",
    "2025-11-25-04.mp3",
    "2025-11-25-05.mp3",
    "2025-11-25-06.mp3",
]

def transcribe_chunk(chunk_path):
    with open(chunk_path, "rb") as f:
        result = client.audio.transcriptions.create(
            model="gpt-4o-transcribe-diarize",
            file=f,
            chunking_strategy="auto",
            response_format="diarized_json"
        )
    return result

results = []

with ThreadPoolExecutor(max_workers=6) as executor:
    future_to_chunk = {executor.submit(transcribe_chunk, c): c for c in chunks}
    for future in as_completed(future_to_chunk):
        chunk_name = future_to_chunk[future]
        try:
            res = future.result()
            results.append((chunk_name, res))
            print(f"Completed {chunk_name}")
        except Exception as e:
            print(f"Error in {chunk_name}: {e}")

import json; json.dump(results, open("results.json", "w"))

