from agents.common.config import settings
import agents.presenter as presenter_mod
import agents.coordinator as coordinator_mod

def test_presenter_onacl_reads_limits_from_settings():
    assert presenter_mod.PresenterAgent.OnACL.acl_max_body_bytes == settings.acl_max_body_bytes
    assert presenter_mod.PresenterAgent.OnACL.acl_max_idle_ticks == settings.acl_max_idle_ticks

def test_coordinator_onacl_reads_limits_from_settings():
    assert coordinator_mod.CoordinatorAgent.OnACL.acl_max_body_bytes == settings.acl_max_body_bytes
    assert coordinator_mod.CoordinatorAgent.OnACL.acl_max_idle_ticks == settings.acl_max_idle_ticks
