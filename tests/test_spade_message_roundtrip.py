from agents.protocol.acl_messages import AclMessage, Performative
from agents.protocol.spade_utils import to_spade_message

def test_to_spade_message_roundtrip_headers_and_body():
    # źródłowy ACL
    src = AclMessage.build_request(
        conversation_id="conv-rt",
        payload={"type": "ASK", "need": ["nights"]},
        ontology="travel",
    )

    # budujemy SPADE Message
    msg = to_spade_message(src, to_jid="peer@xmpp")

    # nagłówki SPADE (metadata)
    assert msg.metadata.get("performative") == Performative.REQUEST.value
    assert msg.metadata.get("conversation_id") == "conv-rt"
    assert msg.metadata.get("ontology") == "travel"
    assert msg.metadata.get("language") == "json"

    # body to poprawny JSON i można go wczytać jako AclMessage 1:1
    dst = AclMessage.from_json(msg.body)
    assert dst.performative == src.performative
    assert dst.conversation_id == src.conversation_id
    assert dst.ontology == src.ontology
    assert dst.language == src.language
    assert dst.payload == src.payload
