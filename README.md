# D&D Session Notes

## Backend

### dnd_rag_ingest

A containerized lambda function that does the following:

- downloads the chromadb data from S3 in the `chromadb.zip` file
- downloads the list of markdown files from S3 in the `session-notes/` S3 prefix
- updates the chromadb data with the markdown files that were updated, deleted, or renamed
- saves the chromadb data back to S3 in the `chromadb.zip` file

### dnd_rag_completion

A containerized lambda function that does the following:

- downloads the chromadb data from S3 in the `chromadb.zip` file
- queries the chromadb data for the 5 most similar data points closest to the supplied `query`
- passes the `query` and the similar data points to the OpenAI API to answer the question

### dnd_rag_api

A python runtime lambda function that allows for login, file manageent, and access to the RAG answering utility.

## Frontend

The frontend is a CloudFront distribution pointing to an S3 bucket, which talks to the backend.

## Scripts

I have some miscellaneous scripts in the `session-notes/` directory, used for actually creating the inputs for the other apps above

### `generate.sh`

This file exclusively combines LLM instructions, campaign state, and big-picture notes in one doc for use with the `summary-generate.py` method

#### Setup

- create a `mainifest.txt` which lists all of the files and folders to be combined, example below.

```manifest.txt
instructions.ignore.md
characters-header.ignore.md
characters/
after-characters-spacing.ignore.md
campaign-setting-map.md
important-places.md
important-items.md
important-groups.md
```

- `.ignore.md` is an extension that does *not* get uploaded when running `sync-notes.py`, so you can create secret DM-only notes that don't get used in the RAG completion but do get used for summarizing things.
- you can set a directory in the `manifest.txt` and the `generate.sh` script will walk th edirectory and find all the `*.md` files

#### Running

```
cd session-notes/
sh generate.sh
```

This will generate a file in `sessions/instructions-and-state.txt`

### `summary-generate.py`

This script requires a `OPENAI_API_KEY` environment variable.

#### Setup

- set your `OPENAI_API_KEY` environment variable
- create three files 
    - `sessions/YYYY-MM-DD-chat-log.md`
    - `sessions/YYYY-MM-DD-notes.md`
    - `sessions/YYYY-MM-DD-summary.md`
- run the `generate.sh` script to create `sessions/instructions-and-state.txt`

#### Running

Once you run the script with whatever flavor of python (uv, pipenv, whatever idc), it will generate a `sessions/YYYY-MM-DD-summary.md`

### `sync-notes.py`

This script syncs between your local `session-notes` folder and a S3 bucket defined on `BUCKET` and a prefix defined on `PREFIX`

Once you run the script with whatever flavor of python (uv, pipenv, whatever idc), it will interactively ask you how to resolve conflicts between files.

### Hear command

To make the transcripts, i use the `hear` command, here's an example

```
./hear -p -d -i ../../dnd-session-notes/session-notes/2025-12-09.mp3 > ../../dnd-session-notes/session-notes/2025-12-09.txt
```