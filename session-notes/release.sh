aws s3 sync . s3://daniel-townsend-dnd-notes-userspace/session-notes/ --exclude "*" --include "*.md" --exclude "*.ignore.md" --delete
