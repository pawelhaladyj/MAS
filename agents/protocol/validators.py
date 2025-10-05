from __future__ import annotations
import json
from typing import Tuple
from pydantic import ValidationError
from .acl_messages import AclMessage
from .errors import ErrorCode, ERROR_MESSAGES

def validate_acl_json(blob: str, *, fallback_conversation_id: str = "invalid-conv") -> Tuple[bool, AclMessage]:
    """
    Próbuje sparsować i zwalidować AclMessage z JSON.
    Zwraca (ok, AclMessage). Gdy ok=False, AclMessage to FAILURE/ERROR(VALIDATION_ERROR).
    """
    try:
        msg = AclMessage.from_json(blob)
        return True, msg
    except (ValidationError, json.JSONDecodeError) as e:
        fail = AclMessage.build_failure(
            conversation_id=fallback_conversation_id,
            code=ErrorCode.VALIDATION_ERROR.value,
            message=ERROR_MESSAGES[ErrorCode.VALIDATION_ERROR],
            details={"err": str(e)},
        )
        return False, fail

def validate_acl_dict(data: dict, *, fallback_conversation_id: str = "invalid-conv") -> Tuple[bool, AclMessage]:
    """Wariant dla już zdekodowanego dict."""
    try:
        # szybki zrzut do JSON i z powrotem, by przejść przez jeden mechanizm walidacji
        blob = json.dumps(data)
        return validate_acl_json(blob, fallback_conversation_id=fallback_conversation_id)
    except (TypeError, ValueError) as e:
        fail = AclMessage.build_failure(
            conversation_id=fallback_conversation_id,
            code=ErrorCode.VALIDATION_ERROR.value,
            message=ERROR_MESSAGES[ErrorCode.VALIDATION_ERROR],
            details={"err": str(e)},
        )
        return False, fail
