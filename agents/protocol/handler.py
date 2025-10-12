from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Optional

from agents.common.telemetry import log_acl_event
from agents.common.metrics import inc

from .acl_messages import AclMessage
from .validators import validate_acl_json
from .spade_utils import to_spade_message

# agents/protocol/handler.py
from enum import Enum

class ErrorCode(str, Enum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    LANGUAGE_NOT_JSON = "LANGUAGE_NOT_JSON"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    BODY_TOO_LARGE = "BODY_TOO_LARGE"
    IDLE = "IDLE"
    UNKNOWN_SLOT = "UNKNOWN_SLOT"
    UNKNOWN = "UNKNOWN"

# Słownik komunikatów – klucze jako stringi (testy często odwołują się po literalach)
ERROR_MESSAGES: dict[str, str] = {
    "VALIDATION_ERROR": "Validation failed.",
    "LANGUAGE_NOT_JSON": "ACL language must be JSON.",
    "PAYLOAD_TOO_LARGE": "Payload too large.",
    "BODY_TOO_LARGE": "Body too large.",
    "IDLE": "No activity (idle).",
    "UNKNOWN_SLOT": "Unknown slot.",
    "UNKNOWN": "Unknown error.",
}

def _sender_jid(raw_msg: Any) -> str:
    s = getattr(raw_msg, "sender", None)
    return str(s) if s is not None else ""


def _conv_id_from_meta(raw_msg: Any, default: str = "invalid-conv") -> str:
    meta = getattr(raw_msg, "metadata", None)
    if isinstance(meta, dict):
        return str(meta.get("conversation_id") or default)
    return default


def acl_handler(fn: Callable[..., Awaitable[None]]):
    async def wrapper(self, maybe_raw_msg: Optional[Any] = None):
        raw_msg = maybe_raw_msg

        # Tryb A: bez wiadomości -> odbierz ze skrzynki (SPADE) z „idle guardem”
        if raw_msg is None:
            receive = getattr(self, "receive", None)
            if not callable(receive):
                return

            timeout = getattr(self, "acl_handler_timeout", 1.0)
            raw_msg = await receive(timeout=timeout)

            if raw_msg is None:
                # idle guard
                try:
                    max_idle = int(getattr(self, "acl_max_idle_ticks", 0))  # 0 = wyłączone
                except Exception:
                    max_idle = 0

                if max_idle > 0:
                    ticks = int(getattr(self, "_acl_idle_ticks", 0)) + 1
                    setattr(self, "_acl_idle_ticks", ticks)
                    if ticks >= max_idle:
                        kill = getattr(self, "kill", None)
                        if callable(kill):
                            await kill()
                        return
                return
            else:
                # reset licznika, skoro przyszła realna wiadomość
                if hasattr(self, "_acl_idle_ticks"):
                    setattr(self, "_acl_idle_ticks", 0)


        body = getattr(raw_msg, "body", "") or ""
        fallback_cid = _conv_id_from_meta(raw_msg)

        # NEW: limit rozmiaru body (UTF-8 bytes)
        try:
            max_bytes = int(getattr(self, "acl_max_body_bytes", 64 * 1024))
        except Exception:
            max_bytes = 64 * 1024
        size_bytes = len(body.encode("utf-8"))
        if size_bytes > max_bytes:
            # metrics
            try:
                inc("acl_in_body_too_large_total", 1)
            except Exception:
                pass

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
            # metrics
            try:
                inc("acl_in_validation_errors_total", 1)
            except Exception:
                pass

            to = _sender_jid(raw_msg)
            if to:
                await self.send(to_spade_message(acl, to))
            return

        # TELEMETRIA IN (po udanym parsowaniu ACL)
        try:
            log_acl_event(acl.conversation_id, "IN", json.loads(acl.to_json()))
        except Exception:
            pass
        
        # ⬇⬇⬇ METRICS IN — NOWA WSTAWKA
        try:
            inc("acl_in_total", 1)
            p = getattr(acl, "performative", None)
            if p and getattr(p, "value", None):
                inc(f"acl_in_performative_{p.value}", 1)
            ptype = (acl.payload or {}).get("type")
            if isinstance(ptype, str):
                inc(f"acl_in_type_{ptype}", 1)
        except Exception:
            pass
        # ⬆⬆⬆ KONIEC WSTAWKI

        await fn(self, acl, raw_msg)
    return wrapper

