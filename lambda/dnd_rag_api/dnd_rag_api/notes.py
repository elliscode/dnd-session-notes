from .utils import (
    dynamo_obj_to_python_obj,
    python_obj_to_dynamo_obj,
    authenticate,
    dynamo,
    TABLE_NAME,
    format_response,
    json,
    s3,
    lambda_client,
    S3_BUCKET,
    time,
    re,
)
import html

PREFIX = "session-notes/"
SAFE_MD = re.compile(r"^[/A-Za-z0-9_-]+\.md$", re.IGNORECASE)


@authenticate
def get_completion_route(event, user_data, body):
    status_code = 500
    question = "No question provided"
    response_text = "Failed to fetch completion, pleasse try again later"
    time_value = int(time.time())
    try:
        question = body["query"]
        resp = lambda_client.invoke(
            FunctionName="dnd_rag_completion",
            InvocationType="RequestResponse",
            Payload=json.dumps({"body": {"query": question}})
        )
        response_body = json.loads(resp["Payload"].read().decode())
        print(f'User: {user_data["key2"]} -- Query: {question} -- Response: {response_body["body"]}')
        status_code = response_body["statusCode"]
        response_text = response_body["body"]
        # write to DB
        completion_data = {
            "key1": "completion",
            "key2": f'{user_data["key2"]}#{time_value}',
            "user": user_data["key2"],
            "time": int(time.time()),
            "query": question,
            "response": response_text,
            "expiration": int(time.time()) + (60 * 60 * 24 * 30),
        }
        dynamo.put_item(
            TableName=TABLE_NAME,
            Item=python_obj_to_dynamo_obj(completion_data),
        )
    except:
        pass
    return format_response(
        event=event,
        http_code=status_code,
        body={
            "time": time_value,
            "query": question,
            "response": response_text,
        }
    )


@authenticate
def get_notes_list_route(event, user_data, body):
    paginator = s3.get_paginator("list_objects_v2")

    files = []

    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=PREFIX):
        for obj in page.get("Contents", []):
            files.append(obj["Key"].removeprefix(PREFIX))

    return format_response(
        event=event,
        http_code=200,
        body=files,
    )


@authenticate
def get_previous_queries_route(event, user_data, body):
    response = dynamo.query(
        TableName=TABLE_NAME,
        KeyConditions={
            "key1": {"AttributeValueList": [{"S": "completion"}], "ComparisonOperator": "EQ"},
            "key2": {
                "AttributeValueList": [{"S": user_data["key2"]}],
                "ComparisonOperator": "BEGINS_WITH",
            },
        },
    )
    output = []
    if "Items" not in response:
        return format_response(
            event=event,
            http_code=201,
            body=output,
        )
    for item in response["Items"]:
        python_item = dynamo_obj_to_python_obj(item)
        output.append({
            "time": int(python_item["time"]),
            "query": python_item["query"],
            "response": python_item["response"],
        })
    return format_response(
        event=event,
        http_code=200,
        body=output,
    )

@authenticate
def get_note_route(event, user_data, body):
    filename = validate_filename(body["filename"])
    if not filename:
        return format_response(
            event=event,
            http_code=400,
            body="Bad input, must include filename with a .md extension",
        )
    full_path = PREFIX + filename
    response = s3.get_object(Bucket=S3_BUCKET, Key=full_path)
    text = response["Body"].read().decode("utf-8")
    return format_response(
        event=event,
        http_code=200,
        body={
            "filename": filename,
            "content": html.escape(text),
        },
    )


@authenticate
def delete_note_route(event, user_data, body):
    filename = validate_filename(body["filename"])
    if not filename:
        return format_response(
            event=event,
            http_code=400,
            body="Bad input, must include filename with a .md extension",
        )
    full_path = PREFIX + filename
    s3.delete_object(Bucket=S3_BUCKET, Key=full_path)
    return format_response(
        event=event,
        http_code=200,
        body=f"Successfully deleted {filename}",
    )



@authenticate
def set_note_route(event, user_data, body):
    output = {}
    filename = validate_filename(body["filename"])
    if not filename:
        return format_response(
            event=event,
            http_code=400,
            body="Bad input, must include filename with a .md extension",
        )
    old_filename = validate_filename(body["old_filename"])
    if old_filename and old_filename != filename:
        full_path = PREFIX + old_filename
        response = s3.delete_object(Bucket=S3_BUCKET, Key=full_path)
        output['delete'] = old_filename
        if 'ResponseMetadata' in response and 'HTTPStatusCode' in response['ResponseMetadata'] and response['ResponseMetadata']['HTTPStatusCode'] == 204:
            output['delete'] = old_filename
    full_path = PREFIX + filename
    response = s3.put_object(Bucket=S3_BUCKET, Key=full_path, Body=body['content'].encode('utf-8'))
    if 'ETag' not in response:
        return format_response(
            event=event,
            http_code=500,
            body="Failed to write file",
        )
    output['write'] = filename
    return format_response(
        event=event,
        http_code=200,
        body=output,
    )


def validate_filename(name: str):
    if not SAFE_MD.fullmatch(name):
        return None
    return name