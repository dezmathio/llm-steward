"""
Custom PII Recognizers for Presidio
====================================
This module demonstrates how to add custom entity recognizers
to the PII guardrail. Teams can extend this for domain-specific patterns.

Example: Adding a recognizer for internal employee IDs, project codes, etc.
"""


from typing import ClassVar

from presidio_analyzer import Pattern, PatternRecognizer


class EmployeeIDRecognizer(PatternRecognizer):
    """
    Recognizes employee IDs in format: EMP-XXXX or EMP-XXXXX
    
    Example pattern for internal employee identifiers.
    Customize this for your organization's ID format.
    """
    
    PATTERNS: ClassVar[list[Pattern]] = [
        Pattern(
            "employee_id_pattern",
            r"\bEMP-\d{4,6}\b",
            0.85,
        ),
    ]
    
    CONTEXT: ClassVar[list[str]] = ["employee", "emp", "staff", "worker", "id", "identifier"]
    
    def __init__(
        self,
        patterns: list[Pattern] | None = None,
        context: list[str] | None = None,
        supported_language: str = "en",
        supported_entity: str = "EMPLOYEE_ID",
    ):
        patterns = patterns or self.PATTERNS
        context = context or self.CONTEXT
        super().__init__(
            supported_entity=supported_entity,
            patterns=patterns,
            context=context,
            supported_language=supported_language,
        )


class ProjectCodeRecognizer(PatternRecognizer):
    """
    Recognizes project codes in format: PROJ-XXX-YYYY
    
    Example: PROJ-ENG-2024, PROJ-MKT-1234
    """
    
    PATTERNS: ClassVar[list[Pattern]] = [
        Pattern(
            "project_code_pattern",
            r"\bPROJ-[A-Z]{2,4}-\d{4}\b",
            0.9,
        ),
    ]
    
    CONTEXT: ClassVar[list[str]] = ["project", "proj", "initiative", "code", "workstream"]
    
    def __init__(
        self,
        patterns: list[Pattern] | None = None,
        context: list[str] | None = None,
        supported_language: str = "en",
        supported_entity: str = "PROJECT_CODE",
    ):
        patterns = patterns or self.PATTERNS
        context = context or self.CONTEXT
        super().__init__(
            supported_entity=supported_entity,
            patterns=patterns,
            context=context,
            supported_language=supported_language,
        )


class InternalIPRecognizer(PatternRecognizer):
    """
    Recognizes internal/private IP addresses.
    
    Matches common private IP ranges:
    - 10.x.x.x
    - 172.16-31.x.x
    - 192.168.x.x
    """
    
    PATTERNS: ClassVar[list[Pattern]] = [
        Pattern(
            "private_ip_10",
            r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
            0.8,
        ),
        Pattern(
            "private_ip_172",
            r"\b172\.(1[6-9]|2[0-9]|3[0-1])\.\d{1,3}\.\d{1,3}\b",
            0.8,
        ),
        Pattern(
            "private_ip_192",
            r"\b192\.168\.\d{1,3}\.\d{1,3}\b",
            0.8,
        ),
    ]
    
    CONTEXT: ClassVar[list[str]] = ["ip", "address", "server", "host", "network", "internal"]
    
    def __init__(
        self,
        patterns: list[Pattern] | None = None,
        context: list[str] | None = None,
        supported_language: str = "en",
        supported_entity: str = "INTERNAL_IP",
    ):
        patterns = patterns or self.PATTERNS
        context = context or self.CONTEXT
        super().__init__(
            supported_entity=supported_entity,
            patterns=patterns,
            context=context,
            supported_language=supported_language,
        )


class APIKeyRecognizer(PatternRecognizer):
    """
    Recognizes common API key patterns.
    
    Matches patterns like:
    - sk-xxxx (OpenAI style)
    - pk_xxxx / sk_xxxx (Stripe style)
    - AKIA... (AWS style)
    """
    
    PATTERNS: ClassVar[list[Pattern]] = [
        Pattern(
            "openai_key",
            r"\bsk-[a-zA-Z0-9]{20,}\b",
            0.95,
        ),
        Pattern(
            "stripe_key",
            r"\b[ps]k_(live|test)_[a-zA-Z0-9]{20,}\b",
            0.95,
        ),
        Pattern(
            "aws_access_key",
            r"\bAKIA[A-Z0-9]{16}\b",
            0.95,
        ),
        Pattern(
            "generic_api_key",
            r"\b[a-zA-Z0-9_-]{32,64}\b",
            0.5,  # Lower confidence for generic patterns
        ),
    ]
    
    CONTEXT: ClassVar[list[str]] = ["api", "key", "secret", "token", "credential", "auth"]
    
    def __init__(
        self,
        patterns: list[Pattern] | None = None,
        context: list[str] | None = None,
        supported_language: str = "en",
        supported_entity: str = "API_KEY",
    ):
        patterns = patterns or self.PATTERNS
        context = context or self.CONTEXT
        super().__init__(
            supported_entity=supported_entity,
            patterns=patterns,
            context=context,
            supported_language=supported_language,
        )


def get_custom_recognizers() -> list[PatternRecognizer]:
    """
    Return a list of all custom recognizers.
    
    To add a new recognizer:
    1. Create a class that extends PatternRecognizer
    2. Define PATTERNS with regex patterns and confidence scores
    3. Add to this list
    
    Example usage with Presidio:
    ```python
    from presidio_analyzer import AnalyzerEngine
    from custom_recognizers import get_custom_recognizers
    
    analyzer = AnalyzerEngine()
    for recognizer in get_custom_recognizers():
        analyzer.registry.add_recognizer(recognizer)
    ```
    """
    return [
        EmployeeIDRecognizer(),
        ProjectCodeRecognizer(),
        InternalIPRecognizer(),
        APIKeyRecognizer(),
    ]


# Entity type to human-readable name mapping
CUSTOM_ENTITY_DESCRIPTIONS = {
    "EMPLOYEE_ID": "Employee Identifier",
    "PROJECT_CODE": "Internal Project Code",
    "INTERNAL_IP": "Private IP Address",
    "API_KEY": "API Key or Secret",
}
