TIMESTAMP=$(date +%s)
zip -vr ../../dnd-rag-api-lambda-release-${TIMESTAMP}.zip . -i "*.py"
cd ../../
aws lambda update-function-code --function-name=dnd-notes-lambda --zip-file=fileb://dnd-rag-api-lambda-release-${TIMESTAMP}.zip --no-cli-pager
cd lambda/dnd-notes-lambda