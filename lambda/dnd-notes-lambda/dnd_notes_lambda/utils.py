import json
import os
import re
import secrets
import time
import urllib

import boto3
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

ADMIN_PHONE = os.environ.get("ADMIN_PHONE")
HTTPS_DOMAIN_NAME = os.environ.get("HTTPS_DOMAIN_NAME")
DOMAIN_NAME = os.environ.get("DOMAIN_NAME")
APP_NAME = os.environ.get("APP_NAME")
TABLE_NAME = os.environ.get("DYNAMODB_TABLE_NAME")
SMS_SQS_QUEUE_URL = os.environ.get("SMS_SQS_QUEUE_URL")
SMS_SQS_QUEUE_ARN = os.environ.get("SMS_SQS_QUEUE_ARN")
S3_BUCKET = os.environ.get("S3_BUCKET")
STARTING_FILE = "dnd_rag_completion.STARTING"

digits = "0123456789"
lowercase_letters = "abcdefghijklmnopqrstuvwxyz"
uppercase_letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
dynamo = boto3.client("dynamodb")
sqs = boto3.client("sqs")
scheduler = boto3.client("scheduler")
lambda_client = boto3.client("lambda")
s3 = boto3.client("s3")


def format_response(event, http_code, body, headers=None):
    domain_name = HTTPS_DOMAIN_NAME
    if isinstance(body, str):
        body = {"message": body}
    elif "origin" in event["headers"] and event["headers"]["origin"].startswith(HTTPS_DOMAIN_NAME):
        pass
    else:
        print(f'Invalid origin {event["headers"].get("origin")}')
        http_code = 403
        body = {"message": "Forbidden"}
        domain_name = "*"
    all_headers = {
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Allow-Origin": domain_name,
        "Access-Control-Allow-Methods": "POST",
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Expose-Headers": "x-csrf-token",
    }
    if headers is not None:
        all_headers.update(headers)
    return {
        "statusCode": http_code,
        "body": json.dumps(body),
        "headers": all_headers,
    }


def parse_cookie(input):
    cookies = input.split(" ")
    for cookie in cookies:
        parts = cookie.split("=")
        cookie_name = parts[0].strip(" ;")
        if cookie_name == f"{APP_NAME}-auth-token":
            return parts[1].strip(" ;")


def parse_body(body):
    if isinstance(body, dict):
        return body
    elif body.startswith("{"):
        return json.loads(body)
    else:
        return dict(urllib.parse.parse_qsl(body))


def dynamo_obj_to_python_obj(dynamo_obj: dict) -> dict:
    deserializer = TypeDeserializer()
    return {k: deserializer.deserialize(v) for k, v in dynamo_obj.items()}


def python_obj_to_dynamo_obj(python_obj: dict) -> dict:
    serializer = TypeSerializer()
    return {k: serializer.serialize(v) for k, v in python_obj.items()}


def get_token(token_string):
    user_data_boto = dynamo.get_item(
        Key=python_obj_to_dynamo_obj({"key1": "token", "key2": token_string}),
        TableName=TABLE_NAME,
    )
    output = None
    if "Item" in user_data_boto:
        output = dynamo_obj_to_python_obj(user_data_boto["Item"])
    return output


def delete_token(token_id):
    print("deleting token")
    dynamo.delete_item(
        Key=python_obj_to_dynamo_obj({"key1": "token", "key2": token_id}),
        TableName=TABLE_NAME,
    )


def get_user_data(username):
    user_data_boto = dynamo.get_item(
        Key=python_obj_to_dynamo_obj({"key1": "user", "key2": username}),
        TableName=TABLE_NAME,
    )
    output = None
    if "Item" in user_data_boto:
        output = dynamo_obj_to_python_obj(user_data_boto["Item"])
    return output


def path_equals(event, method, path):
    event_path = event["path"]
    event_method = event["httpMethod"]
    return event_method == method and (event_path == path or event_path == path + "/" or path == "*")


def path_starts_with(event, method, path):
    event_path = event["path"]
    event_method = event["httpMethod"]
    return event_method == method and event_path.startswith(path)


