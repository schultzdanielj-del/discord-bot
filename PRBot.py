import discord
from discord.ext import commands
import sqlite3
from datetime import datetime, timedelta
import re
import os
import aiohttp
from flask import Flask
from threading import Thread
from rapidfuzz import fuzz, process
import io
import httpx
from exercise_normalization import normalize_exercise_name
from fuzzy_matching import parse_pr_message, get_canonical_with_tiebreaker
from core_foods_api import can_award_core_foods_xp as can_award_core_foods_xp_api, record_core_foods_checkin as record_core_foods_checkin_api, get_core_foods_counts

API_BASE_URL = "https://ttm-metrics-api-production.up.railway.app/api"

# Flask app for keep-alive
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Database setup - local SQLite only for XP/logs (legacy)
DB_NAME = '/data/pr_tracker.db'

# Channel IDs
PR_CHANNEL_ID = '1459000944028028970'
LOGS_CHANNEL_ID = '1450903499075354756'
CORE_FOODS_CHANNEL_ID = '1459000944028028970'

def init_db():
    """Initialize the database with required tables"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Legacy table - no longer written to, but kept for schema compat
    c.execute('''
        CREATE TABLE IF NOT EXISTS prs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            username TEXT NOT NULL,
            exercise TEXT NOT NULL,
            weight REAL NOT NULL,
            reps INTEGER NOT NULL,
            estimated_1rm REAL NOT NULL,
            timestamp TEXT NOT NULL,
            message_id TEXT NOT NULL,
            channel_id TEXT NOT NULL
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_xp (
            user_id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            total_xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            last_updated TEXT NOT NULL
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS weekly_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            message_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            xp_awarded INTEGER NOT NULL
        )
    ''')
    
    # Legacy table - core foods now go to PostgreSQL via API
    c.execute('''
        CREATE TABLE IF NOT EXISTS core_foods_checkins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            date TEXT NOT NULL,
            message_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            xp_awarded INTEGER NOT NULL,
            UNIQUE(user_id, date)
        )
    ''')
    
    conn.commit()
    conn.close()

async def get_user_program_exercises(user_id):
    """
    Fetch user's program exercises from API for fuzzy matching.
    Returns list of canonical exercise names from all workouts (A, B, C, D, E).
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{API_BASE_URL}/workouts/{user_id}",
                timeout=5.0
            )
            if response.status_code == 200:
                workouts = response.json()
                exercises = []
                for workout in workouts.get('workouts', []):
                    for exercise in workout.get('exercises', []):
                        exercises.append(exercise['name'])
                return exercises
    except Exception as e:
        print(f"Could not fetch user program: {e}")
    
    return []


def calculate_1rm(weight, reps):
    """Calculate estimated 1 rep max using Epley formula"""
    return (weight * reps * 0.0333) + weight

def calculate_level(total_xp):
    """Calculate level based on total XP"""
    level = 1
    xp_needed = 500
    while total_xp >= xp_needed:
        total_xp -= xp_needed
        level += 1
        xp_needed = 250 + (level * 250)
    return level

def get_xp_for_next_level(current_level):
    """Get XP needed for next level"""
    return 250 + (current_level * 250)

def add_xp(user_id, username, xp_amount, reason=""):
    """Add XP to a user and check for level up"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT total_xp, level FROM user_xp WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    if result:
        old_xp, old_level = result
        new_xp = old_xp + xp_amount
    else:
        old_xp, old_level = 0, 1
        new_xp = xp_amount
    new_level = calculate_level(new_xp)
    timestamp = datetime.utcnow().isoformat()
    c.execute('''
        INSERT OR REPLACE INTO user_xp (user_id, username, total_xp, level, last_updated)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, username, new_xp, new_level, timestamp))
    conn.commit()
    conn.close()
    leveled_up = new_level > old_level
    return new_xp, new_level, leveled_up, old_level

def get_user_xp_info(user_id):
    """Get user's XP and level information"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT total_xp, level FROM user_xp WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    conn.close()
    if result:
        return result[0], result[1]
    return 0, 1

def can_award_weekly_log_xp(user_id):
    """Check if user can receive weekly log XP"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT timestamp FROM weekly_logs WHERE user_id = ? ORDER BY timestamp DESC LIMIT 1', (user_id,))
    result = c.fetchone()
    conn.close()
    if not result:
        return True
    last_log_time = datetime.fromisoformat(result[0])
    time_since_last = datetime.utcnow() - last_log_time
    return time_since_last.days >= 6

def record_weekly_log(user_id, message_id, xp_awarded):
    """Record a weekly log submission"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    timestamp = datetime.utcnow().isoformat()
    c.execute('INSERT INTO weekly_logs (user_id, message_id, timestamp, xp_awarded) VALUES (?, ?, ?, ?)',
              (user_id, message_id, timestamp, xp_awarded))
    conn.commit()
    conn.close()

