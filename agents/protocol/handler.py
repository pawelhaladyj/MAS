from __future__ import annotations
from typing import Callable, Awaitable, Any, Dict, Tuple

from .acl_messages import AclMessage
from .validators import validate_acl_json
from .spade_utils import to_spade_message


def _sender_jid(raw_msg: Any) -> str:
    """
    Wydobywa nadawcę (JID) z wiadomości SPADE- podobnej.
    W testach używamy atrapy z atrybutem `.sender`; w realu SPADE daje obiekt JID -> str().
    """
    s = getattr(raw_msg, "sender", None)
    return str(s) if s is not None else ""


def _conv_id_from_meta(raw_msg: Any, default: str = "invalid-conv") -> str:
    meta = getattr(raw_msg, "metadata", None)
    if isinstance(meta, dict):
        return str(meta.get("conversation_id") or default)
    return default


def acl_handler(fn: Callable[..., Awaitable[None]]):
    """
    Dekorator dla metod zachowań (behaviour.run w SPADE):
    - Parsuje i waliduje JSON → AclMessage
    - Przy błędzie odsyła FAILURE/ERROR do nadawcy i kończy
    - Przy sukcesie wywołuje fn(self, acl: AclMessage, raw_msg)
    """
    async def wrapper(self, raw_msg: Any):
        body = getattr(raw_msg, "body", "") or ""
        fallback_cid = _conv_id_from_meta(raw_msg)
        ok, acl = validate_acl_json(body, fallback_conversation_id=fallback_cid)
        if not ok:
            to = _sender_jid(raw_msg)
            if to:
                await self.send(to_spade_message(acl, to))
            return
        await fn(self, acl, raw_msg)
    return wrapper