def authenticate(func):
    def wrapper_func(*args, **kwargs):
        event = args[0]
        if "cookie" not in event["headers"]:
            return format_response(event=event, http_code=403, body="No active session, please log in")
        cookie_string = event["headers"]["cookie"]
        cookie = parse_cookie(cookie_string)
        body = parse_body(event["body"])
        csrf_token = body["csrf"]
        token_data = get_token(cookie)
        if token_data is None or token_data["expiration"] < int(time.time()):
            return format_response(
                event=event,
                http_code=403,
                body="Your session has expired, please log in",
            )
        active_tokens = get_active_tokens(token_data["user"])
        if token_data["key2"] not in active_tokens["tokens"].keys():
            return format_response(
                event=event,
                http_code=403,
                body="Your session has expired, please log in",
            )
        if csrf_token is None or token_data["csrf"] != csrf_token:
            delete_token(token_data["key1"])
            return format_response(
                event=event,
                http_code=403,
                body="Your CSRF token is invalid, your session has expired, please re log in",
            )
        user_data = get_user_data(token_data["user"])
        return func(event, user_data, body)

    return wrapper_func


@authenticate
def clear_all_tokens_route(event, user_data, body):
    active_tokens = get_active_tokens(user_data["key2"])
    active_tokens["tokens"] = {}
    dynamo.put_item(
        TableName=TABLE_NAME,
        Item=python_obj_to_dynamo_obj(active_tokens),
    )
    return format_response(
        event=event,
        http_code=200,
        body=f"Successfully logged out {user_data['key2']} of all devices",
    )


@authenticate
def ios_cookie_refresh_route(event, user_data, body):
    cookie_string = event["headers"]["cookie"]
    cookie = parse_cookie(cookie_string)
    token_data = get_token(cookie)
    # generate the date_string
    date_string = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(float(token_data["expiration"])))
    return format_response(
        event=event,
        http_code=200,
        body="successfully refreshed cookie",
        headers={
            "Set-Cookie": f'{APP_NAME}-auth-token={token_data["key2"]}; Domain=.{DOMAIN_NAME}; Expires={date_string}; Secure; HttpOnly',
        },
    )


def login_route(event):
    body = parse_body(event["body"])
    phone = body["phone"]
    submitted_otp = body["otp"]

    print(phone)
    print(submitted_otp)

    # get user data
    user_data = get_user_data(phone)
    if user_data is None:
        return format_response(event=event, http_code=500, body="No user exists")

    # get otp
    otp_data = get_otp(phone)
    if otp_data is None or otp_data["expiration"] < int(time.time()):
        return format_response(
            event=event,
            http_code=500,
            body="OTP expired, please wait 30 seconds and try to log in again",
        )
    diff = otp_data["last_failure"] + 30 - int(time.time())
    if diff > 0:
        return format_response(
            event=event,
            http_code=403,
            body=f"Please wait {diff} seconds before trying to log in again",
        )

    if submitted_otp != otp_data["otp"]:
        otp_data["last_failure"] = int(time.time())
        set_otp(phone, otp_data)
        return format_response(event=event, http_code=403, body="Incorrect OTP, please try again")

    # delete the OTP
    delete_otp(phone)
    # log in the user and send them the data
    token_data = create_token(phone)
    # store this token in the list of sessions we track, for clearing sessions manually by the user
    track_token(token_data)

    # generate the date_string
    date_string = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(time.time() + (4 * 30 * 24 * 60 * 60)))

    return format_response(
        event=event,
        http_code=200,
        body={
            "message": "successfully logged in",
            "phone": phone,
        },
        headers={
            "x-csrf-token": token_data["csrf"],
            "Set-Cookie": f'{APP_NAME}-auth-token={token_data["key2"]}; Domain=.dnd.elliscode.com; Expires={date_string}; Secure; HttpOnly',
        },
    )


