#!/usr/bin/env python3
"""
LLM Gateway Kit - CLI Tool
==========================
Command-line interface for managing teams, keys, and budgets.

Usage:
    python cli/gateway_cli.py team create --name engineering --budget 500
    python cli/gateway_cli.py key create --team engineering --user alice
    python cli/gateway_cli.py team list
    python cli/gateway_cli.py stats --team engineering
"""

import os
import sys
import json
import argparse
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, List
import httpx

# LiteLLM API base URL
LITELLM_URL = os.environ.get("LITELLM_URL", "http://localhost:4000")
MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY", "sk-master-key-change-me")


def get_headers():
    """Get headers with master key authentication."""
    return {
        "Authorization": f"Bearer {MASTER_KEY}",
        "Content-Type": "application/json",
    }


def api_request(method: str, endpoint: str, data: dict = None) -> dict:
    """Make an API request to LiteLLM."""
    url = f"{LITELLM_URL}{endpoint}"
    try:
        with httpx.Client(timeout=30.0) as client:
            if method == "GET":
                response = client.get(url, headers=get_headers())
            elif method == "POST":
                response = client.post(url, headers=get_headers(), json=data)
            elif method == "DELETE":
                response = client.delete(url, headers=get_headers())
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        print(f"Error: HTTP {e.response.status_code}")
        try:
            print(f"Details: {e.response.json()}")
        except Exception:
            print(f"Details: {e.response.text}")
        sys.exit(1)
    except httpx.RequestError as e:
        print(f"Error: Could not connect to gateway at {LITELLM_URL}")
        print(f"Details: {e}")
        sys.exit(1)


# =============================================================================
# Team Management
# =============================================================================

def cmd_team_create(args):
    """Create a new team."""
    data = {
        "team_alias": args.name,
        "max_budget": args.budget,
        "budget_duration": args.budget_duration,
        "rpm_limit": args.rpm,
        "tpm_limit": args.tpm,
        "metadata": {
            "description": args.description or f"Team {args.name}",
            "pii_guardrail_enabled": args.pii_guardrail,
            "store_prompts": args.store_prompts,
            "store_responses": args.store_responses,
        },
    }
    
    if args.models:
        data["models"] = args.models.split(",")
    
    result = api_request("POST", "/team/new", data)
    
    print(f"\n✓ Team created successfully!")
    print(f"  Team ID: {result.get('team_id')}")
    print(f"  Name: {args.name}")
    print(f"  Budget: ${args.budget:.2f}/{args.budget_duration}")
    print(f"  Rate limits: {args.rpm} RPM, {args.tpm} TPM")
    if args.models:
        print(f"  Allowed models: {args.models}")
    print(f"  PII Guardrail: {'enabled' if args.pii_guardrail else 'disabled'}")
    print(f"  Store prompts: {'yes' if args.store_prompts else 'no (privacy default)'}")


def cmd_team_list(args):
    """List all teams."""
    result = api_request("GET", "/team/list")
    
    teams = result if isinstance(result, list) else result.get("teams", [])
    
    if not teams:
        print("No teams found.")
        return
    
    print(f"\n{'Team Name':<20} {'Budget':<15} {'Spent':<12} {'RPM':<8} {'Models':<30}")
    print("-" * 85)
    
    for team in teams:
        name = team.get("team_alias", team.get("team_id", "unknown"))[:19]
        budget = team.get("max_budget", 0) or 0
        spent = team.get("spend", 0) or 0
        rpm = team.get("rpm_limit", "-")
        models = team.get("models", [])
        models_str = ", ".join(models[:3]) if models else "all"
        if models and len(models) > 3:
            models_str += f" (+{len(models)-3})"
        
        print(f"{name:<20} ${budget:<14.2f} ${spent:<11.2f} {str(rpm):<8} {models_str:<30}")


