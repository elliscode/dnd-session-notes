from .utils import (
    dynamo_obj_to_python_obj,
    python_obj_to_dynamo_obj,
    authenticate,
    create_id,
    dynamo,
    TABLE_NAME,
    format_response,
    boto3,
    json,
)

client = boto3.client("lambda")

@authenticate
def set_embedding(event, user_data, body):
    note_text = body.get('note', '')
    note_id = body.get('id', None)
    if not note_id:
        note_id = create_id(32)
    python_data = {
        "key1": "embedding",
        "key2": note_id,
        "text": note_text,
        "last_modified_by": user_data["key2"],
    }
    dynamo_data = python_obj_to_dynamo_obj(python_data)
    dynamo.put_item(
        TableName=TABLE_NAME,
        Item=dynamo_data,
    )
    return format_response(
        event=event,
        http_code=200,
        body=f"Successfully wrote note with ID {note_id}",
    )


@authenticate
def set_note(event, user_data, body):
    note_text = body.get('note', '')
    note_id = body.get('id', None)
    if not note_id:
        note_id = create_id(32)
    python_data = {
        "key1": "note",
        "key2": note_id,
        "text": note_text,
        "last_modified_by": user_data["key2"],
    }
    dynamo_data = python_obj_to_dynamo_obj(python_data)
    dynamo.put_item(
        TableName=TABLE_NAME,
        Item=dynamo_data,
    )
    return format_response(
        event=event,
        http_code=200,
        body=f"Successfully wrote note with ID {note_id}",
    )


@authenticate
def get_note(event, user_data, body):
    note_id = body.get('id', None)
    if not note_id:
        return format_response(
            event=event,
            http_code=400,
            body=f"You didn't provide a note-id in the body",
        )
    python_data = {
        "key1": "note",
        "key2": note_id,
    }
    dynamo_data = python_obj_to_dynamo_obj(python_data)
    data_boto = dynamo.get_item(
        TableName=TABLE_NAME,
        Key=dynamo_data,
    )
    data_dict = None
    if "Item" in data_boto:
        data_dict = dynamo_obj_to_python_obj(data_boto["Item"])
    if not data_dict or not data_dict.get("text"):
        return format_response(
            event=event,
            http_code=400,
            body=f"ID {note_id} does not exist",
        )
    return format_response(
        event=event,
        http_code=200,
        body={"message": "Successfully wrote note with ID {note_id}", "note": data_dict.get("text")},
    )


@authenticate
def get_completion_route(event, user_data, body):
    resp = client.invoke(
        FunctionName="dnd_rag_completion",
        InvocationType="RequestResponse",
        Payload=json.dumps({"body": {"query": body["query"]}})
    )
    response_body = json.loads(resp["Payload"].read().decode())
    return format_response(
        event=event,
        http_code=response_body["statusCode"],
        body=response_body["body"],
    )