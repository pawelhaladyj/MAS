from __future__ import annotations
from enum import Enum

class ErrorCode(str, Enum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    TIMEOUT = "TIMEOUT"
    DOWNSTREAM_UNAVAILABLE = "DOWNSTREAM_UNAVAILABLE"
    UNSUPPORTED_MESSAGE = "UNSUPPORTED_MESSAGE"
    UNAUTHORIZED = "UNAUTHORIZED"

ERROR_MESSAGES = {
    ErrorCode.VALIDATION_ERROR: "Message validation failed",
    ErrorCode.TIMEOUT: "Operation timed out",
    ErrorCode.DOWNSTREAM_UNAVAILABLE: "Downstream service unavailable",
    ErrorCode.UNSUPPORTED_MESSAGE: "Unsupported payload type",
    ErrorCode.UNAUTHORIZED: "Unauthorized",
}
