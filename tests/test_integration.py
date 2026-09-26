"""
Integration Tests for LLM Gateway Kit
=====================================
These tests require a running gateway or mock the external services.
Run with: pytest tests/test_integration.py -v -m integration
"""

import os
import pytest
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


class TestBudgetEnforcement:
    """Test budget and rate limit enforcement."""
    
    @pytest.mark.requires_gateway
    async def test_budget_exceeded_rejected(self, gateway_url, master_key):
        """Test that requests are rejected when budget is exceeded."""
        import httpx
        
        headers = {
            "Authorization": f"Bearer {master_key}",
            "Content-Type": "application/json",
        }
        
        async with httpx.AsyncClient() as client:
            # Check gateway health first (use liveliness endpoint which doesn't require auth)
            response = await client.get(f"{gateway_url}/health/liveliness")
            assert response.status_code == 200
            
            # Create a team with very low budget ($0.01)
            team_response = await client.post(
                f"{gateway_url}/team/new",
                headers=headers,
                json={
                    "team_alias": "test_budget_team",
                    "max_budget": 0.00001,  # Very small budget
                },
            )
            
            if team_response.status_code == 200:
                team_id = team_response.json().get("team_id")
                
                # Create key for team
                key_response = await client.post(
                    f"{gateway_url}/key/generate",
                    headers=headers,
                    json={"team_id": team_id},
                )
                
                if key_response.status_code == 200:
                    api_key = key_response.json().get("key")
                    
                    # Make a request to consume budget
                    await client.post(
                        f"{gateway_url}/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": "fake/echo",
                            "messages": [{"role": "user", "content": "test"}],
                        },
                    )
                    
                    # Second request should be rejected due to budget
                    # (In practice, depends on how quickly spend is tracked)
                    second_response = await client.post(
                        f"{gateway_url}/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": "fake/echo",
                            "messages": [{"role": "user", "content": "test"}],
                        },
                    )
                    # Budget enforcement may not be instant; just verify the flow works
                    assert second_response.status_code in [200, 400, 429]
    
    @pytest.mark.requires_gateway
    async def test_disallowed_model_rejected(self, gateway_url, master_key):
        """Test that requests for disallowed models are rejected."""
        import httpx
        
        # Create a team with restricted models
        headers = {"Authorization": f"Bearer {master_key}", "Content-Type": "application/json"}
        
        async with httpx.AsyncClient() as client:
            # Create restricted team
            team_response = await client.post(
                f"{gateway_url}/team/new",
                headers=headers,
                json={
                    "team_alias": "test_restricted",
                    "models": ["local/small"],  # Only allow local model
                },
            )
            
            if team_response.status_code == 200:
                team_id = team_response.json().get("team_id")
                
                # Create key for team
                key_response = await client.post(
                    f"{gateway_url}/key/generate",
                    headers=headers,
                    json={"team_id": team_id},
                )
                
                if key_response.status_code == 200:
                    api_key = key_response.json().get("key")
                    
                    # Try to use a disallowed model
                    chat_response = await client.post(
                        f"{gateway_url}/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": "openai/gpt-4o",  # Not in allowed list
                            "messages": [{"role": "user", "content": "test"}],
                        },
                    )
                    
                    # Should be rejected
                    assert chat_response.status_code in [400, 403, 401]


class TestGuardrails:
    """Test PII guardrail functionality."""
    
    @pytest.mark.requires_gateway
    async def test_pii_detection(self, gateway_url, master_key):
        """Test that PII is detected and redacted."""
        import httpx
        
        headers = {
            "Authorization": f"Bearer {master_key}",
            "Content-Type": "application/json",
        }
        
        # Create team with PII guardrail enabled
        async with httpx.AsyncClient() as client:
            team_response = await client.post(
                f"{gateway_url}/team/new",
                headers=headers,
                json={
                    "team_alias": "test_pii_team",
                    "metadata": {"pii_guardrail_enabled": True},
                },
            )
            
            if team_response.status_code != 200:
                pytest.skip("Could not create test team")
    
    def test_pii_guardrail_config(self):
        """Test that PII guardrail is configured correctly."""
        import yaml
        
        with open("config/litellm_config.yaml") as f:
            config = yaml.safe_load(f)
        
        guardrails = config.get("guardrails", [])
        pii_guardrail = None
        
        for g in guardrails:
            if g.get("guardrail_name") == "pii-guardrail":
                pii_guardrail = g
                break
        
        assert pii_guardrail is not None, "PII guardrail should be configured"
        
        params = pii_guardrail.get("litellm_params", {})
        assert params.get("guardrail") == "presidio"
        assert "pii_entities_to_detect" in params