def cmd_team_info(args):
    """Get detailed team information."""
    result = api_request("GET", f"/team/info?team_id={args.team_id}")
    
    if not result:
        print(f"Team not found: {args.team_id}")
        return
    
    print(f"\n{'='*50}")
    print(f"Team: {result.get('team_alias', result.get('team_id'))}")
    print(f"{'='*50}")
    print(f"Team ID: {result.get('team_id')}")
    print(f"Budget: ${result.get('max_budget', 0):.2f} / {result.get('budget_duration', 'month')}")
    print(f"Current Spend: ${result.get('spend', 0):.2f}")
    print(f"Rate Limits: {result.get('rpm_limit', '-')} RPM, {result.get('tpm_limit', '-')} TPM")
    
    models = result.get("models", [])
    print(f"Allowed Models: {', '.join(models) if models else 'all'}")
    
    metadata = result.get("metadata", {})
    print(f"PII Guardrail: {'enabled' if metadata.get('pii_guardrail_enabled') else 'disabled'}")
    print(f"Store Prompts: {'yes' if metadata.get('store_prompts') else 'no'}")
    print(f"Store Responses: {'yes' if metadata.get('store_responses') else 'no'}")
    
    # Show members/keys
    members = result.get("members_with_roles", [])
    if members:
        print(f"\nMembers ({len(members)}):")
        for member in members[:10]:
            print(f"  - {member.get('user_id', 'unknown')} ({member.get('role', 'member')})")


def cmd_team_update(args):
    """Update team settings."""
    data = {"team_id": args.team_id}
    
    if args.budget is not None:
        data["max_budget"] = args.budget
    if args.rpm is not None:
        data["rpm_limit"] = args.rpm
    if args.tpm is not None:
        data["tpm_limit"] = args.tpm
    if args.models is not None:
        data["models"] = args.models.split(",") if args.models else None
    
    if args.pii_guardrail is not None or args.store_prompts is not None:
        data["metadata"] = {}
        if args.pii_guardrail is not None:
            data["metadata"]["pii_guardrail_enabled"] = args.pii_guardrail
        if args.store_prompts is not None:
            data["metadata"]["store_prompts"] = args.store_prompts
            data["metadata"]["store_responses"] = args.store_prompts
    
    result = api_request("POST", "/team/update", data)
    print(f"✓ Team updated: {args.team_id}")


def cmd_team_delete(args):
    """Delete a team."""
    if not args.force:
        confirm = input(f"Delete team {args.team_id}? This cannot be undone. [y/N]: ")
        if confirm.lower() != "y":
            print("Cancelled.")
            return
    
    api_request("DELETE", f"/team/delete?team_id={args.team_id}")
    print(f"✓ Team deleted: {args.team_id}")


# =============================================================================
# Key Management
# =============================================================================

def cmd_key_create(args):
    """Create a new API key."""
    data = {
        "team_id": args.team,
        "key_alias": args.alias or f"key-{args.user or 'default'}",
        "duration": args.duration,
    }
    
    if args.user:
        data["user_id"] = args.user
    if args.budget is not None:
        data["max_budget"] = args.budget
    if args.models:
        data["models"] = args.models.split(",")
    
    result = api_request("POST", "/key/generate", data)
    
    key = result.get("key", result.get("token", ""))
    
    print(f"\n✓ API Key created!")
    print(f"{'='*60}")
    print(f"  Key: {key}")
    print(f"{'='*60}")
    print(f"  Team: {args.team}")
    if args.user:
        print(f"  User: {args.user}")
    if args.budget:
        print(f"  Budget: ${args.budget:.2f}")
    print(f"\n⚠️  Save this key securely - it won't be shown again!")


def cmd_key_list(args):
    """List API keys."""
    endpoint = "/key/list"
    if args.team:
        endpoint += f"?team_id={args.team}"
    
    result = api_request("GET", endpoint)
    keys = result if isinstance(result, list) else result.get("keys", [])
    
    if not keys:
        print("No keys found.")
        return
    
    print(f"\n{'Key (masked)':<25} {'Team':<15} {'User':<15} {'Spend':<12} {'Expires':<12}")
    print("-" * 79)
    
    for key_info in keys:
        token = key_info.get("token", key_info.get("key", ""))
        # Mask the key
        if token:
            masked = token[:8] + "..." + token[-4:] if len(token) > 12 else token
        else:
            masked = "-"
        
        team = key_info.get("team_id", key_info.get("team_alias", "-"))
        if team and len(team) > 14:
            team = team[:11] + "..."
        
        user = key_info.get("user_id", "-") or "-"
        if user and len(user) > 14:
            user = user[:11] + "..."
        
        spend = key_info.get("spend", 0) or 0
        
        expires = key_info.get("expires")
        if expires:
            try:
                exp_date = datetime.fromisoformat(expires.replace("Z", "+00:00"))
                expires_str = exp_date.strftime("%Y-%m-%d")
            except Exception:
                expires_str = str(expires)[:10]
        else:
            expires_str = "never"
        
        print(f"{masked:<25} {team:<15} {user:<15} ${spend:<11.2f} {expires_str:<12}")


