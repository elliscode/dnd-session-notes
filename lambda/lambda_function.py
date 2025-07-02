import json
import traceback

from dndnotes.utils import (
    otp_route,
    login_route,
    path_equals,
    format_response,
    ios_cookie_refresh_route,
    clear_all_tokens_route,
    logged_in_check_route,
)

from dndnotes.notes import (
    set_note,
    get_note,
)


def lambda_handler(event, context):
    try:
        print(json.dumps(event))
        result = route(event)
        print(result)
        return result
    except Exception:
        traceback.print_exc()
        return format_response(event=event, http_code=500, body="Internal server error")


# Only using POST because I want to prevent CORS preflight checks, and setting a
# custom header counts as "not a simple request" or whatever, so I need to pass
# in the CSRF token (don't want to pass as a query parameter), so that really
# only leaves POST as an option, as GET has its body removed by AWS somehow
#
# see https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS#simple_requests
def route(event):
    if path_equals(event=event, method="POST", path="/otp"):
        return otp_route(event)
    if path_equals(event=event, method="POST", path="/login"):
        return login_route(event)
    if path_equals(event=event, method="POST", path="/logout-all"):
        return clear_all_tokens_route(event)
    if path_equals(event=event, method="POST", path="/logged-in-check"):
        return logged_in_check_route(event)
    if path_equals(event=event, method="POST", path="/ios-cookie-refresh"):
        return ios_cookie_refresh_route(event)
    if path_equals(event=event, method="POST", path="/set-note"):
        return set_note(event)
    if path_equals(event=event, method="POST", path="/get-note"):
        return get_note(event)

    return format_response(event=event, http_code=404, body="No matching route found")
