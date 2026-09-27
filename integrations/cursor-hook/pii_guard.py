#!/usr/bin/env python3
"""
LLM Steward - Cursor PII Guard Hook
========================================
A Cursor hook that checks prompts for PII before they're sent to the model.
Uses the same Presidio analyzer as the gateway for consistent policy.

Usage:
    Place in your hooks.json:
    {
      "version": 1,
      "hooks": {
        "beforeSubmitPrompt": [
          { "command": "python3 /path/to/pii_guard.py" }
        ]
      }
    }

Configuration (environment variables):
    GATEWAY_URL          - Gateway URL (default: http://localhost:4000)
    PRESIDIO_URL         - Presidio analyzer URL (default: http://localhost:5001)
    PII_GUARD_FAIL_OPEN  - "true" to allow on errors (default), "false" to block
    PII_GUARD_TEAM       - Team name for observability logging
    PII_GUARD_USER       - User ID for observability logging (overrides CURSOR_USER_EMAIL)

Exit codes:
    0 - Success (prompt allowed or PII found with user_message)
    2 - Block the action (used when continue: false and JSON fails to write)
"""

import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional
import urllib.request
import urllib.error

# Configuration
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:4000")
PRESIDIO_URL = os.environ.get("PRESIDIO_URL", "http://localhost:5001")
FAIL_OPEN = os.environ.get("PII_GUARD_FAIL_OPEN", "true").lower() == "true"
TEAM_NAME = os.environ.get("PII_GUARD_TEAM", "cursor-users")
USER_ID = os.environ.get("PII_GUARD_USER") or os.environ.get("CURSOR_USER_EMAIL")

# PII entity types to check for (same as gateway config)
PII_ENTITIES = [
    "PERSON",
    "EMAIL_ADDRESS", 
    "PHONE_NUMBER",
    "CREDIT_CARD",
    "US_SSN",
    "US_BANK_NUMBER",
    "IP_ADDRESS",
    "LOCATION",
]

# Human-readable entity names
ENTITY_LABELS = {
    "PERSON": "person name",
    "EMAIL_ADDRESS": "email address",
    "PHONE_NUMBER": "phone number",
    "CREDIT_CARD": "credit card number",
    "US_SSN": "social security number",
    "US_BANK_NUMBER": "bank account number",
    "IP_ADDRESS": "IP address",
    "LOCATION": "location/address",
}


def log(message: str):
    """Log to stderr (visible in Cursor's Hooks output channel)."""
    print(f"[pii_guard] {message}", file=sys.stderr)


def read_input() -> Dict[str, Any]:
    """Read JSON input from stdin."""
    return json.load(sys.stdin)


def write_output(output: Dict[str, Any]):
    """Write JSON output to stdout."""
    print(json.dumps(output))


