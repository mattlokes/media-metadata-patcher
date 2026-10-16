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
