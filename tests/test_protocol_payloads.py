from agents.protocol.acl_messages import AclMessage, Performative
import pytest

def test_build_request_ask_ok():
    m = AclMessage.build_request_ask("demo-1", ["dates", "party_size"], ontology="travel")
    assert m.performative == Performative.REQUEST
    assert m.payload["type"] == "ASK"
    assert m.payload["need"] == ["dates", "party_size"]
    assert m.ontology == "travel"

def test_build_request_ask_rejects_empty_or_dupes():
    with pytest.raises(Exception):
        AclMessage.build_request_ask("demo-1", [])
    with pytest.raises(Exception):
        AclMessage.build_request_ask("demo-1", ["dates", "dates"])

def test_build_inform_fact_ok():
    m = AclMessage.build_inform_fact("conv-x", "budget_total", 12000)
    assert m.performative == Performative.INFORM
    assert m.payload["type"] == "FACT"
    assert m.payload["slot"] == "budget_total"
    assert m.payload["value"] == 12000

def test_build_inform_fact_rejects_blank_slot():
    with pytest.raises(Exception):
        AclMessage.build_inform_fact("conv-x", "  ", 1)

def test_build_inform_ack_ok():
    m = AclMessage.build_inform_ack("conv-ack", {"type": "PING"})
    assert m.performative == Performative.INFORM
    assert m.payload["type"] == "ACK"
    assert m.payload["echo"] == {"type": "PING"}
