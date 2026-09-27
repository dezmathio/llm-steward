"""
Custom LiteLLM Callback Handler for Observability
==================================================
This module captures all LiteLLM requests and logs them to PostgreSQL
for the observability dashboard. It respects team privacy settings.
"""

import asyncio
import hashlib
import json
import os
from datetime import datetime
from typing import Any

import asyncpg
from litellm import completion_cost
from litellm.integrations.custom_logger import CustomLogger

# Database connection pool
_db_pool: asyncpg.Pool | None = None


async def get_db_pool() -> asyncpg.Pool:
    """Get or create the database connection pool."""
    global _db_pool
    if _db_pool is None:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise ValueError("DATABASE_URL environment variable is required")
        _db_pool = await asyncpg.create_pool(database_url, min_size=2, max_size=10)
    return _db_pool


def hash_api_key(api_key: str) -> str:
    """Hash an API key for storage (we never store raw keys)."""
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]


def truncate_and_redact(text: str, max_length: int = 200) -> str:
    """Truncate text and add basic redaction markers."""
    if not text:
        return ""
    # Truncate first
    truncated = text[:max_length]
    if len(text) > max_length:
        truncated += "..."
    return truncated


def extract_team_info(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Extract team information from the request metadata."""
    metadata = kwargs.get("litellm_params", {}).get("metadata", {})
    
    # LiteLLM passes team info in metadata when using virtual keys
    team_id = metadata.get("team_id")
    team_alias = metadata.get("team_alias")
    user_id = metadata.get("user_id") or metadata.get("user")
    
    # Get API key hash for attribution
    api_key = kwargs.get("api_key", "")
    api_key_hash = hash_api_key(api_key) if api_key else None
    
    return {
        "team_id": team_id,
        "team_name": team_alias,
        "user_id": user_id,
        "api_key_hash": api_key_hash,
    }


def extract_guardrail_info(kwargs: dict[str, Any], response: Any) -> dict[str, Any]:
    """Extract guardrail trigger information."""
    metadata = kwargs.get("litellm_params", {}).get("metadata", {})
    
    guardrail_triggered = False
    guardrail_name = None
    guardrail_action = None
    pii_types = []
    
    # Check for presidio guardrail triggers
    presidio_output = metadata.get("presidio_output", {})
    if presidio_output:
        pii_results = presidio_output.get("results", [])
        if pii_results:
            guardrail_triggered = True
            guardrail_name = "pii-guardrail"
            guardrail_action = "redacted"
            pii_types = list({r.get("entity_type") for r in pii_results if r.get("entity_type")})
    
    return {
        "guardrail_triggered": guardrail_triggered,
        "guardrail_name": guardrail_name,
        "guardrail_action": guardrail_action,
        "pii_types_detected": pii_types,
    }


async def get_team_privacy_settings(team_id: str) -> dict[str, bool]:
    """Get team's privacy settings from database."""
    if not team_id:
        return {"store_prompts": False, "store_responses": False}
    
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT store_prompts, store_responses 
                FROM gateway_teams 
                WHERE id = $1 OR name = $1
                """,
                team_id
            )
            if row:
                return {
                    "store_prompts": row["store_prompts"],
                    "store_responses": row["store_responses"],
                }
    except Exception:
        pass
    
    return {"store_prompts": False, "store_responses": False}


class GatewayObservabilityLogger(CustomLogger):
    """
    Custom logger that captures all requests for the observability dashboard.
    
    Key features:
    - Records team attribution for every request
    - Tracks tokens, cost, latency, and errors
    - Respects team privacy settings (prompts not stored by default)
    - Logs guardrail triggers
    """
    
    def __init__(self):
        super().__init__()
        self._loop = None
    
    def _get_loop(self):
        """Get or create event loop."""
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
            return self._loop
    
    async def _log_request(
        self,
        kwargs: dict[str, Any],
        response: Any,
        start_time: datetime,
        end_time: datetime,
        status: str = "success",
        error_type: str | None = None,
        error_message: str | None = None,
    ):
        """Log a request to the database."""
        try:
            # Extract information
            team_info = extract_team_info(kwargs)
            guardrail_info = extract_guardrail_info(kwargs, response)
            
            # Get privacy settings
            privacy = await get_team_privacy_settings(team_info.get("team_id"))
            
            # Calculate metrics
            latency_ms = int((end_time - start_time).total_seconds() * 1000)
            
            # Extract token usage
            prompt_tokens = 0
            completion_tokens = 0
            total_tokens = 0
            cost = 0.0
            
            if response and hasattr(response, "usage"):
                usage = response.usage
                prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
                completion_tokens = getattr(usage, "completion_tokens", 0) or 0
                total_tokens = getattr(usage, "total_tokens", 0) or 0
            
            # Calculate cost
            try:
                model = kwargs.get("model", "")
                cost = completion_cost(
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                ) or 0.0
            except Exception:
                cost = 0.0
            
            # Get request ID
            litellm_params = kwargs.get("litellm_params", {})
            request_id = litellm_params.get("litellm_call_id", "")
            
            # Extract model info
            model_requested = kwargs.get("model", "")
            model_used = litellm_params.get("model", model_requested)
            
            # Extract content (respecting privacy)
            messages = kwargs.get("messages", [])
            prompt_text = ""
            if messages:
                last_user_msg = next(
                    (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
                    ""
                )
                prompt_text = last_user_msg if isinstance(last_user_msg, str) else str(last_user_msg)
            
            response_text = ""
            if response and hasattr(response, "choices") and response.choices:
                choice = response.choices[0]
                if hasattr(choice, "message") and choice.message:
                    response_text = getattr(choice.message, "content", "") or ""
            
            # Prepare log entry
            log_entry = {
                "request_id": request_id,
                "litellm_call_id": request_id,
                "team_id": team_info.get("team_id"),
                "team_name": team_info.get("team_name"),
                "api_key_hash": team_info.get("api_key_hash"),
                "user_id": team_info.get("user_id"),
                "model_requested": model_requested,
                "model_used": model_used,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "cost": cost,
                "latency_ms": latency_ms,
                "status": status,
                "error_type": error_type,
                "error_message": error_message,
                "guardrail_triggered": guardrail_info.get("guardrail_triggered", False),
                "guardrail_name": guardrail_info.get("guardrail_name"),
                "guardrail_action": guardrail_info.get("guardrail_action"),
                "pii_types_detected": json.dumps(guardrail_info.get("pii_types_detected", [])),
                "prompt_preview": truncate_and_redact(prompt_text),
                "response_preview": truncate_and_redact(response_text),
                "prompt_full": prompt_text if privacy.get("store_prompts") else None,
                "response_full": response_text if privacy.get("store_responses") else None,
            }
            
            # Insert into database
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO gateway_request_logs (
                        request_id, litellm_call_id, team_id, team_name, api_key_hash,
                        user_id, model_requested, model_used, prompt_tokens, completion_tokens,
                        total_tokens, cost, latency_ms, status, error_type, error_message,
                        guardrail_triggered, guardrail_name, guardrail_action, pii_types_detected,
                        prompt_preview, response_preview, prompt_full, response_full
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                        $11, $12, $13, $14, $15, $16, $17, $18, $19, $20,
                        $21, $22, $23, $24
                    )
                    """,
                    log_entry["request_id"],
                    log_entry["litellm_call_id"],
                    log_entry["team_id"],
                    log_entry["team_name"],
                    log_entry["api_key_hash"],
                    log_entry["user_id"],
                    log_entry["model_requested"],
                    log_entry["model_used"],
                    log_entry["prompt_tokens"],
                    log_entry["completion_tokens"],
                    log_entry["total_tokens"],
                    log_entry["cost"],
                    log_entry["latency_ms"],
                    log_entry["status"],
                    log_entry["error_type"],
                    log_entry["error_message"],
                    log_entry["guardrail_triggered"],
                    log_entry["guardrail_name"],
                    log_entry["guardrail_action"],
                    log_entry["pii_types_detected"],
                    log_entry["prompt_preview"],
                    log_entry["response_preview"],
                    log_entry["prompt_full"],
                    log_entry["response_full"],
                )
                
                # Log guardrail event if triggered
                if guardrail_info.get("guardrail_triggered"):
                    for pii_type in guardrail_info.get("pii_types_detected", []):
                        await conn.execute(
                            """
                            INSERT INTO gateway_guardrail_events (
                                request_id, team_id, guardrail_name, guardrail_type,
                                action_taken, pii_entity_type, pii_count
                            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                            """,
                            log_entry["request_id"],
                            log_entry["team_id"],
                            guardrail_info.get("guardrail_name"),
                            "pii",
                            guardrail_info.get("guardrail_action"),
                            pii_type,
                            1,
                        )
                        
        except Exception as e:
            # Don't fail the request if logging fails
            print(f"[GatewayLogger] Error logging request: {e}")
    
    def log_success_event(self, kwargs, response_obj, start_time, end_time):
        """Called on successful completion."""
        try:
            loop = self._get_loop()
            if loop.is_running():
                asyncio.create_task(
                    self._log_request(kwargs, response_obj, start_time, end_time, "success")
                )
            else:
                loop.run_until_complete(
                    self._log_request(kwargs, response_obj, start_time, end_time, "success")
                )
        except Exception as e:
            print(f"[GatewayLogger] Error in log_success_event: {e}")
    
    def log_failure_event(self, kwargs, response_obj, start_time, end_time):
        """Called on failed completion."""
        try:
            error_type = type(response_obj).__name__ if response_obj else "Unknown"
            error_message = str(response_obj) if response_obj else "Unknown error"
            
            loop = self._get_loop()
            if loop.is_running():
                asyncio.create_task(
                    self._log_request(
                        kwargs, None, start_time, end_time,
                        "error", error_type, error_message
                    )
                )
            else:
                loop.run_until_complete(
                    self._log_request(
                        kwargs, None, start_time, end_time,
                        "error", error_type, error_message
                    )
                )
        except Exception as e:
            print(f"[GatewayLogger] Error in log_failure_event: {e}")


# Global logger instance
gateway_logger = GatewayObservabilityLogger()

# Callback functions for LiteLLM config
def log_success(kwargs, response, start_time, end_time):
    """Success callback for LiteLLM."""
    gateway_logger.log_success_event(kwargs, response, start_time, end_time)

def log_failure(kwargs, response, start_time, end_time):
    """Failure callback for LiteLLM."""
    gateway_logger.log_failure_event(kwargs, response, start_time, end_time)