# Legacy SQLite functions kept for dump_core_foods command only
def can_award_core_foods_xp_legacy(user_id):
    """LEGACY - Check core foods in SQLite. Only used by dump_core_foods."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    today = datetime.utcnow().date().isoformat()
    c.execute('SELECT id FROM core_foods_checkins WHERE user_id = ? AND date = ?', (user_id, today))
    result = c.fetchone()
    conn.close()
    return result is None

def record_core_foods_checkin_legacy(user_id, message_id, xp_awarded):
    """LEGACY - Record core foods in SQLite. Only used by dump_core_foods."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    today = datetime.utcnow().date().isoformat()
    timestamp = datetime.utcnow().isoformat()
    try:
        c.execute('INSERT INTO core_foods_checkins (user_id, date, message_id, timestamp, xp_awarded) VALUES (?, ?, ?, ?, ?)',
                  (user_id, today, message_id, timestamp, xp_awarded))
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        success = False
    conn.close()
    return success

async def store_pr(user_id, username, exercise, weight, reps, estimated_1rm, message_id, channel_id):
    """Store a PR entry via API"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{API_BASE_URL}/prs",
                json={"user_id": user_id, "username": username, "exercise": exercise, "weight": weight, "reps": reps},
                timeout=10.0
            )
            response.raise_for_status()
            print(f'✅ Logged PR to API: {username} - {exercise} {weight}/{reps}')
            return True
        except Exception as e:
            print(f'❌ API error storing PR: {e}')
            if hasattr(e, 'response'):
                print(f'Response body: {e.response.text}')
            return False

async def delete_prs_by_message_api(message_id):
    """Delete all PR entries associated with a message ID via API"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.delete(f"{API_BASE_URL}/prs/message/{message_id}", timeout=10.0)
            response.raise_for_status()
            data = response.json()
            deleted_count = data.get("deleted_count", 0)
            print(f'🗑️ API deleted {deleted_count} PR(s) for message {message_id}')
            return deleted_count
        except Exception as e:
            print(f'❌ API error deleting PRs for message {message_id}: {e}')
            return 0

@bot.event
async def on_ready():
    """Called when the bot is ready"""
    print(f'{bot.user} has connected to Discord!')
    print(f'Monitoring channels for PR entries...')
    print(f'✅ Using NEW normalization and fuzzy matching')
    print(f'✅ All commands use API (PostgreSQL)')
    print(f'✅ Core foods check-ins use API (PostgreSQL)')
    init_db()

