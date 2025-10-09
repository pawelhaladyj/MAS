from agents.protocol.acl_messages import AclMessage, Performative

def test_build_request_user_msg_roundtrip():
    msg = AclMessage.build_request_user_msg(
        conversation_id="conv-1",
        text="Cześć, lecimy w lutym?",
        ontology="ui",
        session_id="conv-1",
    )
    assert msg.performative == Performative.REQUEST
    assert msg.payload["type"] == "USER_MSG"
    assert msg.payload["text"] == "Cześć, lecimy w lutym?"
    assert msg.payload["session_id"] == "conv-1"

    # roundtrip JSON
    s = msg.to_json()
    msg2 = AclMessage.from_json(s)
    assert msg2.payload == msg.payload

def test_build_inform_presenter_reply_roundtrip():
    msg = AclMessage.build_inform_presenter_reply(
        conversation_id="conv-2",
        text="Jasne! Myślisz o ciepłym kierunku czy góry?",
        ontology="ui",
        session_id="conv-2",
    )
    assert msg.performative == Performative.INFORM
    assert msg.payload["type"] == "PRESENTER_REPLY"
    assert "kierunku" in msg.payload["text"]
    assert msg.payload["session_id"] == "conv-2"

    # roundtrip JSON
    s = msg.to_json()
    msg2 = AclMessage.from_json(s)
    assert msg2.payload == msg.payload
