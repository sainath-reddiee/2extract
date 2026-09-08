from __future__ import annotations


class ExtractError(Exception):
    """Base error for this project."""


class TargetingError(ExtractError, ValueError):
    """Username targeting rules were violated."""


class GatewayError(ExtractError):
    """The 2extract gateway rejected the request."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        gateway_header: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.gateway_header = gateway_header


class ApiError(ExtractError):
    """The 2extract REST API returned an error envelope."""

    def __init__(self, message: str, *, status_code: int | None = None, error_type: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type