@bot.event
async def on_message(message):
    """Monitor all messages in the specified channels"""
    if message.author.bot:
        return
    channel_id = str(message.channel.id)

    # Coach messaging: detect replies to bot messages in #pr-city
    if channel_id == PR_CHANNEL_ID and message.reference and message.reference.message_id:
        try:
            replied_to = await message.channel.fetch_message(message.reference.message_id)
            if replied_to.author.bot and replied_to.author.id == bot.user.id:
                # This is a reply to our bot's message — treat as coach message
                # Parse display name from the bot message (first word(s) before a verb/keyword)
                bot_content = replied_to.content
                # Bot messages follow patterns like "{name} ate their core foods..."
                # or "{name} just beat their last personal best..."
                target_user_id = None
                async with httpx.AsyncClient() as client:
                    try:
                        resp = await client.get(f"{API_BASE_URL}/dashboard/members", timeout=10.0)
                        if resp.status_code == 200:
                            members = resp.json()
                            for m in members:
                                uname = m.get("username", "")
                                if uname and bot_content.startswith(uname):
                                    target_user_id = m.get("user_id")
                                    break
                    except Exception as e:
                        print(f"❌ Error fetching members for coach msg: {e}")

                if target_user_id:
                    async with httpx.AsyncClient() as client:
                        try:
                            await client.post(
                                f"{API_BASE_URL}/coach-messages",
                                json={
                                    "user_id": target_user_id,
                                    "message_text": message.content,
                                    "discord_msg_id": str(message.id),
                                },
                                headers={"X-Admin-Key": os.environ.get("ADMIN_KEY", "4ifQC_DLzlXM1c5PC6egwvf2p5GgbMR3")},
                                timeout=10.0,
                            )
                            await message.add_reaction("✉️")
                            print(f"✉️ Coach message stored for user {target_user_id}: {message.content[:50]}")
                        except Exception as e:
                            print(f"❌ Error storing coach message: {e}")
                else:
                    print(f"⚠️ Could not identify user from bot message: {bot_content[:60]}")
        except Exception as e:
            print(f"❌ Error processing coach reply: {e}")
    if channel_id == PR_CHANNEL_ID:
        if message.content.strip().startswith('*'):
            await bot.process_commands(message)
            return
        content_lower = message.content.lower()
        core_foods_keywords = ['core foods', 'core', 'food', 'ate', 'eating', 'meal', 'diet', 'nutrition', 'check in', 'checkin']
        is_core_foods = any(keyword in content_lower for keyword in core_foods_keywords)
        if is_core_foods:
            # Use API for core foods check-ins (PostgreSQL)
            if await can_award_core_foods_xp_api(str(message.author.id)):
                xp_earned = 200
                add_xp(str(message.author.id), message.author.name, xp_earned, "Core foods check-in")
                success = await record_core_foods_checkin_api(str(message.author.id), str(message.id), xp_earned)
                if success:
                    await message.add_reaction('🍎')
                    await message.add_reaction('✅')
            else:
                await message.add_reaction('✅')
        else:
            program_exercises = await get_user_program_exercises(str(message.author.id))
            pr_data = parse_pr_message(message.content, program_exercises)
            if pr_data:
                success = await store_pr(
                    str(message.author.id), message.author.name,
                    pr_data['canonical_exercise'], pr_data['weight'],
                    pr_data['reps'], pr_data['estimated_1rm'],
                    str(message.id), str(message.channel.id)
                )
                if success:
                    xp_earned = 100
                    add_xp(str(message.author.id), message.author.name, xp_earned, "PR logged")
                    await message.add_reaction('💪')
                    fuzzy_note = " (fuzzy matched)" if pr_data['used_fuzzy'] else ""
                    print(f'Logged PR: {message.author.name} - {pr_data["canonical_exercise"]} '
                          f'{pr_data["weight"]}/{pr_data["reps"]} '
                          f'(Est. 1RM: {pr_data["estimated_1rm"]:.1f}){fuzzy_note}')
    elif channel_id == LOGS_CHANNEL_ID:
        if len(message.content) >= 300:
            if can_award_weekly_log_xp(str(message.author.id)):
                xp_earned = 800
                if message.attachments:
                    xp_earned += 50
                add_xp(str(message.author.id), message.author.name, xp_earned, "Weekly log")
                record_weekly_log(str(message.author.id), str(message.id), xp_earned)
                await message.add_reaction('📝')
                await message.add_reaction('✅')
            else:
                await message.add_reaction('⏰')
    await bot.process_commands(message)

@bot.event
async def on_raw_message_edit(payload: discord.RawMessageUpdateEvent):
    """Handle edited messages in the PR channel — uses raw event to work regardless of cache"""
    # payload.data is the raw gateway dict; channel_id is always present
    channel_id = str(payload.channel_id)
    if channel_id != PR_CHANNEL_ID:
        return

    # Fetch the full message (not from cache)
    try:
        channel = bot.get_channel(payload.channel_id)
        if not channel:
            channel = await bot.fetch_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)
    except Exception as e:
        print(f"⚠️ Could not fetch edited message {payload.message_id}: {e}")
        return

    if message.author.bot:
        return

    # Coach message edit: if this is a reply to a bot message, update the coach message
    if message.reference and message.reference.message_id:
        try:
            replied_to = await channel.fetch_message(message.reference.message_id)
            if replied_to.author.bot and replied_to.author.id == bot.user.id:
                async with httpx.AsyncClient() as client:
                    try:
                        resp = await client.put(
                            f"{API_BASE_URL}/coach-messages/{message.id}",
                            json={"message_text": message.content},
                            headers={"X-Admin-Key": os.environ.get("ADMIN_KEY", "4ifQC_DLzlXM1c5PC6egwvf2p5GgbMR3")},
                            timeout=10.0,
                        )
                        if resp.status_code == 200:
                            await message.add_reaction("✏️")
                            print(f"✏️ Coach message updated for discord_msg_id {message.id}: {message.content[:50]}")
                        else:
                            print(f"⚠️ Coach message update returned {resp.status_code}: {resp.text}")
                    except Exception as e:
                        print(f"❌ Error updating coach message: {e}")
                return  # Don't process as PR edit
        except Exception:
            pass

    if message.content.strip().startswith('*'):
        return
    deleted_count = await delete_prs_by_message_api(str(message.id))
    program_exercises = await get_user_program_exercises(str(message.author.id))
    pr_data = parse_pr_message(message.content, program_exercises)
    if pr_data:
        success = await store_pr(
            str(message.author.id), message.author.name,
            pr_data['canonical_exercise'], pr_data['weight'],
            pr_data['reps'], pr_data['estimated_1rm'],
            str(message.id), str(message.channel.id)
        )
        if success:
            await message.add_reaction('🔄')
            fuzzy_note = " (fuzzy matched)" if pr_data['used_fuzzy'] else ""
            print(f'Updated PR: {message.author.name} - {pr_data["canonical_exercise"]} '
                  f'{pr_data["weight"]}/{pr_data["reps"]}{fuzzy_note}')
            if deleted_count > 0:
                print(f'Replaced {deleted_count} old PR(s) with new data for message {message.id}')
    else:
        if deleted_count > 0:
            await message.add_reaction('❌')
            print(f'Removed {deleted_count} PR(s) from edited message {message.id} (no longer valid)')

