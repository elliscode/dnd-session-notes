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
)


@authenticate
def get_completion_route(event, user_data, body):
    status_code = 500
    response_text = "Failed to fetch completion, pleasse try again later"
    try:
        resp = lambda_client.invoke(
            FunctionName="dnd_rag_completion",
            InvocationType="RequestResponse",
            Payload=json.dumps({"body": {"query": body["query"]}})
        )
        response_body = json.loads(resp["Payload"].read().decode())
        print(f'User: {user_data["key2"]} -- Query: {body["query"]} -- Response: {response_body["body"]}')
        status_code = response_body["statusCode"]
        response_text = response_body["body"]
    except:
        pass
    return format_response(
        event=event,
        http_code=status_code,
        body=response_text,
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