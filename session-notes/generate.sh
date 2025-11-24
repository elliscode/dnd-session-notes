#!/bin/bash

set -e

# Directory to scan (defaults to current directory)
DIR="${1:-.}"

OUTPUT="sessions/instructions-and-state.txt"

# Empty or create the output file
> "$OUTPUT"

# Find all .md files not starting with YYYY-MM-DD-
# Regex: skip files that start with 4 digits, dash, 2 digits, dash, 2 digits, dash
FILES=""

while IFS= read -r entry; do
  # Skip empty lines or comments in manifest (if any)
  [ -z "$entry" ] && continue

  # Prefix: includes a trailing slash
  if [[ "$entry" == */ ]]; then
    # Find all .md files starting with this prefix
    matches=$(find "$DIR/$entry" -type f -name "*.md" \
      ! -regex ".*/[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}-.*" \
      | sort)

    FILES="$FILES"$'\n'"$matches"

  else
    # Exact file
    if [[ -f "$DIR/$entry" ]]; then
      FILES="$FILES"$'\n'"$DIR/$entry"
    fi
  fi
done < manifest.txt

# Trim leading newline
FILES=$(echo "$FILES" | sed '/^\s*$/d')

echo "Combining the following files:"
echo "$FILES"
echo

# Append each file into output
for f in $FILES; do
  if [[ "$f" == ./characters/* ]]; then
    # Strip all newlines before adding
    tr -d '\n' < "$f" >> "$OUTPUT"
    echo "" >> "$OUTPUT"
  else
    # Normal append
    cat "$f" >> "$OUTPUT"
  fi
done

echo "Done! Wrote output to $OUTPUT"
