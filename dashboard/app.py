"""
LLM Gateway Kit - Observability Dashboard
==========================================
A lightweight dashboard for monitoring gateway usage, spend, and guardrail events.
"""

import os
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
import json
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import asyncpg
import httpx

# Configuration
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://litellm:litellm@localhost:5432/litellm")
LITELLM_URL = os.environ.get("LITELLM_URL", "http://litellm:4000")
LITELLM_MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY", "sk-master-key-change-me")

# Database pool
db_pool: Optional[asyncpg.Pool] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage database connection pool lifecycle."""
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    yield
    if db_pool:
        await db_pool.close()


app = FastAPI(
    title="LLM Gateway Dashboard",
    description="Observability dashboard for LLM Gateway Kit",
    version="1.0.0",
    lifespan=lifespan,
)

# Templates
templates = Jinja2Templates(directory="/app/templates")


# =============================================================================
# API Routes
# =============================================================================

@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.get("/api/summary")
async def get_summary(
    hours: int = Query(24, ge=1, le=720),
    team_id: Optional[str] = None,
):
    """Get summary statistics for the dashboard using LiteLLM's spend logs."""
    async with db_pool.acquire() as conn:
        # Build time filter
        since = datetime.utcnow() - timedelta(hours=hours)
        team_filter = 'AND sl.team_id = $2' if team_id else ""
        params = [since, team_id] if team_id else [since]
        
        # Total requests and tokens from LiteLLM_SpendLogs
        totals = await conn.fetchrow(f"""
            SELECT 
                COUNT(*) as total_requests,
                COALESCE(SUM(sl.total_tokens), 0) as total_tokens,
                COALESCE(SUM(sl.spend), 0) as total_cost,
                COALESCE(AVG(sl.request_duration_ms), 0) as avg_latency,
                COUNT(*) FILTER (WHERE sl.status = 'failure') as error_count,
                COUNT(*) FILTER (WHERE sl.metadata::text LIKE '%guardrail%') as guardrail_count
            FROM "LiteLLM_SpendLogs" sl
            WHERE sl.created_at >= $1 AND sl.call_type = 'acompletion' {team_filter}
        """, *params)
        
        # Active teams with names from LiteLLM_TeamTable
        teams = await conn.fetch(f"""
            SELECT DISTINCT t.team_alias as team_name, sl.team_id
            FROM "LiteLLM_SpendLogs" sl
            LEFT JOIN "LiteLLM_TeamTable" t ON sl.team_id = t.team_id
            WHERE sl.created_at >= $1 AND sl.team_id IS NOT NULL AND sl.call_type = 'acompletion' {team_filter}
        """, *params)
        
        # Active models
        models = await conn.fetch(f"""
            SELECT model_group as model_used, COUNT(*) as count
            FROM "LiteLLM_SpendLogs" sl
            WHERE sl.created_at >= $1 AND sl.model_group IS NOT NULL AND sl.call_type = 'acompletion' {team_filter}
            GROUP BY model_group
            ORDER BY count DESC
            LIMIT 10
        """, *params)
        
        return {
            "period_hours": hours,
            "total_requests": totals["total_requests"],
            "total_tokens": int(totals["total_tokens"]),
            "total_cost": float(totals["total_cost"]),
            "avg_latency_ms": float(totals["avg_latency"]),
            "error_count": totals["error_count"],
            "error_rate": totals["error_count"] / max(totals["total_requests"], 1) * 100,
            "guardrail_count": totals["guardrail_count"],
            "active_teams": len(teams),
            "teams": [{"name": t["team_name"], "id": str(t["team_id"]) if t["team_id"] else None} for t in teams],
            "top_models": [{"model": m["model_used"], "count": m["count"]} for m in models],
        }