@bot.event
async def on_raw_message_delete(payload):
    """Handle deleted messages - remove associated PRs via API"""
    if str(payload.channel_id) != PR_CHANNEL_ID:
        return
    deleted_count = await delete_prs_by_message_api(str(payload.message_id))
    if deleted_count > 0:
        print(f'🗑️ Deleted {deleted_count} PR(s) from deleted message {payload.message_id}')

@bot.command()
@commands.has_permissions(administrator=True)
async def prcount(ctx):
    """Check total number of PRs stored (via API)"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{API_BASE_URL}/prs/count", timeout=10.0)
            response.raise_for_status()
            data = response.json()
            await ctx.send(f'Total PRs stored: {data["total_prs"]}')
    except Exception as e:
        await ctx.send(f"❌ Error fetching PR count: {e}")

@bot.command()
async def mylatest(ctx):
    """Check your 5 most recent PRs (via API)"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{API_BASE_URL}/prs/{ctx.author.id}/latest?limit=5", timeout=10.0)
            response.raise_for_status()
            records = response.json()
        if records:
            response_text = "**Your latest PRs:**\n"
            for pr in records:
                ts = pr.get('timestamp', '')
                date = ts[:10] if ts else 'Unknown'
                response_text += f"• {pr['exercise']}: {pr['weight']}/{pr['reps']} (Est. 1RM: {pr['estimated_1rm']:.1f}) - {date}\n"
            await ctx.send(response_text)
        else:
            await ctx.send("No PRs found for you yet!")
    except Exception as e:
        await ctx.send(f"❌ Error fetching latest PRs: {e}")

@bot.command(name='progress')
async def progress_command(ctx):
    """Shows progress for each exercise (minimum PR vs maximum PR)"""
    user_id = str(ctx.author.id)
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f'{API_BASE_URL}/prs/{user_id}', timeout=10.0)
            if response.status_code != 200:
                await ctx.send(f"❌ Error fetching PRs: {response.status_code}")
                return
            prs = response.json()
        if not prs:
            await ctx.send("No PRs found! Post your first PR to get started. 💪")
            return
        exercise_prs = {}
        for pr in prs:
            exercise = pr['exercise']
            if exercise not in exercise_prs:
                exercise_prs[exercise] = []
            exercise_prs[exercise].append(pr)
        lines = [f"**Progress Report for {ctx.author.display_name}**\n"]
        for exercise in sorted(exercise_prs.keys()):
            prs_list = exercise_prs[exercise]
            is_bodyweight = all(pr['weight'] == 0 for pr in prs_list)
            if is_bodyweight:
                min_pr = min(prs_list, key=lambda x: x['reps'])
                max_pr = max(prs_list, key=lambda x: x['reps'])
                min_reps = min_pr['reps']
                max_reps = max_pr['reps']
                if min_reps != max_reps and min_reps > 0:
                    rep_gain = max_reps - min_reps
                    pct_gain = ((max_reps - min_reps) / min_reps) * 100
                    lines.append(f"**{exercise}**: {min_reps} reps → {max_reps} reps ({rep_gain:+.0f} reps, {pct_gain:+.1f}%)")
                else:
                    lines.append(f"**{exercise}**: {max_reps} reps")
            else:
                min_pr = min(prs_list, key=lambda x: x['estimated_1rm'])
                max_pr = max(prs_list, key=lambda x: x['estimated_1rm'])
                min_1rm = min_pr['estimated_1rm']
                max_1rm = max_pr['estimated_1rm']
                if min_1rm != max_1rm and min_1rm > 0:
                    rm_gain = max_1rm - min_1rm
                    pct_gain = ((max_1rm - min_1rm) / min_1rm) * 100
                    lines.append(f"**{exercise}**: {min_1rm:.0f}lb e1RM → {max_1rm:.0f}lb e1RM ({rm_gain:+.0f}lb, {pct_gain:+.1f}%)")
                else:
                    lines.append(f"**{exercise}**: {max_1rm:.0f}lb e1RM")
            lines.append(f"  └ {len(prs_list)} total PRs\n")
        msg_text = "\n".join(lines)
        if len(msg_text) <= 2000:
            await ctx.send(msg_text)
        else:
            chunks = []
            current_chunk = lines[0] + "\n"
            for line in lines[1:]:
                if len(current_chunk) + len(line) + 1 <= 1900:
                    current_chunk += line + "\n"
                else:
                    chunks.append(current_chunk)
                    current_chunk = line + "\n"
            chunks.append(current_chunk)
            for chunk in chunks:
                await ctx.send(chunk)
    except Exception as e:
        await ctx.send(f"❌ Error generating progress report: {str(e)}")
        print(f"Progress command error: {e}")
        import traceback
        traceback.print_exc()

