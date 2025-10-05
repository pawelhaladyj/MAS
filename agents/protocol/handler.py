from __future__ import annotations
from typing import Any, Awaitable, Callable, Optional

from .acl_messages import AclMessage
from .validators import validate_acl_json
from .spade_utils import to_spade_message


def _sender_jid(raw_msg: Any) -> str:
    s = getattr(raw_msg, "sender", None)
    return str(s) if s is not None else ""


def _conv_id_from_meta(raw_msg: Any, default: str = "invalid-conv") -> str:
    meta = getattr(raw_msg, "metadata", None)
    if isinstance(meta, dict):
        return str(meta.get("conversation_id") or default)
    return default


def acl_handler(fn: Callable[..., Awaitable[None]]):
    """
    Dekorator dla metod zachowań (SPADE-like):

    - Tryb A: SPADE wywołuje run(self) bez argumentów -> dekorator sam robi await self.receive(timeout=...).
    - Tryb B: Testy/atrapy wywołują run(self, raw_msg) -> używamy przekazanego raw_msg.

    Walidacja:
    - limit rozmiaru body (domyślnie 64 KB, można nadpisać self.acl_max_body_bytes),
    - JSON -> AclMessage (validate_acl_json),
    - przy błędzie odsyła FAILURE/ERROR do nadawcy.
    """
    async def wrapper(self, maybe_raw_msg: Optional[Any] = None):
        raw_msg = maybe_raw_msg

        # Tryb A: bez wiadomości -> odbierz ze skrzynki (SPADE)
        if raw_msg is None:
            receive = getattr(self, "receive", None)
            if callable(receive):
                timeout = getattr(self, "acl_handler_timeout", 1.0)
                raw_msg = await receive(timeout=timeout)
                if raw_msg is None:
                    return  # brak wiadomości w tym ticku
            else:
                return

        body = getattr(raw_msg, "body", "") or ""
        fallback_cid = _conv_id_from_meta(raw_msg)

        # NEW: limit rozmiaru body (UTF-8 bytes)
        try:
            max_bytes = int(getattr(self, "acl_max_body_bytes", 64 * 1024))
        except Exception:
            max_bytes = 64 * 1024
        size_bytes = len(body.encode("utf-8"))
        if size_bytes > max_bytes:
            # budujemy FAILURE ręcznie (bez validate_acl_json, bo body może być gigantyczne)
            fail = AclMessage.build_failure(
                conversation_id=fallback_cid,
                code="VALIDATION_ERROR",
                message="ACL body too large",
                details={"size_bytes": size_bytes, "max_bytes": max_bytes},
            )
            to = _sender_jid(raw_msg)
            if to:
                await self.send(to_spade_message(fail, to))
            return
        # END NEW

        ok, acl = validate_acl_json(body, fallback_conversation_id=fallback_cid)
        if not ok:
            to = _sender_jid(raw_msg)
            if to:
                await self.send(to_spade_message(acl, to))
            return

        await fn(self, acl, raw_msg)

    return wrapper
