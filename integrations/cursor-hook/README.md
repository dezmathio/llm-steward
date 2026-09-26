# Cursor PII Guard Hook

A Cursor hook that checks prompts for PII before they're sent to the model. Uses the same Presidio analyzer as the LLM Gateway, so your PII detection policy lives in one place.

## What It Does

When you hit send in Cursor, this hook:

1. Intercepts the prompt via the `beforeSubmitPrompt` hook
2. Sends the text to your gateway's Presidio analyzer
3. If PII is detected: blocks the prompt and tells you what types were found (never the values)
4. If no PII: allows the prompt through
5. Logs block events to the gateway's observability dashboard

## What It Doesn't Do

- **It only sees prompts you submit** - Tab completions, inline suggestions, and other Cursor traffic may not go through this hook
- **It's a guardrail, not a compliance guarantee** - Pattern-based PII detection has limits; this doesn't make you HIPAA/GDPR compliant
- **It doesn't modify prompts** - It can only allow or block; redaction happens at the gateway level

## Installation

### Project-Level (Recommended)

Apply to a specific repository:

```bash
# Copy the hook to your project
mkdir -p .cursor/hooks
cp integrations/cursor-hook/pii_guard.py .cursor/hooks/

# Create hooks.json in your project
cp integrations/cursor-hook/hooks.project.json .cursor/hooks.json
```

Your `.cursor/hooks.json`:

```json
{
  "version": 1,
  "hooks": {
    "beforeSubmitPrompt": [
      {
        "command": "python3 .cursor/hooks/pii_guard.py",
        "timeout": 10
      }
    ]
  }
}
```

### User-Level (Global)

Apply to all your Cursor projects:

```bash
# Copy to your home directory
mkdir -p ~/.cursor/hooks
cp integrations/cursor-hook/pii_guard.py ~/.cursor/hooks/

# Create user hooks.json
cp integrations/cursor-hook/hooks.user.json ~/.cursor/hooks.json
```

Your `~/.cursor/hooks.json`:

```json
{
  "version": 1,
  "hooks": {
    "beforeSubmitPrompt": [
      {
        "command": "python3 ~/.cursor/hooks/pii_guard.py",
        "timeout": 10
      }
    ]
  }
}
```

## Configuration

Set these environment variables (in your shell profile or the hook command):

| Variable | Default | Description |
|----------|---------|-------------|
| `PRESIDIO_URL` | `http://localhost:5001` | Presidio analyzer URL |
| `GATEWAY_URL` | `http://localhost:4000` | Gateway URL (for future use) |
| `DASHBOARD_URL` | `http://localhost:8080` | Dashboard URL for logging |
| `PII_GUARD_FAIL_OPEN` | `true` | Allow prompts when gateway is unreachable |
| `PII_GUARD_TEAM` | `cursor-users` | Team name for observability |
| `PII_GUARD_USER` | `$CURSOR_USER_EMAIL` | User ID for observability |

### Fail-Open vs Fail-Closed

**Fail-Open (Default)**: When the gateway/Presidio is unreachable, prompts are allowed through with a warning.

- Pros: Doesn't block work when the gateway is down
- Cons: PII could slip through during outages

**Fail-Closed**: When the gateway/Presidio is unreachable, prompts are blocked.

- Pros: Maximum protection - nothing gets through without a PII check
- Cons: Gateway outage = no AI assistance

To enable fail-closed:

```json
{
  "version": 1,
  "hooks": {
    "beforeSubmitPrompt": [
      {
        "command": "PII_GUARD_FAIL_OPEN=false python3 .cursor/hooks/pii_guard.py",
        "timeout": 10,
        "failClosed": true
      }
    ]
  }
}
```

Note: Setting both `PII_GUARD_FAIL_OPEN=false` in the environment AND `failClosed: true` in the hook config gives the strongest protection. The env var controls the script's behavior; `failClosed` controls what Cursor does if the script crashes or times out.

## Observability

Block events are logged to the gateway's dashboard at `http://localhost:8080/guardrails`. Each event records:

- Team name
- User ID (from `CURSOR_USER_EMAIL` or `PII_GUARD_USER`)
- Entity types detected (PERSON, EMAIL_ADDRESS, etc.)
- Timestamp
- **Never the actual prompt content**

This lets you see Cursor-side blocks alongside gateway-side guardrail hits in one place.

## PII Types Detected

The hook checks for the same entity types as the gateway:

| Entity Type | Examples |
|-------------|----------|
| `PERSON` | John Smith, Dr. Jane Doe |
| `EMAIL_ADDRESS` | user@example.com |
| `PHONE_NUMBER` | 555-123-4567, (555) 123-4567 |
| `CREDIT_CARD` | 4111-1111-1111-1111 |
| `US_SSN` | 123-45-6789 |
| `US_BANK_NUMBER` | Bank account patterns |
| `IP_ADDRESS` | 192.168.1.1, 10.0.0.1 |
| `LOCATION` | 123 Main St, New York, NY |

## Testing

Run the hook tests:

```bash
pytest integrations/cursor-hook/test_pii_guard.py -v
```

Test manually:

```bash
# Should fail-open (no Presidio running)
echo '{"prompt": "Contact john@example.com"}' | python3 integrations/cursor-hook/pii_guard.py

# With gateway running
make up
echo '{"prompt": "Contact john@example.com"}' | python3 integrations/cursor-hook/pii_guard.py
```

## Troubleshooting

### Hook not running

1. Check the Hooks output channel in Cursor: `View > Output > Hooks`
2. Verify the hooks.json path is correct
3. Ensure the script is executable: `chmod +x pii_guard.py`
4. Check Python is available: `which python3`

### Always failing/blocking

1. Check if `PII_GUARD_FAIL_OPEN=false` is set
2. Verify Presidio is reachable: `curl http://localhost:5001/health`
3. Check the Hooks output for error messages

### False positives

Presidio's pattern matching can have false positives. If certain prompts are incorrectly flagged:

1. Check which entity type triggered: the block message tells you
2. Consider adjusting the score threshold in the script
3. Report patterns that cause issues

## Architecture

```
┌──────────────────┐     ┌─────────────────────┐     ┌───────────────┐
│     Cursor       │     │   pii_guard.py      │     │   Presidio    │
│                  │────►│                     │────►│   Analyzer    │
│ beforeSubmitPrompt     │  (same rules as     │     │               │
│                  │◄────│   gateway)          │◄────│   (shared)    │
│                  │     │                     │     │               │
└──────────────────┘     └─────────────────────┘     └───────────────┘
        │                         │
        │                         │ Log block events
        │                         ▼
        │                 ┌───────────────┐
        │                 │   Dashboard   │
        │                 │               │
        │                 │ Shows blocks  │
        └────────────────►│ from Cursor   │
          If allowed      │ + gateway     │
                          └───────────────┘
```

## Enterprise Deployment

For team-wide enforcement:

1. **Project hooks**: Commit `.cursor/hooks.json` and the script to your repos
2. **MDM distribution**: Deploy to `~/.cursor/hooks/` via your MDM tool
3. **Cloud distribution** (Enterprise): Configure in Cursor dashboard for automatic sync

Team and Enterprise hooks have higher priority than user hooks, ensuring policy is enforced even if users have their own hooks.json.

## Limitations

1. **Prompt-only**: Only checks the text prompt, not file attachments or images
2. **No streaming**: Checks happen before submission, not during response streaming
3. **Pattern-based**: Won't catch all PII in all contexts; semantic understanding is limited
4. **English-focused**: Presidio's default models work best on English text
5. **Network dependency**: Requires Presidio to be reachable (unless fail-open)
