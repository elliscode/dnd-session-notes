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