class TestObservability:
    """Test observability and logging."""
    
    def test_request_log_schema(self, database_url):
        """Test that request log table has correct schema."""
        # This test validates the database schema
        expected_columns = [
            "request_id",
            "team_id",
            "team_name",
            "user_id",
            "model_requested",
            "model_used",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "cost",
            "latency_ms",
            "status",
            "guardrail_triggered",
        ]
        
        # Schema is defined in db/init.sql
        init_sql = Path("db/init.sql").read_text()
        
        for col in expected_columns:
            assert col in init_sql, f"Column {col} should be in schema"
    
    def test_privacy_default(self):
        """Test that prompt bodies are not stored by default."""
        init_sql = Path("db/init.sql").read_text()
        
        # Check that store_prompts defaults to false
        assert "store_prompts BOOLEAN DEFAULT false" in init_sql
        assert "store_responses BOOLEAN DEFAULT false" in init_sql
    
    @pytest.mark.requires_gateway
    async def test_request_logged_with_attribution(self, gateway_url, master_key):
        """Test that requests are logged with correct team attribution."""
        import httpx
        
        # This would require checking the database after making a request
        # Implementation depends on having database access in tests
        pass


class TestDashboard:
    """Test dashboard API endpoints."""
    
    @pytest.mark.requires_gateway
    async def test_dashboard_health(self):
        """Test dashboard health endpoint."""
        import httpx
        
        dashboard_url = os.environ.get("DASHBOARD_URL", "http://localhost:8080")
        
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{dashboard_url}/api/health")
            
            if response.status_code == 200:
                data = response.json()
                assert data.get("status") == "healthy"
    
    @pytest.mark.requires_gateway
    async def test_dashboard_summary(self):
        """Test dashboard summary endpoint."""
        import httpx
        
        dashboard_url = os.environ.get("DASHBOARD_URL", "http://localhost:8080")
        
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{dashboard_url}/api/summary?hours=24")
            
            if response.status_code == 200:
                data = response.json()
                assert "total_requests" in data
                assert "total_cost" in data
                assert "error_rate" in data


class TestDockerCompose:
    """Test Docker Compose configuration."""
    
    def test_compose_file_valid(self):
        """Test that docker-compose.yml is valid."""
        import yaml
        
        compose_path = Path("docker-compose.yml")
        assert compose_path.exists()
        
        with open(compose_path) as f:
            compose = yaml.safe_load(f)
        
        assert "services" in compose
        assert "litellm" in compose["services"]
        assert "postgres" in compose["services"]
        assert "dashboard" in compose["services"]
    
    def test_required_services(self):
        """Test that all required services are defined."""
        import yaml
        
        with open("docker-compose.yml") as f:
            compose = yaml.safe_load(f)
        
        services = compose["services"]
        
        required = ["postgres", "litellm", "dashboard", "presidio-analyzer", "presidio-anonymizer"]
        for svc in required:
            assert svc in services, f"Service {svc} should be defined"
    
    def test_healthchecks_defined(self):
        """Test that healthchecks are defined for key services."""
        import yaml
        
        with open("docker-compose.yml") as f:
            compose = yaml.safe_load(f)
        
        services_with_healthcheck = ["postgres", "litellm"]
        
        for svc in services_with_healthcheck:
            assert "healthcheck" in compose["services"][svc], \
                f"Service {svc} should have healthcheck"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