@bot.command()
async def level(ctx):
    """Check your current level and XP"""
    total_xp, level_val = get_user_xp_info(str(ctx.author.id))
    xp_for_current = 0
    for i in range(1, level_val):
        xp_for_current += 250 + (i * 250)
    xp_in_level = total_xp - xp_for_current
    xp_needed_for_next = get_xp_for_next_level(level_val)
    progress_pct = (xp_in_level / xp_needed_for_next) * 100
    bar_length = 20
    filled = int((progress_pct / 100) * bar_length)
    bar = '█' * filled + '░' * (bar_length - filled)
    pr_count = 0
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{API_BASE_URL}/prs/{ctx.author.id}/count", timeout=10.0)
            if response.status_code == 200:
                pr_count = response.json().get("pr_count", 0)
    except Exception as e:
        print(f"Error fetching PR count for level command: {e}")
    response = f"⚔️ **Level {level_val}**\n\n"
    response += f"**XP:** {xp_in_level:,} / {xp_needed_for_next:,} ({progress_pct:.1f}%)\n"
    response += f"[{bar}]\n\n"
    response += f"**Total XP:** {total_xp:,}\n"
    response += f"**Lifetime PRs:** {pr_count}\n"
    response += f"**Next Level:** {level_val + 1} (need {xp_needed_for_next - xp_in_level:,} more XP)\n"
    await ctx.send(response)

