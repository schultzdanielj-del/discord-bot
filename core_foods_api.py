"""
Core Foods API client functions for the Discord bot.
Replaces local SQLite calls with API calls to PostgreSQL backend.
"""
import httpx

API_BASE_URL = "https://ttm-metrics-api-production.up.railway.app/api"


async def can_award_core_foods_xp(user_id):
    """Check if user can receive core foods XP today via API"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{API_BASE_URL}/core-foods/{user_id}/can-checkin",
                timeout=10.0
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("can_checkin", False)
            else:
                print(f"Core foods can-checkin API error: {response.status_code}")
    except Exception as e:
        print(f"Error checking core foods eligibility via API: {e}")
    return False


async def record_core_foods_checkin(user_id, message_id, xp_awarded):
    """Record a core foods check-in via API (writes to PostgreSQL)"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{API_BASE_URL}/core-foods",
                params={
                    "user_id": user_id,
                    "message_id": message_id,
                    "xp_awarded": xp_awarded
                },
                timeout=10.0
            )
            if response.status_code == 200:
                print(f"✅ Core foods check-in recorded via API for user {user_id}")
                return True
            else:
                print(f"❌ Core foods API error: {response.status_code} - {response.text}")
                return False
    except Exception as e:
        print(f"❌ Error recording core foods via API: {e}")
        return False


async def get_core_foods_counts(start_iso, end_iso):
    """Get core foods check-in counts per user for a date range via admin SQL endpoint"""
    try:
        async with httpx.AsyncClient() as client:
            query = (
                f"SELECT user_id, COUNT(*) as checkin_count "
                f"FROM core_foods_checkins "
                f"WHERE timestamp >= '{start_iso}' AND timestamp <= '{end_iso}' "
                f"GROUP BY user_id"
            )
            response = await client.get(
                f"{API_BASE_URL}/admin/sql",
                params={
                    "key": "4ifQC_DLzlXM1c5PC6egwvf2p5GgbMR3",
                    "q": query
                },
                timeout=10.0
            )
            if response.status_code == 200:
                data = response.json()
                return {row["user_id"]: row["checkin_count"] for row in data.get("rows", [])}
            else:
                print(f"Core foods summary API error: {response.status_code}")
    except Exception as e:
        print(f"Error fetching core foods summary via API: {e}")
    return {}
