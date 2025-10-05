import agents.agent as agent_mod

class DummyAgent(agent_mod.BaseAgent):
    def __init__(self):
        # nie wołamy super().__init__, żeby nie startować SPADE
        pass
    def log(self, *a, **k): pass

def test_export_metrics_calls_put_fact(monkeypatch):
    called = {}
    # podmieniamy put_fact używane w metrics.export_to_kb przez monkeypatch na module metrics
    import agents.common.metrics as metrics_mod

    def fake_put_fact(session_id, slot, payload):
        called["session_id"] = session_id
        called["slot"] = slot
        called["payload"] = payload

    monkeypatch.setattr(metrics_mod, "put_fact", fake_put_fact, raising=False)

    # strzał
    a = DummyAgent()
    slot = agent_mod.BaseAgent.export_metrics(a, session_id="system", slot_prefix="metrics")

    assert called, "put_fact should be called"
    assert called["session_id"] == "system"
    assert called["slot"].startswith("metrics_")
    assert isinstance(called["payload"], dict)
    assert slot == called["slot"]
