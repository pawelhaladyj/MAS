# tests/test_acl_roundtrip.py
from agents.protocol.acl_messages import AclMessage, Performative

def test_acl_roundtrip_request_inform():
    src = AclMessage.build_request(
        conversation_id="conv-1",
        payload={"type": "PING"},
        ontology="demo",
    )
    js = src.to_json()
    dst = AclMessage.from_json(js)

    # asercje podstawowe
    assert dst.performative == Performative.REQUEST
    assert dst.conversation_id == "conv-1"
    assert dst.ontology == "demo"
    assert dst.language == "json"
    assert dst.payload == {"type": "PING"}

    # drugi przebieg (INFORM)
    src2 = AclMessage.build_inform(
        conversation_id="conv-2",
        payload={"type": "ACK", "echo": {"type": "PING"}},
        ontology="demo",
    )
    js2 = src2.to_json()
    dst2 = AclMessage.from_json(js2)
    assert dst2.performative == Performative.INFORM
    assert dst2.conversation_id == "conv-2"
    assert dst2.ontology == "demo"
    assert dst2.payload["type"] == "ACK"
