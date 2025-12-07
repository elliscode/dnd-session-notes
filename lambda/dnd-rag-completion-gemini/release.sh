rm -rf dimg
docker stop $(docker ps -q)
docker build -t dnd-rag-completion-gemini .
docker rm dnd-rag-completion-gemini-instance
docker run -d -p 2222:22 --name dnd-rag-completion-gemini-instance dnd-rag-completion-gemini
docker cp dnd-rag-completion-gemini-instance:/opt/python dimg
TIMESTAMP=$(date +%s)
cp lambda_function.py dimg/
cd dimg
zip -vr ../../../dnd-rag-completion-gemini-lambda-release-${TIMESTAMP}.zip .
cd ../../../
aws lambda update-function-code --function-name=dnd-rag-completion-gemini --zip-file=fileb://dnd-rag-completion-gemini-lambda-release-${TIMESTAMP}.zip --no-cli-pager
cd lambda/dnd-rag-completion-gemini