#!/usr/bin/env python3
"""
Seed Traffic Generator
======================
Generates realistic demo traffic from multiple fake teams to populate the dashboard.
Run with: python scripts/seed_traffic.py
"""

import os
import sys
import time
import random
import asyncio
from datetime import datetime
from typing import List, Dict, Any
import httpx

# Configuration
GATEWAY_URL = os.environ.get("LITELLM_URL", "http://localhost:4000")
MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY", "sk-master-key-change-me")

# Demo teams configuration
DEMO_TEAMS = [
    {
        "name": "engineering",
        "description": "Engineering team - full access to all models",
        "budget": 500.0,
        "pii_guardrail": False,
        "models": None,  # All models
        "prompts": [
            "Explain how to implement a binary search tree in Python",
            "Write a function to validate email addresses using regex",
            "What's the difference between async and threading in Python?",
            "How do I optimize a slow database query?",
            "Explain the CAP theorem in distributed systems",
            "Write a REST API endpoint for user authentication",
            "How do I set up CI/CD with GitHub Actions?",
            "Explain microservices vs monolithic architecture",
        ],
        "users": ["alice@example.com", "bob@example.com", "charlie@example.com"],
        "request_count": 30,
    },
    {
        "name": "support",
        "description": "Customer support - budget limited with PII protection",
        "budget": 100.0,
        "pii_guardrail": True,
        "models": ["openai/gpt-4o-mini", "local/small", "fake/echo"],
        "prompts": [
            "Draft a response to a customer asking about refund policy",
            "Help me write an apology email for a delayed shipment",
            "Summarize this customer complaint: The product arrived broken",
            "Write a FAQ answer about password reset",
            "How should I respond to an angry customer?",
            "Draft a follow-up email for an open support ticket",
        ],
        "pii_prompts": [
            "The customer John Smith at john.smith@email.com needs help",
            "Customer called from 555-123-4567 about their order",
            "Credit card ending in 4242 was declined, customer email: jane@test.com",
            "User at 192.168.1.100 is having login issues",
            "Sarah Johnson (SSN: 123-45-6789) needs account verification",
        ],
        "users": ["support1@example.com", "support2@example.com"],
        "request_count": 25,
    },
    {
        "name": "analytics",
        "description": "Data analytics team - smart model access",
        "budget": 200.0,
        "pii_guardrail": True,
        "models": ["smart", "openai/gpt-4o", "local/medium", "fake/echo"],
        "prompts": [
            "Analyze this sales data trend and suggest improvements",
            "Write a SQL query to find top customers by revenue",
            "Explain the difference between correlation and causation",
            "How do I create a cohort analysis in Python?",
            "Summarize the key metrics from this quarterly report",
            "What statistical tests should I use for A/B testing?",
            "Help me interpret this regression analysis output",
        ],
        "users": ["analyst1@example.com", "analyst2@example.com"],
        "request_count": 20,
    },
]


def get_headers(api_key: str = None):
    """Get headers for API requests."""
    return {
        "Authorization": f"Bearer {api_key or MASTER_KEY}",
        "Content-Type": "application/json",
    }


async def create_team(client: httpx.AsyncClient, team: Dict[str, Any]) -> str:
    """Create a team and return its ID."""
    data = {
        "team_alias": team["name"],
        "max_budget": team["budget"],
        "budget_duration": "monthly",
        "metadata": {
            "description": team["description"],
            "pii_guardrail_enabled": team["pii_guardrail"],
        },
    }
    
    if team["models"]:
        data["models"] = team["models"]
    
    try:
        response = await client.post(
            f"{GATEWAY_URL}/team/new",
            headers=get_headers(),
            json=data,
        )
        response.raise_for_status()
        result = response.json()
        print(f"  ✓ Created team: {team['name']}")
        return result.get("team_id")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400 and "already exists" in e.response.text.lower():
            # Team exists, get its ID
            list_response = await client.get(
                f"{GATEWAY_URL}/team/list",
                headers=get_headers(),
            )
            teams = list_response.json()
            for t in teams if isinstance(teams, list) else teams.get("teams", []):
                if t.get("team_alias") == team["name"]:
                    print(f"  → Team exists: {team['name']}")
                    return t.get("team_id")
        raise


