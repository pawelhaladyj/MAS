from agents.protocol.acl_messages import AclMessage, Performative
import pytest

def test_failure_must_carry_error():
    msg = AclMessage.build_failure("demo-1", "VALIDATION_ERROR", "bad")
    assert msg.performative == Performative.FAILURE
    assert msg.payload.get("type") == "ERROR"
    assert msg.payload.get("code") == "VALIDATION_ERROR"

def test_request_rejects_wrong_payload_type():
    with pytest.raises(Exception):
        AclMessage.build_request("demo-1", {"type": "FACT", "slot": "x", "value": 1})
