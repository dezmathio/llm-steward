"""
LLM Steward - Guardrails Module
====================================
Custom guardrails and callback handlers for the gateway.
"""

# Lazy imports to avoid requiring litellm for basic usage
__all__ = ["gateway_logger", "log_success", "log_failure", "get_custom_recognizers"]


def __getattr__(name):
    """Lazy loading of callback handler (requires litellm)."""
    if name in ("gateway_logger", "log_success", "log_failure"):
        from .custom_callback_handler import gateway_logger, log_success, log_failure
        return {"gateway_logger": gateway_logger, "log_success": log_success, "log_failure": log_failure}[name]
    if name == "get_custom_recognizers":
        from .custom_recognizers import get_custom_recognizers
        return get_custom_recognizers
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