def cmd_key_info(args):
    """Get key information."""
    result = api_request("GET", f"/key/info?key={args.key}")
    
    print(f"\n{'='*50}")
    print(f"Key Information")
    print(f"{'='*50}")
    print(json.dumps(result, indent=2, default=str))


def cmd_key_delete(args):
    """Delete/revoke an API key."""
    if not args.force:
        confirm = input(f"Revoke key {args.key[:8]}...? [y/N]: ")
        if confirm.lower() != "y":
            print("Cancelled.")
            return
    
    api_request("POST", "/key/delete", {"keys": [args.key]})
    print(f"✓ Key revoked")


# =============================================================================
# Statistics
# =============================================================================

def cmd_stats(args):
    """Show usage statistics."""
    endpoint = "/global/spend/logs"
    params = []
    
    if args.team:
        params.append(f"team_id={args.team}")
    if args.days:
        start_date = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")
        params.append(f"start_date={start_date}")
    
    if params:
        endpoint += "?" + "&".join(params)
    
    result = api_request("GET", endpoint)
    
    print(f"\n{'='*60}")
    print("Usage Statistics")
    print(f"{'='*60}")
    
    if isinstance(result, dict):
        total_spend = result.get("total_spend", 0)
        print(f"Total Spend: ${total_spend:.4f}")
        
        logs = result.get("spend_logs", [])
        if logs:
            print(f"\nRecent requests: {len(logs)}")
            
            # Group by model
            by_model = {}
            for log in logs:
                model = log.get("model", "unknown")
                if model not in by_model:
                    by_model[model] = {"count": 0, "tokens": 0, "spend": 0}
                by_model[model]["count"] += 1
                by_model[model]["tokens"] += log.get("total_tokens", 0) or 0
                by_model[model]["spend"] += log.get("spend", 0) or 0
            
            print(f"\n{'Model':<30} {'Requests':<12} {'Tokens':<15} {'Spend':<12}")
            print("-" * 69)
            for model, stats in sorted(by_model.items(), key=lambda x: x[1]["spend"], reverse=True):
                print(f"{model[:29]:<30} {stats['count']:<12} {stats['tokens']:<15} ${stats['spend']:<11.4f}")
    else:
        print(json.dumps(result, indent=2, default=str))


def cmd_health(args):
    """Check gateway health."""
    try:
        result = api_request("GET", "/health")
        print("✓ Gateway is healthy")
        if args.verbose:
            print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"✗ Gateway health check failed: {e}")
        sys.exit(1)


def cmd_models(args):
    """List available models."""
    result = api_request("GET", "/model/info")
    
    models = result.get("data", []) if isinstance(result, dict) else result
    
    if not models:
        print("No models configured.")
        return
    
    print(f"\n{'Model Name':<30} {'Provider':<15} {'Tier':<10}")
    print("-" * 55)
    
    for model in models:
        name = model.get("model_name", "unknown")
        info = model.get("model_info", {})
        tier = info.get("tier", "-")
        
        # Extract provider from model name
        if "/" in name:
            provider = name.split("/")[0]
        else:
            provider = "litellm"
        
        print(f"{name:<30} {provider:<15} {tier:<10}")


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="LLM Gateway Kit CLI - Manage teams, keys, and budgets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s team create --name engineering --budget 500
  %(prog)s team create --name support --budget 100 --pii-guardrail --models openai/gpt-4o-mini,local/small
  %(prog)s key create --team engineering --user alice@company.com
  %(prog)s key create --team support --budget 20 --duration 30d
  %(prog)s stats --team engineering --days 7
  %(prog)s models

