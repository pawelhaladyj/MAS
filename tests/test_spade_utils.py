from agents.protocol.acl_messages import AclMessage, Performative
from agents.protocol.spade_utils import to_spade_message

def test_to_spade_message_sets_headers_and_body():
    acl = AclMessage.build_inform(
        conversation_id="conv-xyz",
        payload={"type": "CONFIRM", "slot": "budget_total", "status": "saved"},
        ontology="demo",
    )

    msg = to_spade_message(acl, to_jid="someone@example.com")

    # adresat
    assert str(msg.to) == "someone@example.com"

    # metadane SPADE
    assert msg.metadata.get("performative") == acl.performative.value
    assert msg.metadata.get("conversation_id") == "conv-xyz"
    assert msg.metadata.get("ontology") == "demo"
    assert msg.metadata.get("language") == "json"

    # treść (JSON string) — minimalna weryfikacja
    assert isinstance(msg.body, str)
    assert '"performative":"INFORM"' in msg.body
    assert '"conversation_id":"conv-xyz"' in msg.body
    assert '"payload":{"type":"CONFIRM"' in msg.body