@app.get("/api/usage/timeseries")
async def get_usage_timeseries(
    hours: int = Query(24, ge=1, le=720),
    interval: str = Query("hour", regex="^(hour|day)$"),
    team_id: Optional[str] = None,
):
    """Get usage data over time for charts."""
    async with db_pool.acquire() as conn:
        since = datetime.utcnow() - timedelta(hours=hours)
        team_filter = "AND team_id = $2" if team_id else ""
        params = [since, team_id] if team_id else [since]
        
        rows = await conn.fetch(f"""
            SELECT 
                date_trunc('{interval}', created_at) as bucket,
                COUNT(*) as requests,
                COALESCE(SUM(total_tokens), 0) as tokens,
                COALESCE(SUM(cost), 0) as cost,
                COALESCE(AVG(latency_ms), 0) as avg_latency,
                COUNT(*) FILTER (WHERE status = 'error') as errors,
                COUNT(*) FILTER (WHERE guardrail_triggered) as guardrails
            FROM gateway_request_logs
            WHERE created_at >= $1 {team_filter}
            GROUP BY bucket
            ORDER BY bucket
        """, *params)
        
        return {
            "interval": interval,
            "data": [
                {
                    "timestamp": r["bucket"].isoformat(),
                    "requests": r["requests"],
                    "tokens": int(r["tokens"]),
                    "cost": float(r["cost"]),
                    "avg_latency": float(r["avg_latency"]),
                    "errors": r["errors"],
                    "guardrails": r["guardrails"],
                }
                for r in rows
            ]
        }


@app.get("/api/usage/by-team")
async def get_usage_by_team(
    hours: int = Query(24, ge=1, le=720),
):
    """Get usage breakdown by team using LiteLLM's spend logs."""
    async with db_pool.acquire() as conn:
        since = datetime.utcnow() - timedelta(hours=hours)
        
        rows = await conn.fetch("""
            SELECT 
                COALESCE(t.team_alias, 'unknown') as team,
                COUNT(*) as requests,
                COALESCE(SUM(sl.total_tokens), 0) as tokens,
                COALESCE(SUM(sl.spend), 0) as cost,
                COUNT(*) FILTER (WHERE sl.status = 'failure') as errors,
                COUNT(*) FILTER (WHERE sl.metadata::text LIKE '%guardrail%') as guardrails
            FROM "LiteLLM_SpendLogs" sl
            LEFT JOIN "LiteLLM_TeamTable" t ON sl.team_id = t.team_id
            WHERE sl.created_at >= $1 AND sl.call_type = 'acompletion'
            GROUP BY t.team_alias
            ORDER BY cost DESC
        """, since)
        
        return {
            "data": [
                {
                    "team": r["team"],
                    "requests": r["requests"],
                    "tokens": int(r["tokens"]),
                    "cost": float(r["cost"]),
                    "errors": r["errors"],
                    "guardrails": r["guardrails"],
                }
                for r in rows
            ]
        }


@app.get("/api/usage/by-model")
async def get_usage_by_model(
    hours: int = Query(24, ge=1, le=720),
    team_id: Optional[str] = None,
):
    """Get usage breakdown by model using LiteLLM's spend logs."""
    async with db_pool.acquire() as conn:
        since = datetime.utcnow() - timedelta(hours=hours)
        team_filter = "AND sl.team_id = $2" if team_id else ""
        params = [since, team_id] if team_id else [since]
        
        rows = await conn.fetch(f"""
            SELECT 
                COALESCE(sl.model_group, 'unknown') as model,
                COUNT(*) as requests,
                COALESCE(SUM(sl.total_tokens), 0) as tokens,
                COALESCE(SUM(sl.spend), 0) as cost,
                COALESCE(AVG(sl.request_duration_ms), 0) as avg_latency,
                COUNT(*) FILTER (WHERE sl.status = 'failure') as errors
            FROM "LiteLLM_SpendLogs" sl
            WHERE sl.created_at >= $1 AND sl.call_type = 'acompletion' {team_filter}
            GROUP BY sl.model_group
            ORDER BY requests DESC
        """, *params)
        
        return {
            "data": [
                {
                    "model": r["model"],
                    "requests": r["requests"],
                    "tokens": int(r["tokens"]),
                    "cost": float(r["cost"]),
                    "avg_latency": float(r["avg_latency"]),
                    "errors": r["errors"],
                }
                for r in rows
            ]
        }


