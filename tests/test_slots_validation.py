from agents.common.slots import CANONICAL_SLOTS

def test_canonical_slots_contains_expected_minimum():
    required = {"budget_total", "destination_pref", "nights"}
    assert required.issubset(CANONICAL_SLOTS)
