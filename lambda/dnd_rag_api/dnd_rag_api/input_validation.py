import re
import datetime
from .utils import (
    create_id
)

NEGATIVE_INTEGER_REGEX = "^[\\-]*\\d+$"
DATE_REGEX = "^\\d{4}-\\d{2}-\\d{2}$"
TIME_REGEX = "^\\d{2}:\\d{2}:\\d{2}$"
FLOAT_REGEX = "^[\\-]{0,1}\\d*[\\.]{0,1}\\d+$"


def validate_unix_time(value):
    if isinstance(value, str) and value.isnumeric():
        return value
    elif isinstance(value, int):
        return str(value)
    return None


def validate_id(value):
    if not value:
        return create_id(32)
    if isinstance(value, str):
        return value
    elif isinstance(value, int):
        return str(value)
    return None


def validate_date(value):
    if isinstance(value, str) and re.match(DATE_REGEX, value):
        try:
            datetime.datetime.strptime(value, "%Y-%m-%d")
            return value
        except:
            pass
    elif isinstance(value, datetime.datetime):
        return value.strftime("%Y-%m-%d")
    return None


def validate_hms_time(value):
    if isinstance(value, str) and re.match(TIME_REGEX, value):
        try:
            datetime.datetime.strptime(value, "%H:%M:%S")
            return value
        except:
            pass
    elif isinstance(value, datetime.datetime):
        return value.strftime("%H:%M:%S")
    return None


def validate_decimal(value):
    if isinstance(value, str) and re.match(FLOAT_REGEX, value):
        return value
    elif isinstance(value, float):
        return str(value)
    return None


def validate_string(value):
    if not value:
        return None
    return str(value)


def is_valid_against_schema(value, schema):
    if schema["type"] == list or schema["type"] == dict:
        if not isinstance(value, schema["type"]):
            return False
        if schema["type"] == list:
            all_valid = True
            for value_item in value:
                all_valid = all_valid and is_valid_against_schema(value_item, schema["elements"])
            return all_valid
        if schema["type"] == dict:
            all_valid = True
            for field in schema["fields"]:
                if field["name"] not in value:
                    all_valid = False
                    break
                all_valid = all_valid and is_valid_against_schema(value[field["name"]], field)
            return all_valid
    elif callable(schema["type"]):
        if schema["type"].__call__(value):
            return True
        return False
    return False


def validate_schema(value, schema):
    if schema["type"] == list or schema["type"] == dict:
        if not isinstance(value, schema["type"]):
            return None
        if schema["type"] == list:
            output = []
            for value_item in value:
                result = validate_schema(value_item, schema["elements"])
                if not result:
                    return None
                output.append(result)
            return output;
        if schema["type"] == dict:
            output = {}
            for field in schema["fields"]:
                if field["name"] not in value:
                    return None
                result = validate_schema(value[field["name"]], field)
                if not result:
                    return None
                output[field["name"]] = result
            return output
    elif callable(schema["type"]):
        result = schema["type"].__call__(value)
        if result:
            return result
        return None
    return None


if __name__ == '__main__':
    EVENTS_SCHEMA = {
        "type": list,
        "elements": {
            "type": dict,
            "fields": [
                {"type": validate_unix_time, "name": "timestamp"},
                {"type": validate_id, "name": "hash"},
            ]
        }
    }
    print(validate_date('2024-13-13'))
    print(validate_date(datetime.datetime.now()))
    print(validate_id(-187))
    print(validate_id("-187"))
    print(validate_id("-187vb"))
    print(is_valid_against_schema([
        {
          "timestamp": "1718320743",
          "hash": "-177853341"
        },
        {
          "timestamp": "1718329743",
          "hash": "-1218480146"
        },
        {
          "timestamp": "1718329744",
          "hash": "-177853341"
        },
        {
          "timestamp": "1718329943",
          "hash": "-1218480146"
        }
    ], EVENTS_SCHEMA))
    print(f"{EVENTS_SCHEMA}")
    print(validate_schema([
        {
          "timestamp": 1718320743,
          "hash": -177853341
        },
        {
          "timestamp": "1718329743",
          "hash": "-1218480146"
        },
        {
          "timestamp": "1718329744",
          "hash": "-177853341"
        },
        {
          "timestamp": 1718329943,
          "hash": -1218480146
        }
    ], EVENTS_SCHEMA))
    CONNECTIONS_SCHEMA = {
        "type": list,
        "elements": {
            "type": list,
            "elements": {
                "type": str
            }
        }
    }
    print(validate_schema(['["GOTCHA","RATTLE","SLITHER","SURPRISE"]', '["BOO","GOTCHA","GUESS WHO","SURPRISE"]', '["BABY","CREAK","INDULGE","SEE"]', '["HISS","RATTLE","SHED","SLITHER"]', '["BAE","HUMOR","INDULGE","STRAIGHT"]', '["BABY","HUMOR","INDULGE","PAMPER"]', '["BAE","CREAK","SEE","STRAIGHT"]'], CONNECTIONS_SCHEMA))
    print(validate_schema([["GOTCHA","RATTLE","SLITHER","SURPRISE"], ["BOO","GOTCHA","GUESS WHO","SURPRISE"],
                           ["BABY","CREAK","INDULGE","SEE"], ["HISS","RATTLE","SHED","SLITHER"],
                           ["BAE","HUMOR","INDULGE","STRAIGHT"], ["BABY","HUMOR","INDULGE","PAMPER"],
                           ["BAE","CREAK","SEE","STRAIGHT"]], CONNECTIONS_SCHEMA))