@app.get("/api/usage/by-user")
async def get_usage_by_user(
    hours: int = Query(24, ge=1, le=720),
    team_id: Optional[str] = None,
):
    """Get usage breakdown by user."""
    async with db_pool.acquire() as conn:
        since = datetime.utcnow() - timedelta(hours=hours)
        team_filter = "AND team_id = $2" if team_id else ""
        params = [since, team_id] if team_id else [since]
        
        rows = await conn.fetch(f"""
            SELECT 
                COALESCE(user_id, api_key_hash, 'anonymous') as user_id,
                team_name,
                COUNT(*) as requests,
                COALESCE(SUM(total_tokens), 0) as tokens,
                COALESCE(SUM(cost), 0) as cost
            FROM gateway_request_logs
            WHERE created_at >= $1 {team_filter}
            GROUP BY user_id, api_key_hash, team_name
            ORDER BY cost DESC
            LIMIT 50
        """, *params)
        
        return {
            "data": [
                {
                    "user": r["user_id"],
                    "team": r["team_name"],
                    "requests": r["requests"],
                    "tokens": int(r["tokens"]),
                    "cost": float(r["cost"]),
                }
                for r in rows
            ]
        }


@app.get("/api/budgets")
async def get_budgets():
    """Get team budget status from LiteLLM's team table with actual spend from spend logs."""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT 
                t.team_alias as name,
                t.max_budget as budget_limit,
                COALESCE(spend.total_spend, 0) as current_spend,
                'monthly' as budget_duration,
                NULL as budget_reset_at,
                gt.pii_guardrail_enabled
            FROM "LiteLLM_TeamTable" t
            LEFT JOIN (
                SELECT team_id, SUM(spend) as total_spend
                FROM "LiteLLM_SpendLogs"
                WHERE call_type = 'acompletion'
                GROUP BY team_id
            ) spend ON t.team_id = spend.team_id
            LEFT JOIN gateway_teams gt ON t.team_alias = gt.name
            ORDER BY current_spend DESC
        """)
        
        return {
            "data": [
                {
                    "team": r["name"],
                    "budget_limit": float(r["budget_limit"]) if r["budget_limit"] else 0,
                    "current_spend": float(r["current_spend"]) if r["current_spend"] else 0,
                    "budget_duration": r["budget_duration"],
                    "budget_reset_at": r["budget_reset_at"].isoformat() if r["budget_reset_at"] else None,
                    "pii_guardrail": r["pii_guardrail_enabled"] if r["pii_guardrail_enabled"] is not None else False,
                    "usage_percent": (float(r["current_spend"]) / float(r["budget_limit"]) * 100) if r["budget_limit"] and r["budget_limit"] > 0 else 0,
                }
                for r in rows
            ]
        }


@app.get("/api/guardrails")
async def get_guardrail_events(
    hours: int = Query(24, ge=1, le=720),
    team_id: Optional[str] = None,
):
    """Get guardrail trigger events."""
    async with db_pool.acquire() as conn:
        since = datetime.utcnow() - timedelta(hours=hours)
        team_filter = "AND team_id = $2" if team_id else ""
        params = [since, team_id] if team_id else [since]
        
        # Summary by type
        summary = await conn.fetch(f"""
            SELECT 
                guardrail_name,
                pii_entity_type,
                action_taken,
                COUNT(*) as count
            FROM gateway_guardrail_events
            WHERE created_at >= $1 {team_filter}
            GROUP BY guardrail_name, pii_entity_type, action_taken
            ORDER BY count DESC
        """, *params)
        
        # Recent events
        recent = await conn.fetch(f"""
            SELECT 
                ge.guardrail_name,
                ge.pii_entity_type,
                ge.action_taken,
                ge.created_at,
                gt.name as team_name
            FROM gateway_guardrail_events ge
            LEFT JOIN gateway_teams gt ON ge.team_id = gt.id
            WHERE ge.created_at >= $1 {team_filter}
            ORDER BY ge.created_at DESC
            LIMIT 100
        """, *params)
        
        return {
            "summary": [
                {
                    "guardrail": s["guardrail_name"],
                    "entity_type": s["pii_entity_type"],
                    "action": s["action_taken"],
                    "count": s["count"],
                }
                for s in summary
            ],
            "recent": [
                {
                    "guardrail": r["guardrail_name"],
                    "entity_type": r["pii_entity_type"],
                    "action": r["action_taken"],
                    "team": r["team_name"],
                    "timestamp": r["created_at"].isoformat(),
                }
                for r in recent
            ],
        }


@app.post("/api/hook-events")
async def record_hook_event(request: Request):
    """
    Record a guardrail event from a Cursor hook.
    
    Used by the pii_guard.py hook to log block events.
    Only stores metadata - never the prompt content.
    """
    try:
        data = await request.json()
        
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO gateway_guardrail_events (
                    request_id, team_id, guardrail_name, guardrail_type,
                    action_taken, pii_entity_type, details
                ) 
                SELECT 
                    $1,
                    gt.id,
                    $3,
                    $4,
                    $5,
                    $6,
                    $7
                FROM gateway_teams gt
                WHERE gt.name = $2
                """,
                data.get("conversation_id", "cursor-hook-" + datetime.utcnow().strftime("%Y%m%d%H%M%S")),
                data.get("team_name", "cursor-users"),
                data.get("guardrail_name", "pii-guard-cursor"),
                data.get("guardrail_type", "pii"),
                data.get("action_taken", "blocked"),
                ", ".join(data.get("pii_types_detected", [])),
                json.dumps({
                    "source": data.get("source", "cursor_hook"),
                    "user_id": data.get("user_id"),
                    "pii_types": data.get("pii_types_detected", []),
                    "timestamp": data.get("timestamp"),
                }),
            )
        
        return {"status": "recorded"}
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)},
        )


