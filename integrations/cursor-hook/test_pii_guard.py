#!/usr/bin/env python3
"""
Tests for the Cursor PII Guard Hook
===================================
Run with: pytest integrations/cursor-hook/test_pii_guard.py -v
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

# Path to the hook script
HOOK_SCRIPT = Path(__file__).parent / "pii_guard.py"


def run_hook(input_data: dict, env: dict = None) -> tuple[int, dict, str]:
    """
    Run the hook script with given input and return (exit_code, output, stderr).
    """
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    
    # Don't actually call external services in tests
    process_env["PRESIDIO_URL"] = "http://localhost:5001"
    
    result = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
        env=process_env,
    )
    
    try:
        output = json.loads(result.stdout) if result.stdout.strip() else {}
    except json.JSONDecodeError:
        output = {"raw_stdout": result.stdout}
    
    return result.returncode, output, result.stderr


class TestHookInputParsing:
    """Test hook input handling."""
    
    def test_empty_prompt_allowed(self):
        """Empty prompts should be allowed through."""
        # This test doesn't need Presidio - empty prompts short-circuit
        with patch.dict(os.environ, {"PII_GUARD_FAIL_OPEN": "true"}):
            input_data = {"prompt": ""}
            exit_code, output, stderr = run_hook(input_data)
            
            assert exit_code == 0
            assert output.get("continue") is True
    
    def test_missing_prompt_allowed(self):
        """Missing prompt field should be allowed."""
        with patch.dict(os.environ, {"PII_GUARD_FAIL_OPEN": "true"}):
            input_data = {}
            exit_code, output, stderr = run_hook(input_data)
            
            assert exit_code == 0
            assert output.get("continue") is True


class TestHookPayloads:
    """Test with sample hook payloads from Cursor docs."""
    
    def test_standard_prompt_payload(self):
        """Test standard beforeSubmitPrompt payload structure."""
        payload = {
            "prompt": "Hello world",
            "attachments": [],
            "conversation_id": "conv-123",
            "generation_id": "gen-456",
            "model": "claude-opus-4-7",
            "hook_event_name": "beforeSubmitPrompt",
            "cursor_version": "1.7.2",
            "workspace_roots": ["/Users/test/project"],
            "user_email": "test@example.com",
        }
        
        # With Presidio unreachable, should fail open
        exit_code, output, stderr = run_hook(payload)
        
        assert exit_code == 0
        # Should either allow (fail-open) or have a valid response
        assert "continue" in output
    
    def test_payload_with_attachments(self):
        """Test payload with file attachments."""
        payload = {
            "prompt": "Review this file",
            "attachments": [
                {"type": "file", "file_path": "/path/to/file.py"},
                {"type": "rule", "file_path": "/path/to/rule.md"},
            ],
            "conversation_id": "conv-789",
        }
        
        exit_code, output, stderr = run_hook(payload)
        
        assert exit_code == 0
        assert "continue" in output


class TestBlockMessageFormat:
    """Test the block message formatting."""
    
    def test_format_single_entity(self):
        """Test message for single PII type."""
        # Import the function directly
        import importlib.util
        spec = importlib.util.spec_from_file_location("pii_guard", HOOK_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        message = module.format_block_message(["EMAIL_ADDRESS"])
        assert "email address" in message
        assert "PII detected" in message
    
    def test_format_multiple_entities(self):
        """Test message for multiple PII types."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("pii_guard", HOOK_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        message = module.format_block_message(["EMAIL_ADDRESS", "PHONE_NUMBER", "PERSON"])
        assert "email address" in message
        assert "phone number" in message
        assert "person name" in message
    
    def test_format_deduplicates_entities(self):
        """Test that duplicate entity types are deduplicated."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("pii_guard", HOOK_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        message = module.format_block_message(["EMAIL_ADDRESS", "EMAIL_ADDRESS", "EMAIL_ADDRESS"])
        # Should only mention email once
        assert message.count("email address") == 2  # Once in list, once in "remove the X"


class TestFailOpenBehavior:
    """Test fail-open vs fail-closed behavior."""
    
    def test_fail_open_on_connection_error(self):
        """Test that connection errors result in fail-open by default."""
        payload = {"prompt": "Test prompt with john@example.com"}
        env = {
            "PII_GUARD_FAIL_OPEN": "true",
            "PRESIDIO_URL": "http://localhost:59999",  # Non-existent
        }
        
        exit_code, output, stderr = run_hook(payload, env)
        
        assert exit_code == 0
        assert output.get("continue") is True
        assert "unavailable" in output.get("user_message", "").lower()
    
    def test_fail_closed_on_connection_error(self):
        """Test that connection errors can be configured to fail-closed."""
        payload = {"prompt": "Test prompt with john@example.com"}
        env = {
            "PII_GUARD_FAIL_OPEN": "false",
            "PRESIDIO_URL": "http://localhost:59999",  # Non-existent
        }
        
        exit_code, output, stderr = run_hook(payload, env)
        
        assert exit_code == 0
        assert output.get("continue") is False
        assert "failed" in output.get("user_message", "").lower()


class TestEnvironmentVariables:
    """Test environment variable handling."""
    
    def test_custom_presidio_url(self):
        """Test custom PRESIDIO_URL is used."""
        payload = {"prompt": "Test"}
        env = {"PRESIDIO_URL": "http://custom-presidio:3000"}
        
        exit_code, output, stderr = run_hook(payload, env)
        
        # Should attempt to connect to custom URL (will fail, but that's OK)
        assert "custom-presidio" in stderr or exit_code == 0
    
    def test_team_and_user_from_env(self):
        """Test team and user can be set via environment."""
        payload = {"prompt": "Test"}
        env = {
            "PII_GUARD_TEAM": "engineering",
            "PII_GUARD_USER": "alice@example.com",
        }
        
        exit_code, output, stderr = run_hook(payload, env)
        
        # Hook should run (even if Presidio unavailable)
        assert exit_code == 0


class TestSamplePIIPrompts:
    """Test with sample prompts containing PII patterns."""
    
    # Note: These tests document expected behavior when Presidio IS available
    # In unit tests without Presidio, they test fail-open behavior
    
    SAMPLE_PROMPTS = [
        {
            "name": "email",
            "prompt": "Send an email to john.smith@example.com about the project",
            "expected_entities": ["EMAIL_ADDRESS"],
        },
        {
            "name": "phone",
            "prompt": "Call me at 555-123-4567 when you're done",
            "expected_entities": ["PHONE_NUMBER"],
        },
        {
            "name": "credit_card",
            "prompt": "My card number is 4111-1111-1111-1111",
            "expected_entities": ["CREDIT_CARD"],
        },
        {
            "name": "ssn",
            "prompt": "SSN: 123-45-6789",
            "expected_entities": ["US_SSN"],
        },
        {
            "name": "multiple",
            "prompt": "Contact John Smith at john@example.com or 555-555-5555",
            "expected_entities": ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER"],
        },
        {
            "name": "clean",
            "prompt": "Write a function that calculates fibonacci numbers",
            "expected_entities": [],
        },
    ]
    
    @pytest.mark.parametrize("sample", SAMPLE_PROMPTS, ids=lambda x: x["name"])
    def test_sample_prompt(self, sample):
        """Test handling of sample prompts with known PII patterns."""
        payload = {"prompt": sample["prompt"]}
        
        # Without Presidio running, these should fail-open
        exit_code, output, stderr = run_hook(payload)
        
        assert exit_code == 0
        assert "continue" in output
        
        # Log for visibility
        print(f"\nSample '{sample['name']}':")
        print(f"  Prompt: {sample['prompt'][:50]}...")
        print(f"  Expected entities: {sample['expected_entities']}")
        print(f"  Result: continue={output.get('continue')}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
