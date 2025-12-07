rm -rf dimg
docker stop $(docker ps -q)
docker build -t dnd-rag-ingest-gemini .
docker rm dnd-rag-ingest-gemini-instance
docker run -d -p 2222:22 --name dnd-rag-ingest-gemini-instance dnd-rag-ingest-gemini
docker cp dnd-rag-ingest-gemini-instance:/opt/python dimg
TIMESTAMP=$(date +%s)
cp lambda_function.py dimg/
cd dimg
zip -vr ../../../dnd-rag-ingest-gemini-lambda-release-${TIMESTAMP}.zip .
cd ../../../
aws lambda update-function-code --function-name=dnd-rag-ingest-gemini --zip-file=fileb://dnd-rag-ingest-gemini-lambda-release-${TIMESTAMP}.zip --no-cli-pager
cd lambda/dnd-rag-ingest-gemini