@app.get("/api/errors")
async def get_errors(
    hours: int = Query(24, ge=1, le=720),
    limit: int = Query(50, ge=1, le=200),
):
    """Get recent errors."""
    async with db_pool.acquire() as conn:
        since = datetime.utcnow() - timedelta(hours=hours)
        
        rows = await conn.fetch("""
            SELECT 
                request_id,
                team_name,
                model_requested,
                error_type,
                error_message,
                created_at
            FROM gateway_request_logs
            WHERE created_at >= $1 AND status = 'error'
            ORDER BY created_at DESC
            LIMIT $2
        """, since, limit)
        
        return {
            "data": [
                {
                    "request_id": r["request_id"],
                    "team": r["team_name"],
                    "model": r["model_requested"],
                    "error_type": r["error_type"],
                    "error_message": r["error_message"][:200] if r["error_message"] else None,
                    "timestamp": r["created_at"].isoformat(),
                }
                for r in rows
            ]
        }


@app.get("/api/requests")
async def get_requests(
    hours: int = Query(1, ge=1, le=24),
    limit: int = Query(100, ge=1, le=500),
    team_id: Optional[str] = None,
):
    """Get recent requests (for detailed view)."""
    async with db_pool.acquire() as conn:
        since = datetime.utcnow() - timedelta(hours=hours)
        team_filter = "AND team_id = $3" if team_id else ""
        params = [since, limit, team_id] if team_id else [since, limit]
        
        rows = await conn.fetch(f"""
            SELECT 
                request_id,
                team_name,
                user_id,
                model_requested,
                model_used,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                cost,
                latency_ms,
                status,
                guardrail_triggered,
                prompt_preview,
                created_at
            FROM gateway_request_logs
            WHERE created_at >= $1 {team_filter}
            ORDER BY created_at DESC
            LIMIT $2
        """, *params)
        
        return {
            "data": [
                {
                    "request_id": r["request_id"],
                    "team": r["team_name"],
                    "user": r["user_id"],
                    "model_requested": r["model_requested"],
                    "model_used": r["model_used"],
                    "tokens": {
                        "prompt": r["prompt_tokens"],
                        "completion": r["completion_tokens"],
                        "total": r["total_tokens"],
                    },
                    "cost": float(r["cost"]) if r["cost"] else 0,
                    "latency_ms": r["latency_ms"],
                    "status": r["status"],
                    "guardrail_triggered": r["guardrail_triggered"],
                    "prompt_preview": r["prompt_preview"],
                    "timestamp": r["created_at"].isoformat(),
                }
                for r in rows
            ]
        }


# =============================================================================
# HTML Routes
# =============================================================================

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page."""
    return templates.TemplateResponse(request, "dashboard.html")


@app.get("/teams", response_class=HTMLResponse)
async def teams_page(request: Request):
    """Teams overview page."""
    return templates.TemplateResponse(request, "teams.html")


@app.get("/requests", response_class=HTMLResponse)
async def requests_page(request: Request):
    """Recent requests page."""
    return templates.TemplateResponse(request, "requests.html")


@app.get("/guardrails", response_class=HTMLResponse)
async def guardrails_page(request: Request):
    """Guardrails page."""
    return templates.TemplateResponse(request, "guardrails.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
