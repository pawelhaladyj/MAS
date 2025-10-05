import json
import agents.agent as agent_mod
from agents.protocol.acl_messages import AclMessage

class DummyBehaviour:
    def __init__(self):
        self.sent = []
    async def send(self, msg):
        self.sent.append(msg)

class DummySelf:
    async def send(self, msg):  # nieużywane tu, ale BaseAgent ma taką metodę
        pass
    def log(self, *a, **k):
        pass

def test_baseagent_send_acl_logs_out(asyncio_event_loop, monkeypatch):
    telemetry = []
    monkeypatch.setattr(
        agent_mod, "log_acl_event",
        lambda cid, d, data: telemetry.append((cid, d, data)),
        raising=False
    )

    dummy_self = DummySelf()
    beh = DummyBehaviour()
    acl = AclMessage.build_request_ask("conv-out", ["nights"])

    asyncio_event_loop.run_until_complete(
        agent_mod.BaseAgent.send_acl(dummy_self, beh, acl, to_jid="peer@xmpp")
    )

    assert telemetry, "expected OUT telemetry call"
    assert telemetry[0][0] == "conv-out" and telemetry[0][1] == "OUT"
    # i wiadomość została realnie wysłana przez behaviour:
    assert beh.sent, "behaviour.send should be called"