Environment:
  LITELLM_URL          Gateway URL (default: http://localhost:4000)
  LITELLM_MASTER_KEY   Master key for admin operations
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # Team commands
    team_parser = subparsers.add_parser("team", help="Team management")
    team_sub = team_parser.add_subparsers(dest="team_command")
    
    # team create
    team_create = team_sub.add_parser("create", help="Create a new team")
    team_create.add_argument("--name", "-n", required=True, help="Team name")
    team_create.add_argument("--budget", "-b", type=float, default=100.0, help="Budget limit (default: 100)")
    team_create.add_argument("--budget-duration", choices=["daily", "weekly", "monthly"], default="monthly")
    team_create.add_argument("--rpm", type=int, default=100, help="Requests per minute limit")
    team_create.add_argument("--tpm", type=int, default=100000, help="Tokens per minute limit")
    team_create.add_argument("--models", help="Comma-separated list of allowed models")
    team_create.add_argument("--description", help="Team description")
    team_create.add_argument("--pii-guardrail", action="store_true", help="Enable PII guardrail")
    team_create.add_argument("--store-prompts", action="store_true", help="Store full prompts (privacy opt-in)")
    team_create.add_argument("--store-responses", action="store_true", help="Store full responses (privacy opt-in)")
    team_create.set_defaults(func=cmd_team_create)
    
    # team list
    team_list = team_sub.add_parser("list", help="List all teams")
    team_list.set_defaults(func=cmd_team_list)
    
    # team info
    team_info = team_sub.add_parser("info", help="Get team details")
    team_info.add_argument("team_id", help="Team ID or name")
    team_info.set_defaults(func=cmd_team_info)
    
    # team update
    team_update = team_sub.add_parser("update", help="Update team settings")
    team_update.add_argument("team_id", help="Team ID")
    team_update.add_argument("--budget", type=float, help="New budget limit")
    team_update.add_argument("--rpm", type=int, help="New RPM limit")
    team_update.add_argument("--tpm", type=int, help="New TPM limit")
    team_update.add_argument("--models", help="New allowed models (comma-separated)")
    team_update.add_argument("--pii-guardrail", type=bool, help="Enable/disable PII guardrail")
    team_update.add_argument("--store-prompts", type=bool, help="Enable/disable prompt storage")
    team_update.set_defaults(func=cmd_team_update)
    
    # team delete
    team_delete = team_sub.add_parser("delete", help="Delete a team")
    team_delete.add_argument("team_id", help="Team ID")
    team_delete.add_argument("--force", "-f", action="store_true", help="Skip confirmation")
    team_delete.set_defaults(func=cmd_team_delete)
    
    # Key commands
    key_parser = subparsers.add_parser("key", help="API key management")
    key_sub = key_parser.add_subparsers(dest="key_command")
    
    # key create
    key_create = key_sub.add_parser("create", help="Create a new API key")
    key_create.add_argument("--team", "-t", required=True, help="Team ID or name")
    key_create.add_argument("--user", "-u", help="User ID (for attribution)")
    key_create.add_argument("--alias", "-a", help="Key alias/name")
    key_create.add_argument("--budget", "-b", type=float, help="Per-key budget limit")
    key_create.add_argument("--duration", "-d", default="90d", help="Key validity (e.g., 30d, 1y)")
    key_create.add_argument("--models", help="Comma-separated list of allowed models")
    key_create.set_defaults(func=cmd_key_create)
    
    # key list
    key_list = key_sub.add_parser("list", help="List API keys")
    key_list.add_argument("--team", "-t", help="Filter by team")
    key_list.set_defaults(func=cmd_key_list)
    
    # key info
    key_info = key_sub.add_parser("info", help="Get key information")
    key_info.add_argument("key", help="API key")
    key_info.set_defaults(func=cmd_key_info)
    
    # key delete
    key_delete = key_sub.add_parser("delete", help="Revoke an API key")
    key_delete.add_argument("key", help="API key to revoke")
    key_delete.add_argument("--force", "-f", action="store_true", help="Skip confirmation")
    key_delete.set_defaults(func=cmd_key_delete)
    
    # Stats command
    stats_parser = subparsers.add_parser("stats", help="Usage statistics")
    stats_parser.add_argument("--team", "-t", help="Filter by team")
    stats_parser.add_argument("--days", "-d", type=int, default=7, help="Days to look back (default: 7)")
    stats_parser.set_defaults(func=cmd_stats)
    
    # Health command
    health_parser = subparsers.add_parser("health", help="Check gateway health")
    health_parser.add_argument("--verbose", "-v", action="store_true")
    health_parser.set_defaults(func=cmd_health)
    
    # Models command
    models_parser = subparsers.add_parser("models", help="List available models")
    models_parser.set_defaults(func=cmd_models)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    if args.command == "team" and not args.team_command:
        team_parser.print_help()
        sys.exit(1)
    
    if args.command == "key" and not args.key_command:
        key_parser.print_help()
        sys.exit(1)
    
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
