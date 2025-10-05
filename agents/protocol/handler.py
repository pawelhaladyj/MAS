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
      Timeout można nadpisać atrybutem self.acl_handler_timeout (sekundy), domyślnie 1.0.
    - Tryb B: Testy/atrapy wywołują run(self, raw_msg) -> używamy przekazanego raw_msg.

    Przy błędzie walidacji odsyła FAILURE/ERROR do nadawcy i kończy.
    Przy sukcesie woła fn(self, acl: AclMessage, raw_msg).
    """
    async def wrapper(self, maybe_raw_msg: Optional[Any] = None):
        raw_msg = maybe_raw_msg

        # Tryb A: bez wiadomości -> odbierz ze skrzynki (SPADE)
        if raw_msg is None:
            # SPADE Behaviour ma metodę receive()
            receive = getattr(self, "receive", None)
            if callable(receive):
                timeout = getattr(self, "acl_handler_timeout", 1.0)
                raw_msg = await receive(timeout=timeout)
                if raw_msg is None:
                    return  # brak wiadomości w tym ticku
            else:
                # Brak receive(): nie da się nic zrobić
                return

        body = getattr(raw_msg, "body", "") or ""
        fallback_cid = _conv_id_from_meta(raw_msg)
        ok, acl = validate_acl_json(body, fallback_conversation_id=fallback_cid)
        if not ok:
            to = _sender_jid(raw_msg)
            if to:
                # zakładamy, że self ma metodę send()
                await self.send(to_spade_message(acl, to))
            return

        await fn(self, acl, raw_msg)

    return wrapper
