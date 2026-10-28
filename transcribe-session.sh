#!/bin/bash

set -u

HEAR="$HOME/git/hear/products/hear"
SESSIONS="$HOME/git/dnd-session-notes/session-notes/sessions"

SESSION_DATE="${1:-$(date +%Y-%m-%d)}"

if [[ ! "$SESSION_DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    echo "Error: Date must be YYYY-MM-DD."
    exit 1
fi

INPUT="${SESSIONS}/${SESSION_DATE}.mp3"
OUTPUT="${SESSIONS}/${SESSION_DATE}-transcript.md"

if [[ ! -x "$HEAR" ]]; then
    echo "Error: hear executable not found: $HEAR"
    exit 1
fi

if [[ ! -f "$INPUT" ]]; then
    echo "Error: Recording not found: $INPUT"
    exit 1
fi

TEMP_OUTPUT=$(mktemp "${OUTPUT}.tmp.XXXXXX") || exit 1
trap 'rm -f "$TEMP_OUTPUT"' EXIT

echo "Transcribing: $INPUT"

if "$HEAR" -p -d -i "$INPUT" > "$TEMP_OUTPUT"; then
    if mv "$TEMP_OUTPUT" "$OUTPUT"; then
        echo "Transcript saved: $OUTPUT"
    else
        echo "Error: Could not save transcript."
        exit 1
    fi
else
    echo "Error: Transcription failed. Existing transcript preserved."
    exit 1
fi