def analyze_pii(text: str) -> List[Dict[str, Any]]:
    """
    Send text to Presidio analyzer and return detected entities.
    
    Returns a list of detected entities with their types.
    Never returns the actual PII values.
    """
    try:
        request_data = json.dumps({
            "text": text,
            "language": "en",
            "entities": PII_ENTITIES,
            "score_threshold": 0.7,
        }).encode("utf-8")
        
        req = urllib.request.Request(
            f"{PRESIDIO_URL}/analyze",
            data=request_data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        
        with urllib.request.urlopen(req, timeout=5) as response:
            results = json.loads(response.read().decode("utf-8"))
            return results
            
    except urllib.error.URLError as e:
        log(f"Failed to connect to Presidio at {PRESIDIO_URL}: {e}")
        raise
    except Exception as e:
        log(f"Presidio analysis error: {e}")
        raise


def record_block_event(
    entity_types: List[str],
    team: str,
    user: Optional[str],
    conversation_id: Optional[str],
):
    """
    Record a block event in the gateway's observability layer.
    
    Only records metadata - never stores the actual prompt.
    """
    try:
        # Use the gateway's dashboard API to record the event
        # This goes into gateway_guardrail_events table
        request_data = json.dumps({
            "source": "cursor_hook",
            "team_name": team,
            "user_id": user,
            "conversation_id": conversation_id,
            "guardrail_name": "pii-guard-cursor",
            "guardrail_type": "pii",
            "action_taken": "blocked",
            "pii_types_detected": entity_types,
            "timestamp": datetime.utcnow().isoformat(),
        }).encode("utf-8")
        
        # Try the dashboard's logging endpoint
        dashboard_url = os.environ.get("DASHBOARD_URL", "http://localhost:8080")
        req = urllib.request.Request(
            f"{dashboard_url}/api/hook-events",
            data=request_data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        
        with urllib.request.urlopen(req, timeout=3) as response:
            log(f"Block event recorded for team={team}, user={user}")
            
    except Exception as e:
        # Don't fail the hook if logging fails
        log(f"Failed to record block event (non-fatal): {e}")


def format_block_message(entity_types: List[str]) -> str:
    """
    Format a user-friendly message about detected PII types.
    
    Never includes the actual PII values - only the types.
    """
    unique_types = sorted(set(entity_types))
    labels = [ENTITY_LABELS.get(t, t.lower().replace("_", " ")) for t in unique_types]
    
    if len(labels) == 1:
        types_str = labels[0]
    elif len(labels) == 2:
        types_str = f"{labels[0]} and {labels[1]}"
    else:
        types_str = ", ".join(labels[:-1]) + f", and {labels[-1]}"
    
    return (
        f"⚠️ PII detected in prompt: {types_str}.\n\n"
        f"Your prompt contains potentially sensitive information. "
        f"Please remove or redact the {types_str} before sending.\n\n"
        f"This check uses the same Presidio rules as your LLM gateway."
    )


def main():
    """Main hook entry point."""
    try:
        # Read input from Cursor
        input_data = read_input()
        prompt = input_data.get("prompt", "")
        conversation_id = input_data.get("conversation_id")
        
        if not prompt:
            # Empty prompt, allow it
            write_output({"continue": True})
            return
        
        log(f"Analyzing prompt ({len(prompt)} chars) for PII...")
        
        try:
            # Analyze for PII
            results = analyze_pii(prompt)
            
            if results:
                # PII detected - block the prompt
                entity_types = [r.get("entity_type") for r in results if r.get("entity_type")]
                
                log(f"PII detected: {entity_types}")
                
                # Record the block event (metadata only)
                record_block_event(
                    entity_types=entity_types,
                    team=TEAM_NAME,
                    user=USER_ID,
                    conversation_id=conversation_id,
                )
                
                # Return block response
                write_output({
                    "continue": False,
                    "user_message": format_block_message(entity_types),
                })
            else:
                # No PII found - allow
                log("No PII detected, allowing prompt")
                write_output({"continue": True})
                
        except Exception as e:
            # Error contacting Presidio
            if FAIL_OPEN:
                log(f"Error analyzing PII, failing open: {e}")
                write_output({
                    "continue": True,
                    "user_message": (
                        "⚠️ PII check unavailable (gateway unreachable). "
                        "Proceeding without PII validation."
                    ),
                })
            else:
                log(f"Error analyzing PII, failing closed: {e}")
                write_output({
                    "continue": False,
                    "user_message": (
                        "❌ PII check failed (gateway unreachable). "
                        "Prompt blocked for safety. Please try again later or "
                        "contact your administrator."
                    ),
                })
                
    except json.JSONDecodeError as e:
        log(f"Failed to parse input JSON: {e}")
        if FAIL_OPEN:
            write_output({"continue": True})
        else:
            sys.exit(2)  # Block with exit code
            
    except Exception as e:
        log(f"Unexpected error: {e}")
        if FAIL_OPEN:
            write_output({"continue": True})
        else:
            sys.exit(2)


if __name__ == "__main__":
    main()
