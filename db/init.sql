-- =============================================================================
-- LLM Steward - Database Initialization
-- =============================================================================
-- This script sets up additional tables for observability and team management.
-- LiteLLM creates its own tables; this adds our extensions.

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- -----------------------------------------------------------------------------
-- Teams Table (extends LiteLLM's team concept)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gateway_teams (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    
    -- Budget configuration
    budget_limit DECIMAL(10, 2) DEFAULT 100.00,
    budget_duration VARCHAR(20) DEFAULT 'monthly', -- daily, weekly, monthly
    current_spend DECIMAL(10, 2) DEFAULT 0.00,
    budget_reset_at TIMESTAMP WITH TIME ZONE,
    
    -- Rate limiting
    rpm_limit INTEGER DEFAULT 100, -- requests per minute
    tpm_limit INTEGER DEFAULT 100000, -- tokens per minute
    
    -- Model access (JSON array of allowed model names, null = all)
    allowed_models JSONB DEFAULT NULL,
    
    -- Guardrail configuration
    pii_guardrail_enabled BOOLEAN DEFAULT false,
    custom_guardrails JSONB DEFAULT '[]'::jsonb,
    
    -- Privacy settings
    store_prompts BOOLEAN DEFAULT false, -- opt-in prompt storage
    store_responses BOOLEAN DEFAULT false, -- opt-in response storage
    
    -- Metadata
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- Request Log Table (observability)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gateway_request_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- Request identification
    request_id VARCHAR(255) NOT NULL,
    litellm_call_id VARCHAR(255),
    
    -- Attribution
    team_id UUID REFERENCES gateway_teams(id),
    team_name VARCHAR(255),
    api_key_hash VARCHAR(255), -- hashed key for identification
    user_id VARCHAR(255), -- optional user within team
    
    -- Request details
    model_requested VARCHAR(255),
    model_used VARCHAR(255),
    endpoint VARCHAR(50) DEFAULT 'chat/completions',
    
    -- Metrics
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    cost DECIMAL(10, 6) DEFAULT 0.000000,
    latency_ms INTEGER DEFAULT 0,
    
    -- Status
    status VARCHAR(20) DEFAULT 'success', -- success, error, blocked
    error_type VARCHAR(100),
    error_message TEXT,
    
    -- Guardrail data
    guardrail_triggered BOOLEAN DEFAULT false,
    guardrail_name VARCHAR(100),
    guardrail_action VARCHAR(50), -- blocked, redacted, warned
    pii_types_detected JSONB DEFAULT '[]'::jsonb,
    
    -- Content (privacy-aware)
    prompt_preview VARCHAR(200), -- first 200 chars, always redacted
    response_preview VARCHAR(200), -- first 200 chars, always redacted
    prompt_full TEXT, -- only if team.store_prompts = true
    response_full TEXT, -- only if team.store_responses = true
    
    -- Metadata
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for common queries
CREATE INDEX IF NOT EXISTS idx_request_logs_team_id ON gateway_request_logs(team_id);
CREATE INDEX IF NOT EXISTS idx_request_logs_created_at ON gateway_request_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_request_logs_model ON gateway_request_logs(model_used);
CREATE INDEX IF NOT EXISTS idx_request_logs_status ON gateway_request_logs(status);
CREATE INDEX IF NOT EXISTS idx_request_logs_team_created ON gateway_request_logs(team_id, created_at);

-- -----------------------------------------------------------------------------
-- Guardrail Events Table (detailed guardrail tracking)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gateway_guardrail_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id VARCHAR(255) NOT NULL,
    team_id UUID REFERENCES gateway_teams(id),
    
    guardrail_name VARCHAR(100) NOT NULL,
    guardrail_type VARCHAR(50), -- pii, custom, content_filter
    action_taken VARCHAR(50) NOT NULL, -- blocked, redacted, warned, passed
    
    -- PII-specific fields
    pii_entity_type VARCHAR(50),
    pii_count INTEGER DEFAULT 0,
    
    -- Details (never includes actual PII)
    details JSONB DEFAULT '{}'::jsonb,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_guardrail_events_team ON gateway_guardrail_events(team_id);
CREATE INDEX IF NOT EXISTS idx_guardrail_events_created ON gateway_guardrail_events(created_at);

-- -----------------------------------------------------------------------------
-- Budget Alerts Table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gateway_budget_alerts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    team_id UUID REFERENCES gateway_teams(id),
    
    alert_type VARCHAR(50) NOT NULL, -- threshold_warning, budget_exceeded, rate_limit_hit
    threshold_percent INTEGER, -- e.g., 80 for 80% warning
    current_spend DECIMAL(10, 2),
    budget_limit DECIMAL(10, 2),
    
    acknowledged BOOLEAN DEFAULT false,
    acknowledged_at TIMESTAMP WITH TIME ZONE,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- Aggregation Views for Dashboard
-- -----------------------------------------------------------------------------

-- Hourly usage aggregation
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_hourly_usage AS
SELECT 
    date_trunc('hour', created_at) AS hour,
    team_id,
    team_name,
    model_used,
    COUNT(*) AS request_count,
    SUM(total_tokens) AS total_tokens,
    SUM(cost) AS total_cost,
    AVG(latency_ms) AS avg_latency_ms,
    COUNT(*) FILTER (WHERE status = 'error') AS error_count,
    COUNT(*) FILTER (WHERE guardrail_triggered) AS guardrail_count
FROM gateway_request_logs
GROUP BY date_trunc('hour', created_at), team_id, team_name, model_used;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_hourly_usage 
ON mv_hourly_usage(hour, team_id, model_used);

-- Daily usage aggregation
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_daily_usage AS
SELECT 
    date_trunc('day', created_at) AS day,
    team_id,
    team_name,
    model_used,
    COUNT(*) AS request_count,
    SUM(total_tokens) AS total_tokens,
    SUM(cost) AS total_cost,
    AVG(latency_ms) AS avg_latency_ms,
    COUNT(*) FILTER (WHERE status = 'error') AS error_count,
    COUNT(*) FILTER (WHERE guardrail_triggered) AS guardrail_count
FROM gateway_request_logs
GROUP BY date_trunc('day', created_at), team_id, team_name, model_used;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_daily_usage 
ON mv_daily_usage(day, team_id, model_used);

-- -----------------------------------------------------------------------------
-- Functions
-- -----------------------------------------------------------------------------

-- Function to refresh materialized views (call periodically)
CREATE OR REPLACE FUNCTION refresh_usage_views()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_hourly_usage;
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_daily_usage;
END;
$$ LANGUAGE plpgsql;

-- Function to reset team budgets
CREATE OR REPLACE FUNCTION reset_team_budgets()
RETURNS void AS $$
BEGIN
    UPDATE gateway_teams 
    SET current_spend = 0, 
        budget_reset_at = NOW() + 
            CASE budget_duration 
                WHEN 'daily' THEN INTERVAL '1 day'
                WHEN 'weekly' THEN INTERVAL '1 week'
                WHEN 'monthly' THEN INTERVAL '1 month'
                ELSE INTERVAL '1 month'
            END,
        updated_at = NOW()
    WHERE budget_reset_at IS NULL OR budget_reset_at <= NOW();
END;
$$ LANGUAGE plpgsql;

-- Trigger to update team spend when requests are logged
CREATE OR REPLACE FUNCTION update_team_spend()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.team_id IS NOT NULL AND NEW.cost > 0 THEN
        UPDATE gateway_teams 
        SET current_spend = current_spend + NEW.cost,
            updated_at = NOW()
        WHERE id = NEW.team_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_update_team_spend
AFTER INSERT ON gateway_request_logs
FOR EACH ROW
EXECUTE FUNCTION update_team_spend();

-- -----------------------------------------------------------------------------
-- Default Data
-- -----------------------------------------------------------------------------

-- Insert default teams for demo
INSERT INTO gateway_teams (name, description, budget_limit, pii_guardrail_enabled, allowed_models)
VALUES 
    ('engineering', 'Engineering team - full access', 500.00, false, NULL),
    ('support', 'Customer support - budget limited', 100.00, true, '["openai/gpt-4o-mini", "local/small", "fast"]'),
    ('analytics', 'Data analytics team', 200.00, true, '["openai/gpt-4o", "anthropic/claude-3-5-sonnet", "smart"]')
ON CONFLICT (name) DO NOTHING;