async def create_key(client: httpx.AsyncClient, team_id: str, user: str) -> str:
    """Create an API key for a user."""
    data = {
        "team_id": team_id,
        "user_id": user,
        "key_alias": f"key-{user.split('@')[0]}",
        "duration": "30d",
    }
    
    response = await client.post(
        f"{GATEWAY_URL}/key/generate",
        headers=get_headers(),
        json=data,
    )
    response.raise_for_status()
    result = response.json()
    return result.get("key", result.get("token"))


async def send_chat_request(
    client: httpx.AsyncClient,
    api_key: str,
    prompt: str,
    model: str = "fake/echo",
    user: str = None,
) -> Dict[str, Any]:
    """Send a chat completion request."""
    data = {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 150,
    }
    
    if user:
        data["user"] = user
    
    try:
        response = await client.post(
            f"{GATEWAY_URL}/v1/chat/completions",
            headers=get_headers(api_key),
            json=data,
            timeout=30.0,
        )
        response.raise_for_status()
        return {"success": True, "response": response.json()}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def generate_team_traffic(
    client: httpx.AsyncClient,
    team: Dict[str, Any],
    team_id: str,
):
    """Generate traffic for a single team."""
    print(f"\n  Generating traffic for {team['name']}...")
    
    # Create keys for users
    user_keys = {}
    for user in team["users"]:
        try:
            key = await create_key(client, team_id, user)
            user_keys[user] = key
            print(f"    ✓ Created key for {user}")
        except Exception as e:
            print(f"    ✗ Failed to create key for {user}: {e}")
    
    if not user_keys:
        print(f"    ✗ No keys created, skipping traffic generation")
        return
    
    # Generate requests
    models = team.get("models") or ["fake/echo", "local/small"]
    prompts = team["prompts"].copy()
    
    # Add PII prompts if team has PII guardrail
    if team.get("pii_guardrail") and team.get("pii_prompts"):
        prompts.extend(team["pii_prompts"])
    
    success_count = 0
    error_count = 0
    
    for i in range(team["request_count"]):
        user = random.choice(list(user_keys.keys()))
        api_key = user_keys[user]
        prompt = random.choice(prompts)
        model = random.choice(models)
        
        result = await send_chat_request(client, api_key, prompt, model, user)
        
        if result["success"]:
            success_count += 1
        else:
            error_count += 1
        
        # Add some randomness to timing
        await asyncio.sleep(random.uniform(0.1, 0.5))
        
        # Progress indicator
        if (i + 1) % 10 == 0:
            print(f"    Progress: {i + 1}/{team['request_count']}")
    
    print(f"    ✓ Completed: {success_count} success, {error_count} errors")


async def main():
    """Main function to seed demo traffic."""
    print("=" * 60)
    print("LLM Steward - Demo Traffic Generator")
    print("=" * 60)
    print(f"\nGateway URL: {GATEWAY_URL}")
    
    # Check gateway health
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{GATEWAY_URL}/health/liveliness")
            response.raise_for_status()
            print("✓ Gateway is healthy\n")
        except Exception as e:
            print(f"✗ Gateway health check failed: {e}")
            print("\nMake sure the gateway is running: make up")
            sys.exit(1)
        
        print("Creating teams...")
        team_ids = {}
        
        for team in DEMO_TEAMS:
            try:
                team_id = await create_team(client, team)
                team_ids[team["name"]] = team_id
            except Exception as e:
                print(f"  ✗ Failed to create team {team['name']}: {e}")
        
        print("\nGenerating traffic...")
        
        for team in DEMO_TEAMS:
            if team["name"] in team_ids:
                await generate_team_traffic(client, team, team_ids[team["name"]])
    
    print("\n" + "=" * 60)
    print("✓ Demo traffic generation complete!")
    print("=" * 60)
    print("\nView the results at: http://localhost:8080")
    print("\nGenerated traffic includes:")
    print("  - Multiple teams with different budgets")
    print("  - Per-user attribution")
    print("  - PII guardrail triggers (support and analytics teams)")
    print("  - Various model usage patterns")


if __name__ == "__main__":
    asyncio.run(main())