def otp_route(event):
    body = parse_body(event["body"])
    phone = str(body["phone"])

    if not re.match(r"^\d{10}$", phone):
        return format_response(
            event=event,
            http_code=500,
            body="Invalid phone supplied, must be a 10 digit USA phone number",
        )

    # get or create user data
    user_data = get_user_data(phone)
    if user_data is None:
        return format_response(event=event, http_code=401, body="User is not allowed to log in. Please ask an admin to create you an account.")
    print(user_data)

    # generate and set OTP
    otp_data = get_otp(phone)
    body_value = {
        "username": phone,
        "status": f"OTP already exists for {phone}, please log in",
    }
    if otp_data is None or otp_data["expiration"] < int(time.time()):
        otp_value = "".join(secrets.choice(digits) for i in range(6))
        otp_data = create_otp(phone, otp_value)

        # generate and send message if you are creating a new otp
        message = {
            "phone": f"+1{phone}",
            "message": f"{otp_data['otp']} is your dnd.elliscode.com one-time passcode\n\n@dnd.elliscode.com #{otp_data['otp']}",
        }
        print(message)
        sqs.send_message(
            QueueUrl=SMS_SQS_QUEUE_URL,
            MessageBody=json.dumps(message),
        )
        body_value = {"username": phone}
    print(otp_data)

    return format_response(event=event, http_code=200, body=body_value)


def create_token(phone):
    python_data = {
        "key1": "token",
        "key2": create_id(32),
        "csrf": create_id(32),
        "user": phone,  # .               m    d    h    m    s
        "expiration": int(time.time()) + (4 * 30 * 24 * 60 * 60),
    }
    dynamo_data = python_obj_to_dynamo_obj(python_data)
    dynamo.put_item(
        TableName=TABLE_NAME,
        Item=dynamo_data,
    )
    return python_data


def track_token(token_data):
    active_tokens = get_active_tokens(token_data["user"])
    token_id = token_data["key2"]
    active_tokens["tokens"][token_id] = token_data["expiration"]
    dynamo.put_item(
        TableName=TABLE_NAME,
        Item=python_obj_to_dynamo_obj(active_tokens),
    )


def get_active_tokens(username):
    active_tokens_boto = dynamo.get_item(
        Key=python_obj_to_dynamo_obj({"key1": "active_tokens", "key2": username}),
        TableName=TABLE_NAME,
    )
    if "Item" in active_tokens_boto:
        active_tokens = dynamo_obj_to_python_obj(active_tokens_boto["Item"])
        active_tokens["tokens"] = {k: v for k, v in active_tokens["tokens"].items() if v > int(time.time())}
    else:
        active_tokens = {"key1": "active_tokens", "key2": username, "tokens": {}}
    return active_tokens


def set_otp(phone, python_data):
    dynamo_data = python_obj_to_dynamo_obj(python_data)
    dynamo.put_item(
        TableName=TABLE_NAME,
        Item=dynamo_data,
    )
    return python_data


def create_otp(phone, otp_value):
    python_data = {
        "key1": "otp",
        "key2": phone,
        "otp": otp_value,
        "expiration": int(time.time()) + (5 * 60),
        "last_failure": 0,
    }
    dynamo_data = python_obj_to_dynamo_obj(python_data)
    dynamo.put_item(
        TableName=TABLE_NAME,
        Item=dynamo_data,
    )
    return python_data


def get_otp(phone):
    user_data_boto = dynamo.get_item(
        Key=python_obj_to_dynamo_obj({"key1": "otp", "key2": phone}),
        TableName=TABLE_NAME,
    )
    output = None
    if "Item" in user_data_boto:
        output = dynamo_obj_to_python_obj(user_data_boto["Item"])
    return output


def delete_otp(phone):
    dynamo.delete_item(
        Key=python_obj_to_dynamo_obj({"key1": "otp", "key2": phone}),
        TableName=TABLE_NAME,
    )


def create_user_data(phone):
    python_data = {
        "key1": "user",
        "key2": phone,
    }
    dynamo_data = python_obj_to_dynamo_obj(python_data)
    dynamo.put_item(
        TableName=TABLE_NAME,
        Item=dynamo_data,
    )
    return python_data


def create_id(length):
    return "".join(secrets.choice(digits + lowercase_letters + uppercase_letters) for i in range(length))

def s3_exists(bucket, key):
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except:
        pass
    return False


@authenticate
def logged_in_check_route(event, user_data, body):
    if not s3_exists(bucket=S3_BUCKET, key=STARTING_FILE):
        lambda_client.invoke(
            FunctionName="dnd_rag_completion",
            InvocationType="Event",
            Payload=json.dumps({"body": {}})
        )
    return format_response(
        event=event,
        http_code=200,
        body={
            "message": "You are logged in",
            "phone": user_data["key2"],
        },
    )


