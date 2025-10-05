from agents.protocol import (
    AclMessage, Performative,
    ErrorCode, ERROR_MESSAGES,
    validate_acl_json, validate_acl_dict,
)
import json

def test_validate_acl_json_ok():
    src = AclMessage.build_inform_fact("conv-ok", "budget_total", 9999)
    ok, msg = validate_acl_json(src.to_json())
    assert ok is True
    assert msg.performative == Performative.INFORM
    assert msg.payload["type"] == "FACT"

def test_validate_acl_json_bad_malformed():
    ok, msg = validate_acl_json("{not-json", fallback_conversation_id="conv-bad")
    assert ok is False
    assert msg.performative == Performative.FAILURE
    assert msg.payload["type"] == "ERROR"
    assert msg.payload["code"] == ErrorCode.VALIDATION_ERROR.value
    assert msg.conversation_id == "conv-bad"

def test_validate_acl_dict_bad_semantic():
    # REQUEST z niedozwolonym payload.type
    data = {
        "performative": "REQUEST",
        "conversation_id": "conv-sem",
        "ontology": "default",
        "language": "json",
        "payload": {"type": "FACT", "slot": "x", "value": 1},
    }
    ok, msg = validate_acl_dict(data)
    assert ok is False
    assert msg.performative == Performative.FAILURE
    assert msg.payload["code"] == ErrorCode.VALIDATION_ERROR.value
