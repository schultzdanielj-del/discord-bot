# TTM Discord Bot

Discord bot for Three Target Method coaching server. Handles PR logging relay, core foods check-ins, coach messaging bridge, and activity reporting.

## Stack

- Python 3.11, discord.py 2.3.2
- Local SQLite (`pr_tracker.db`) for legacy XP/level data
- Calls TTM Metrics API for all persistent data (PRs, core foods, coach messages)
- Flask keep-alive server on port 8080
- Deployed on Railway

## Key Behavior

**PR logging via Discord is disabled** (Feb 24, 2026). All PR logging now goes through the dashboard, which enforces canonical exercise names. The bot still processes PR messages for relay to the API when `DISCORD_PR_LOGGING_ENABLED` is toggled back on.

**Coach message bridge**: When Dan replies to a user's message in the PR channel, the bot forwards it as a coach message via the API. Users receive coach messages in their dashboard.

**Core foods**: Check-ins in the Discord channel are recorded via the API to PostgreSQL.

## Files

| File | Purpose |
|------|---------|
| `PRBot.py` | Main bot: message handling, commands, API relay |
| `exercise_normalization.py` | Canonical exercise name mapping |
| `fuzzy_matching.py` | Parse PR messages from free-text Discord posts |
| `core_foods_api.py` | Async API client for core foods check-ins |
| `pr_tracker.db` | Legacy SQLite DB (XP, levels — mostly unused now) |

## Commands

| Command | Access | Purpose |
|---------|--------|---------|
| `!prcount` | Admin | Total PR count from API |
| `!mylatest` | All | User's recent PRs |
| `!progress` | All | Per-exercise PR history chart |
| `!level` | All | XP level (legacy system) |
| `!leaderboard` | All | XP leaderboard (legacy) |
| `!weekly_content` | All | Weekly activity summary |
| `!monthly_content` | All | Monthly activity summary |
| `!weekly_raw` | All | Raw weekly data export |
| `!monthly_raw` | All | Raw monthly data export |

## API Integration

All data flows through: `https://ttm-metrics-api-production.up.railway.app/api`

Coach endpoints use `X-Admin-Key` header. Core foods and PR endpoints are public (user_id based).

## Development

```bash
pip install -r requirements.txt
python PRBot.py
```

Requires `DISCORD_TOKEN` and `ADMIN_KEY` environment variables.
