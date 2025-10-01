# tests/test_language_guards.py
class DummyMsg:
    def __init__(self, language=None):
        # symulacja SPADE Message.metadata
        self.metadata = {}
        if language is not None:
            self.metadata["language"] = language

class DummyAcl:
    def __init__(self, language):
        self.language = language

from agents.protocol.guards import meta_language_is_json, acl_language_is_json

def test_meta_language_is_json_accepts_json_or_none():
    assert meta_language_is_json(DummyMsg("json")) is True
    assert meta_language_is_json(DummyMsg("JSON")) is True  # case-insensitive
    assert meta_language_is_json(DummyMsg(None))  is True   # brak nagłówka traktujemy jako OK
    assert meta_language_is_json(DummyMsg())      is True

def test_meta_language_is_json_rejects_non_json():
    assert meta_language_is_json(DummyMsg("xml")) is False
    assert meta_language_is_json(DummyMsg("text")) is False

def test_acl_language_is_json_accepts_json():
    assert acl_language_is_json(DummyAcl("json")) is True
    assert acl_language_is_json(DummyAcl("JSON")) is True

def test_acl_language_is_json_rejects_non_json():
    assert acl_language_is_json(DummyAcl("xml")) is False
    assert acl_language_is_json(DummyAcl(None)) is False