@bot.command()
async def leaderboard(ctx, board_type: str = "level"):
    """Show leaderboards"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if board_type.lower() == "level":
        c.execute('SELECT username, level, total_xp FROM user_xp ORDER BY level DESC, total_xp DESC LIMIT 10')
        title = "🏆 Top 10 Levels"
    else:
        c.execute('SELECT username, total_xp, level FROM user_xp ORDER BY total_xp DESC LIMIT 10')
        title = "🏆 Top 10 Total XP"
    results = c.fetchall()
    conn.close()
    if not results:
        await ctx.send("No one has earned XP yet!")
        return
    response = f"**{title}**\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, (username, primary, secondary) in enumerate(results, 1):
        medal = medals[i-1] if i <= 3 else f"#{i}"
        if board_type.lower() == "level":
            response += f"{medal} **{username}** - Level {primary} ({secondary:,} XP)\n"
        else:
            response += f"{medal} **{username}** - {primary:,} XP (Level {secondary})\n"
    await ctx.send(response)

@bot.command()
async def weekly_content(ctx):
    """Generate weekly content summary for social media"""
    await _generate_content_summary(ctx, days=7, period_name="Week")

@bot.command()
async def monthly_content(ctx):
    """Generate monthly content summary for social media"""
    await _generate_content_summary(ctx, days=30, period_name="Month")

async def _generate_content_summary(ctx, days, period_name):
    """Generate content summary - uses API for PRs and core foods, local for XP/logs"""
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    start_iso = start_date.isoformat()
    end_iso = end_date.isoformat()
    all_prs_raw = []
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{API_BASE_URL}/prs?limit=5000", timeout=15.0)
            if response.status_code == 200:
                for pr in response.json():
                    ts = pr.get('timestamp', '')
                    if ts and ts >= start_iso and ts <= end_iso:
                        all_prs_raw.append(pr)
    except Exception as e:
        await ctx.send(f"❌ Error fetching PR data from API: {e}")
        return
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT user_id, COUNT(*) as log_count FROM weekly_logs WHERE timestamp >= ? AND timestamp <= ? GROUP BY user_id', (start_iso, end_iso))
    weekly_logs = dict(c.fetchall())
    c.execute('SELECT user_id, username, total_xp, level FROM user_xp ORDER BY level DESC')
    all_users = c.fetchall()
    conn.close()
    # Get core foods from API (PostgreSQL)
    core_foods = await get_core_foods_counts(start_iso, end_iso)
    if not all_prs_raw and not weekly_logs and not core_foods:
        await ctx.send(f"No activity found in the past {days} days!")
        return
    user_prs = {}
    total_pr_count = 0
    exercise_prs = {}
    for pr in all_prs_raw:
        user_id = pr.get('user_id', '')
        username = pr.get('username', 'Unknown')
        exercise = pr.get('exercise', '')
        if user_id not in user_prs:
            user_prs[user_id] = {'username': username, 'prs': [], 'pr_count': 0}
        user_prs[user_id]['prs'].append({'exercise': exercise, 'weight': pr.get('weight', 0), 'reps': pr.get('reps', 0), 'est_1rm': pr.get('estimated_1rm', 0), 'timestamp': pr.get('timestamp', '')})
        user_prs[user_id]['pr_count'] += 1
        total_pr_count += 1
        exercise_prs[exercise] = exercise_prs.get(exercise, 0) + 1
    standout_moments = []
    for user_id, data in user_prs.items():
        consecutive_days = {}
        for pr in data['prs']:
            day = pr['timestamp'][:10]
            consecutive_days[day] = consecutive_days.get(day, 0) + 1
        if consecutive_days:
            max_in_day = max(consecutive_days.values())
            if max_in_day >= 5:
                standout_moments.append(f"{data['username']} hit {max_in_day} PRs in a single day")
        exercise_progress = {}
        for pr in sorted(data['prs'], key=lambda x: x['timestamp']):
            ex = pr['exercise']
            if ex not in exercise_progress:
                exercise_progress[ex] = {'first': pr['est_1rm'], 'last': pr['est_1rm']}
            else:
                exercise_progress[ex]['last'] = pr['est_1rm']
        for ex, progress in exercise_progress.items():
            improvement = progress['last'] - progress['first']
            if improvement >= 20:
                standout_moments.append(f"{data['username']} added +{improvement:.0f}lbs to {ex}")
    top_users = sorted(user_prs.items(), key=lambda x: x[1]['pr_count'], reverse=True)[:5]
    active_members = len(user_prs)
    total_members = len(all_users)
    summary = f"📊 **{period_name.upper()} SUMMARY ({start_date.strftime('%b %d')} - {end_date.strftime('%b %d')})**\n\n"
    summary += f"👥 **ACTIVE MEMBERS:** {active_members}/{total_members} ({(active_members/max(total_members,1)*100):.0f}%)\n\n"
    summary += f"💪 **PRS THIS {period_name.upper()}:** {total_pr_count} total\n"
    for user_id, data in top_users:
        pr_samples = ", ".join([f"{pr['exercise']} +{pr['weight']:.0f}lbs" for pr in data['prs'][:3]])
        summary += f"- {data['username']}: {data['pr_count']} PRs ({pr_samples}...)\n"
    summary += f"\n📝 **WEEKLY LOGS:** {sum(weekly_logs.values())} submitted\n"
    if weekly_logs:
        for user_id, count in sorted(weekly_logs.items(), key=lambda x: x[1], reverse=True):
            username = user_prs.get(user_id, {}).get('username', 'Unknown')
            summary += f"- {username}: {count} log(s)\n"
    summary += f"\n🍽️ **CORE FOODS CHECK-INS:**\n"
    if core_foods:
        for user_id, count in sorted(core_foods.items(), key=lambda x: x[1], reverse=True):
            username = user_prs.get(user_id, {}).get('username', 'Unknown')
            summary += f"- {username}: {count}/{days} days ({(count/days*100):.0f}%)\n"
    else:
        summary += "- No check-ins this period\n"
    summary += f"\n🏆 **TOP XP EARNERS (ESTIMATED):**\n"
    for i, (user_id, data) in enumerate(top_users, 1):
        est_xp = (data['pr_count'] * 100) + (weekly_logs.get(user_id, 0) * 800) + (core_foods.get(user_id, 0) * 200)
        summary += f"{i}. {data['username']}: ~{est_xp:,} XP\n"
    if standout_moments:
        summary += f"\n🔥 **STANDOUT MOMENTS:**\n"
        for moment in standout_moments[:5]:
            summary += f"- {moment}\n"
    if exercise_prs:
        top_exercises = sorted(exercise_prs.items(), key=lambda x: x[1], reverse=True)[:5]
        summary += f"\n💥 **MOST POPULAR EXERCISES:**\n"
        for exercise, count in top_exercises:
            summary += f"- {exercise}: {count} PRs\n"
    summary += f"\n---\n\n**PASTE THIS INTO CLAUDE WITH YOUR CONTENT GENERATION PROMPT**\n"
    try:
        await ctx.author.send(summary)
        await ctx.send("✅ Content summary sent to your DMs!")
    except discord.Forbidden:
        await ctx.send(summary)

@bot.command()
async def weekly_raw(ctx):
    """Export ALL raw Discord activity from past 7 days"""
    await _export_raw_activity(ctx, days=7, period_name="Week")

@bot.command()
async def monthly_raw(ctx):
    """Export ALL raw Discord activity from past 30 days"""
    await _export_raw_activity(ctx, days=30, period_name="Month")

async def _export_raw_activity(ctx, days, period_name):
    """Export complete raw Discord activity for Claude to analyze"""
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    pr_channel = bot.get_channel(int(PR_CHANNEL_ID))
    logs_channel = bot.get_channel(int(LOGS_CHANNEL_ID))
    general_channel = None
    for channel in ctx.guild.text_channels:
        if 'general' in channel.name.lower():
            general_channel = channel
            break
    output = f"📊 **COMPLETE RAW ACTIVITY EXPORT - PAST {days} DAYS**\n"
    output += f"**Period:** {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}\n"
    output += "=" * 80 + "\n\n"
    if pr_channel:
        output += f"🏋️ **#PRS CHANNEL - ALL MESSAGES**\n" + "=" * 80 + "\n\n"
        pr_messages = []
        async for message in pr_channel.history(limit=500, after=start_date):
            if not message.author.bot:
                pr_messages.append(message)
        pr_messages.reverse()
        for msg in pr_messages:
            output += f"[{msg.created_at.strftime('%Y-%m-%d %H:%M')}] {msg.author.name}:\n{msg.content}\n"
            if msg.reactions:
                output += f"Reactions: {' '.join([f'{r.emoji}x{r.count}' for r in msg.reactions])}\n"
            output += "\n"
        output += f"\nTotal PR channel messages: {len(pr_messages)}\n\n"
    if logs_channel:
        output += f"📝 **#WEEKLY-LOGS CHANNEL - ALL MESSAGES**\n" + "=" * 80 + "\n\n"
        log_messages = []
        async for message in logs_channel.history(limit=200, after=start_date):
            if not message.author.bot:
                log_messages.append(message)
        log_messages.reverse()
        for msg in log_messages:
            output += f"[{msg.created_at.strftime('%Y-%m-%d %H:%M')}] {msg.author.name}:\n{msg.content}\n"
            if msg.attachments:
                output += f"Attachments: {len(msg.attachments)} file(s)\n"
            if msg.reactions:
                output += f"Reactions: {' '.join([f'{r.emoji}x{r.count}' for r in msg.reactions])}\n"
            output += "\n"
        output += f"\nTotal weekly log messages: {len(log_messages)}\n\n"
    if general_channel:
        output += f"💬 **#GENERAL CHANNEL - ALL MESSAGES**\n" + "=" * 80 + "\n\n"
        general_messages = []
        async for message in general_channel.history(limit=500, after=start_date):
            if not message.author.bot:
                general_messages.append(message)
        general_messages.reverse()
        for msg in general_messages:
            output += f"[{msg.created_at.strftime('%Y-%m-%d %H:%M')}] {msg.author.name}:\n{msg.content}\n"
            if msg.reactions:
                output += f"Reactions: {' '.join([f'{r.emoji}x{r.count}' for r in msg.reactions])}\n"
            output += "\n"
        output += f"\nTotal general messages: {len(general_messages)}\n\n"
    output += f"📈 **DATABASE STATISTICS**\n" + "=" * 80 + "\n\n"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{API_BASE_URL}/prs/count", timeout=10.0)
            total_prs = resp.json().get("total_prs", 0) if resp.status_code == 200 else 0
            resp = await client.get(f"{API_BASE_URL}/prs?limit=5000", timeout=15.0)
            if resp.status_code == 200:
                all_prs = resp.json()
                period_prs = [p for p in all_prs if p.get('timestamp', '') >= start_date.isoformat()]
                unique_users = len(set(p.get('user_id', '') for p in period_prs))
                unique_exercises = len(set(p.get('exercise', '') for p in period_prs))
            else:
                period_prs, unique_users, unique_exercises = [], 0, 0
        output += f"Total PRs in database: {total_prs}\nPRs this period: {len(period_prs)}\nUnique members with PRs: {unique_users}\nUnique exercises: {unique_exercises}\n\n"
    except Exception as e:
        output += f"Error fetching API stats: {e}\n\n"
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT username, total_xp, level FROM user_xp ORDER BY total_xp DESC')
    xp_stats = c.fetchall()
    conn.close()
    output += f"**Current XP Leaderboard:**\n"
    for username, xp, lvl in xp_stats:
        output += f"- {username}: Level {lvl} ({xp:,} XP)\n"
    output += "\n" + "=" * 80 + "\n**END OF RAW DATA EXPORT**\n"
    output += f"Total characters: {len(output):,}\n"
    file = discord.File(io.BytesIO(output.encode('utf-8')), filename=f'discord_raw_export_{period_name.lower()}.txt')
    try:
        await ctx.author.send(file=file)
        await ctx.send("✅ Raw data export sent to your DMs as a file!")
    except discord.Forbidden:
        await ctx.send(file=file)

@bot.command()
@commands.has_permissions(administrator=True)
async def export_data(ctx):
    """Export all database data as JSON for migration (PRs from API, XP from local)"""
    import json
    prs = []
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{API_BASE_URL}/prs?limit=10000", timeout=15.0)
            if response.status_code == 200:
                for pr in response.json():
                    prs.append({"user_id": pr.get("user_id", ""), "username": pr.get("username", ""), "exercise": pr.get("exercise", ""), "weight": pr.get("weight", 0), "reps": pr.get("reps", 0), "estimated_1rm": pr.get("estimated_1rm", 0), "timestamp": pr.get("timestamp", "")})
    except Exception as e:
        await ctx.send(f"⚠️ Error fetching PRs from API: {e}")
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT user_id, username, total_xp, level FROM user_xp')
    xp = [{"user_id": r[0], "username": r[1], "total_xp": r[2], "level": r[3]} for r in c.fetchall()]
    conn.close()
    data = {"prs": prs, "xp": xp}
    file_content = json.dumps(data, indent=2)
    file = discord.File(io.BytesIO(file_content.encode('utf-8')), filename='ttm_data_export.json')
    await ctx.author.send(f"Exported {len(prs)} PRs (from API) and {len(xp)} XP records (from local)")
    await ctx.author.send(file=file)
    await ctx.send("✅ Data exported to your DMs!")

@bot.command()
@commands.has_permissions(administrator=True)
async def dump_core_foods(ctx):
    """Dump all core_foods_checkins from local SQLite as JSON (legacy data)"""
    import json
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT id, user_id, date, message_id, timestamp, xp_awarded FROM core_foods_checkins ORDER BY timestamp')
    rows = c.fetchall()
    c.execute('SELECT user_id, COUNT(*) FROM core_foods_checkins GROUP BY user_id')
    user_counts = c.fetchall()
    c.execute('SELECT MIN(date), MAX(date) FROM core_foods_checkins')
    date_range = c.fetchone()
    conn.close()
    records = [{"id": r[0], "user_id": r[1], "date": r[2], "message_id": r[3], "timestamp": r[4], "xp_awarded": r[5]} for r in rows]
    data = {"total_records": len(records), "date_range": {"earliest": date_range[0], "latest": date_range[1]} if date_range[0] else None, "per_user": {uid: count for uid, count in user_counts}, "records": records}
    file_content = json.dumps(data, indent=2)
    file = discord.File(io.BytesIO(file_content.encode('utf-8')), filename='core_foods_dump.json')
    summary = f"🍎 **Core Foods Dump (Legacy SQLite)**\nTotal records: {len(records)}\n"
    if date_range[0]:
        summary += f"Date range: {date_range[0]} to {date_range[1]}\n"
    summary += f"\n**Per user:**\n"
    for uid, count in user_counts:
        summary += f"- {uid}: {count} check-ins\n"
    await ctx.author.send(summary)
    await ctx.author.send(file=file)
    await ctx.send("✅ Core foods dump sent to your DMs!")

if __name__ == '__main__':
    TOKEN = os.getenv('DISCORD_BOT_TOKEN')
    if not TOKEN:
        print("Error: DISCORD_BOT_TOKEN environment variable not set!")
        print("Set it with: set DISCORD_TOKEN=your_token_here")
    else:
        keep_alive()
        bot.run(TOKEN)
