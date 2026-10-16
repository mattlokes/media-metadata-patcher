import json

from hass_sonos_metadata_mux.alexa import parse_push_message, push_serial


def _directive(command, payload):
    resource = {"command": command, "payload": json.dumps(payload)}
    return {"directive": {"payload": {"renderingUpdates": [{"resourceMetadata": json.dumps(resource)}]}}}


def test_parse_push_message_unwraps_nested_json():
    payload = {"dopplerId": {"deviceSerialNumber": "SERIAL1", "deviceType": "T"}}
    assert parse_push_message(_directive("PUSH_MEDIA_CHANGE", payload)) == [
        ("PUSH_MEDIA_CHANGE", payload)
    ]


def test_parse_push_message_skips_malformed():
    message = {"directive": {"payload": {"renderingUpdates": [{"resourceMetadata": "not json"}]}}}
    assert parse_push_message(message) == []
    assert parse_push_message({}) == []


def test_push_serial_variants():
    assert push_serial({"dopplerId": {"deviceSerialNumber": "A"}}) == "A"
    assert push_serial({"key": {"entryId": "x#y#B"}}) == "B"
    assert push_serial({"key": {"serialNumber": "C"}}) == "C"
    assert push_serial({}) is None


def test_enrollment_url_uses_working_signin_page():
    from yarl import URL

    from hass_sonos_metadata_mux.alexa import _Enrollment

    flow = _Enrollment("amazon.co.uk")
    url = URL(flow.oauth_url)
    assert (url.host, url.path) == ("www.amazon.com", "/ap/signin")
    assert url.query["openid.return_to"] == "https://www.amazon.com/ap/maplanding"
    assert url.query["openid.oa2.code_challenge"] == flow.code_challenge
    assert url.query["language"] == "en_GB"

    pasted = "https://www.amazon.com/ap/maplanding?openid.oa2.authorization_code=CODE"
    assert flow.parse_redirect_url(pasted) == "CODE"
