from .utils import (
    dynamo_obj_to_python_obj,
    python_obj_to_dynamo_obj,
    authenticate,
    create_id,
    dynamo,
    TABLE_NAME,
    format_response,
    json,
    s3,
    lambda_client,
    S3_BUCKET,
    time,
)


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

    prefix = "session-notes/"

    files = []

    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            files.append(obj["Key"].removeprefix(prefix))

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