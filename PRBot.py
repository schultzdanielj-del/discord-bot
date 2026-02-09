import discord
from discord.ext import commands
import sqlite3
from datetime import datetime, timedelta
import re
import os
from flask import Flask
from threading import Thread
from rapidfuzz import fuzz, process
import io
import httpx

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

# Database setup
DB_NAME = '/data/pr_tracker.db'

# Channel IDs
PR_CHANNEL_ID = '1459000944028028970'
LOGS_CHANNEL_ID = '1450903499075354756'
CORE_FOODS_CHANNEL_ID = '1459000944028028970'

def init_db():
    """Initialize the database with required tables"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
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
    
    c.execute('''
        SELECT timestamp FROM weekly_logs 
        WHERE user_id = ? 
        ORDER BY timestamp DESC 
        LIMIT 1
    ''', (user_id,))
    
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
    c.execute('''
        INSERT INTO weekly_logs (user_id, message_id, timestamp, xp_awarded)
        VALUES (?, ?, ?, ?)
    ''', (user_id, message_id, timestamp, xp_awarded))
    
    conn.commit()
    conn.close()

def can_award_core_foods_xp(user_id):
    """Check if user can receive core foods XP today"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    today = datetime.utcnow().date().isoformat()
    
    c.execute('''
        SELECT id FROM core_foods_checkins 
        WHERE user_id = ? AND date = ?
    ''', (user_id, today))
    
    result = c.fetchone()
    conn.close()
    
    return result is None

def record_core_foods_checkin(user_id, message_id, xp_awarded):
    """Record a core foods check-in"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    today = datetime.utcnow().date().isoformat()
    timestamp = datetime.utcnow().isoformat()
    
    try:
        c.execute('''
            INSERT INTO core_foods_checkins (user_id, date, message_id, timestamp, xp_awarded)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, today, message_id, timestamp, xp_awarded))
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        success = False
    
    conn.close()
    return success

def normalize_exercise_name(exercise):
    """Normalize exercise names to standardize variations"""
    exercise = exercise.lower().strip()
    
    words = exercise.split()
    normalized_words = []
    
    for word in words:
        if len(word) > 2 and word.endswith('s') and not word.endswith('ss'):
            normalized_words.append(word[:-1])
        else:
            normalized_words.append(word)
    
    exercise = ' '.join(normalized_words)
    
    exercise = re.sub(r'\b(1|one|single)\s+arm\b', 'single arm', exercise)
    exercise = re.sub(r'\b(uh|underhand\s+grip)\b', 'underhand', exercise)
    exercise = re.sub(r'\bdb\b', 'dumbbell', exercise)
    exercise = re.sub(r'\bbb\b', 'barbell', exercise)
    exercise = re.sub(r'\bflye?\b', 'fly', exercise)
    exercise = re.sub(r'\blateral\b', 'lateral raise', exercise)
    exercise = re.sub(r'\brdf\b', 'rear delt fly', exercise)
    exercise = re.sub(r'\bsupp\b', 'supported', exercise)
    
    if 'extension' in exercise:
        if not re.search(r'\b(leg|back|reverse|hyper|hip)\s+extension', exercise):
            exercise = re.sub(r'\bextension\b', 'tricep extension', exercise)
    
    exercise = re.sub(r'\s+', ' ', exercise).strip()
    
    return exercise

def parse_single_pr(text):
    """Parse a single PR from text"""
    text = text.strip().lower()
    
    if not text:
        return None
    
    text = re.sub(r'\bbw\b', '0', text, flags=re.IGNORECASE)
    text = re.sub(r'\bbodyweight\b', '0', text, flags=re.IGNORECASE)
    
    text = re.sub(r'\b(pr|new pr|hit|got|did|at|for|with|just|finally|crushed)\b', ' ', text)
    text = re.sub(r'\b(reps?|rep|repetitions?)\b', '', text)
    text = re.sub(r'\b(lbs?|pounds?|kgs?|kilos?)\b', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    
    p1 = r'^(\w+)\s+([\d.]+)\s*[/*x]\s*(\d+)$'
    p2 = r'^(.+?)\s+([\d.]+)\s*[/*x]\s*(\d+)$'
    p3 = r'^(.+?)\s+([\d.]+)\s*-\s*(\d+)$'
    p4 = r'^(\d+)\s*[x]\s*([\d.]+)\s+(.+)$'
    p5 = r'^(.+?):\s*([\d.]+)\s*[/*x]\s*(\d+)$'
    p6 = r'^(.+?)\s+([\d.]+)\s+(\d+)$'
    
    all_patterns = [p1, p2, p3, p4, p5, p6]
    
    for idx, pattern in enumerate(all_patterns):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            groups = match.groups()
            
            if idx == 3:
                reps = int(groups[0])
                weight = float(groups[1])
                exercise = groups[2].strip()
            else:
                exercise = groups[0].strip()
                weight = float(groups[1])
                reps = int(groups[2])
            
            exercise = re.sub(r'[^\w\s]', '', exercise)
            exercise = re.sub(r'\s+', ' ', exercise).strip()
            exercise = normalize_exercise_name(exercise)
            
            if exercise and weight >= 0 and reps > 0 and reps < 1000:
                return (exercise, weight, reps)
    
    return None

def parse_all_prs(message_content):
    """Parse multiple PR entries from a single message"""
    prs = []
    text = message_content.strip()
    lines = text.split('\n')
    
    for line in lines:
        parsed = parse_single_pr(line)
        if parsed:
            prs.append(parsed)
    
    if not prs:
        parsed = parse_single_pr(text)
        if parsed:
            prs.append(parsed)
    
    return prs

def get_canonical_exercise_name(exercise):
    """Match exercise name to existing exercises using fuzzy matching"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute('''
        SELECT exercise, COUNT(*) as count 
        FROM prs 
        GROUP BY exercise 
        ORDER BY count DESC
    ''')
    
    existing_exercises = c.fetchall()
    conn.close()
    
    if not existing_exercises:
        return exercise
    
    exercise_names = [ex[0] for ex in existing_exercises]
    
    best_match = process.extractOne(exercise, exercise_names, scorer=fuzz.ratio)
    
    if best_match and best_match[1] >= 85:
        return best_match[0]
    
    return exercise
 
async def store_pr(user_id, username, exercise, weight, reps, estimated_1rm, message_id, channel_id):
    """Store a PR entry via API"""
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{API_BASE_URL}/prs",
                json={
                    "user_id": user_id,
                    "username": username,
                    "exercise": exercise,
                    "weight": weight,
                    "reps": reps
                },
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

def delete_prs_by_message(message_id):
    """Delete all PR entries associated with a message ID"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('DELETE FROM prs WHERE message_id = ?', (message_id,))
    deleted_count = c.rowcount
    conn.commit()
    conn.close()
    return deleted_count

@bot.event
async def on_ready():
    """Called when the bot is ready"""
    print(f'{bot.user} has connected to Discord!')
    print(f'Monitoring channels for PR entries...')
    init_db()

@bot.event
async def on_message(message):
    """Monitor all messages in the specified channels"""
    if message.author.bot:
        return
    
    channel_id = str(message.channel.id)
    
    if channel_id == PR_CHANNEL_ID:
        content_lower = message.content.lower()
        core_foods_keywords = ['core foods', 'core', 'food', 'ate', 'eating', 'meal', 'diet', 'nutrition', 'check in', 'checkin']
        
        is_core_foods = any(keyword in content_lower for keyword in core_foods_keywords)
        
        if is_core_foods:
            if can_award_core_foods_xp(str(message.author.id)):
                xp_earned = 200
                
                add_xp(
                    str(message.author.id),
                    message.author.name,
                    xp_earned,
                    "Core foods check-in"
                )
                
                success = record_core_foods_checkin(str(message.author.id), str(message.id), xp_earned)
                
                if success:
                    await message.add_reaction('🍎')
                    await message.add_reaction('✅')
            else:
                await message.add_reaction('✅')
        else:
            parsed_prs = parse_all_prs(message.content)
            
            if parsed_prs:
                logged_count = 0
                
                for exercise, weight, reps in parsed_prs:
                    estimated_1rm = calculate_1rm(weight, reps)
                    
                    await store_pr(
                        str(message.author.id),
                        message.author.name,
                        exercise,
                        weight,
                        reps,
                        estimated_1rm,
                        str(message.id),
                        str(message.channel.id)
                    )
                    
                    logged_count += 1
                    print(f'Logged PR: {message.author.name} - {exercise} {weight}/{reps} (Est. 1RM: {estimated_1rm:.1f})')
                
                xp_earned = logged_count * 100
                add_xp(
                    str(message.author.id),
                    message.author.name,
                    xp_earned,
                    f"{logged_count} PR(s)"
                )
                
                if logged_count == 1:
                    await message.add_reaction('💪')
                elif logged_count > 1:
                    await message.add_reaction('💪')
                    await message.add_reaction('🔥')
    
    elif channel_id == LOGS_CHANNEL_ID:
        if len(message.content) >= 300:
            if can_award_weekly_log_xp(str(message.author.id)):
                xp_earned = 800
                
                if message.attachments:
                    xp_earned += 50
                
                add_xp(
                    str(message.author.id),
                    message.author.name,
                    xp_earned,
                    "Weekly log"
                )
                
                record_weekly_log(str(message.author.id), str(message.id), xp_earned)
                
                await message.add_reaction('📝')
                await message.add_reaction('✅')
            else:
                await message.add_reaction('⏰')
    
    await bot.process_commands(message)

@bot.event
async def on_message_edit(before, after):
    """Handle edited messages in the PR channel"""
    if after.author.bot:
        return
    
    if str(after.channel.id) != PR_CHANNEL_ID:
        return
    
    if before.content == after.content:
        return
    
    deleted_count = delete_prs_by_message(str(after.id))
    
    parsed_prs = parse_all_prs(after.content)
    
    if parsed_prs:
        logged_count = 0
        
        for exercise, weight, reps in parsed_prs:
            estimated_1rm = calculate_1rm(weight, reps)
            
            await store_pr(
                str(after.author.id),
                after.author.name,
                exercise,
                weight,
                reps,
                estimated_1rm,
                str(after.id),
                str(after.channel.id)
            )
            
            logged_count += 1
            print(f'Updated PR: {after.author.name} - {exercise} {weight}/{reps} (Est. 1RM: {estimated_1rm:.1f})')
        
        await after.add_reaction('🔄')
        
        if deleted_count > 0:
            print(f'Replaced {deleted_count} old PR(s) with {logged_count} new PR(s) for message {after.id}')
    else:
        if deleted_count > 0:
            await after.add_reaction('❌')
            print(f'Removed {deleted_count} PR(s) from edited message {after.id} (no longer valid)')

@bot.command()
@commands.has_permissions(administrator=True)
async def prcount(ctx):
    """Check total number of PRs stored"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM prs')
    count = c.fetchone()[0]
    conn.close()
    
    await ctx.send(f'Total PRs stored: {count}')

@bot.command()
async def mylatest(ctx):
    """Check your 5 most recent PRs"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        SELECT exercise, weight, reps, estimated_1rm, timestamp 
        FROM prs 
        WHERE user_id = ? 
        ORDER BY timestamp DESC 
        LIMIT 5
    ''', (str(ctx.author.id),))
    
    records = c.fetchall()
    conn.close()
    
    if records:
        response = "**Your latest PRs:**\n"
        for exercise, weight, reps, est_1rm, timestamp in records:
            date = datetime.fromisoformat(timestamp).strftime('%Y-%m-%d')
            response += f"• {exercise}: {weight}/{reps} (Est. 1RM: {est_1rm:.1f}) - {date}\n"
        await ctx.send(response)
    else:
        await ctx.send("No PRs found for you yet!")

@bot.command()
async def progress(ctx):
    """Show your overall strength improvement"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute('''
        SELECT exercise, 
               MIN(estimated_1rm) as first_1rm,
               MAX(estimated_1rm) as current_1rm,
               COUNT(*) as pr_count,
               MIN(timestamp) as first_date,
               MAX(timestamp) as latest_date
        FROM prs 
        WHERE user_id = ?
        GROUP BY exercise
        HAVING COUNT(*) >= 2
    ''', (str(ctx.author.id),))
    
    exercises = c.fetchall()
    conn.close()
    
    if not exercises:
        await ctx.send("You need at least 2 PRs in an exercise to track progress!")
        return
    
    exercise_gains = []
    total_percentage = 0
    
    for exercise, first_1rm, current_1rm, pr_count, first_date, latest_date in exercises:
        pct_gain = ((current_1rm - first_1rm) / first_1rm) * 100
        exercise_gains.append((exercise, pct_gain, pr_count, current_1rm - first_1rm))
        total_percentage += pct_gain
    
    avg_gain = total_percentage / len(exercise_gains)
    
    first_pr_date = datetime.fromisoformat(exercises[0][4])
    latest_pr_date = datetime.fromisoformat(exercises[0][5])
    
    for ex in exercises:
        ex_first = datetime.fromisoformat(ex[4])
        ex_latest = datetime.fromisoformat(ex[5])
        if ex_first < first_pr_date:
            first_pr_date = ex_first
        if ex_latest > latest_pr_date:
            latest_pr_date = ex_latest
    
    days_training = (latest_pr_date - first_pr_date).days
    weeks_training = max(days_training / 7, 0.1)
    
    improvement_rate = avg_gain / weeks_training
    
    response = f"**📊 Your Overall Strength Progress**\n\n"
    response += f"**Overall Improvement: +{avg_gain:.1f}%**\n"
    response += f"_(Average across {len(exercise_gains)} exercises)_\n\n"
    response += f"📈 Improvement Rate: **+{improvement_rate:.2f}% per week**\n"
    response += f"📅 Training Duration: **{days_training} days** ({weeks_training:.1f} weeks)\n\n"
    response += f"**Exercise Breakdown:**\n"
    
    exercise_gains.sort(key=lambda x: x[1], reverse=True)
    
    for exercise, pct_gain, pr_count, abs_gain in exercise_gains[:10]:
        response += f"• {exercise}: **+{pct_gain:.1f}%** (+{abs_gain:.1f} lbs, {pr_count} PRs)\n"
    
    if len(exercise_gains) > 10:
        response += f"\n_...and {len(exercise_gains) - 10} more exercises_"
    
    await ctx.send(response)

@bot.command()
async def level(ctx):
    """Check your current level and XP"""
    total_xp, level = get_user_xp_info(str(ctx.author.id))
    
    xp_for_current = 0
    for i in range(1, level):
        xp_for_current += 250 + (i * 250)
    
    xp_in_level = total_xp - xp_for_current
    xp_needed_for_next = get_xp_for_next_level(level)
    progress_pct = (xp_in_level / xp_needed_for_next) * 100
    
    bar_length = 20
    filled = int((progress_pct / 100) * bar_length)
    bar = '█' * filled + '░' * (bar_length - filled)
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM prs WHERE user_id = ?', (str(ctx.author.id),))
    pr_count = c.fetchone()[0]
    conn.close()
    
    response = f"⚔️ **Level {level}**\n\n"
    response += f"**XP:** {xp_in_level:,} / {xp_needed_for_next:,} ({progress_pct:.1f}%)\n"
    response += f"[{bar}]\n\n"
    response += f"**Total XP:** {total_xp:,}\n"
    response += f"**Lifetime PRs:** {pr_count}\n"
    response += f"**Next Level:** {level + 1} (need {xp_needed_for_next - xp_in_level:,} more XP)\n"
    
    await ctx.send(response)

@bot.command()
async def leaderboard(ctx, board_type: str = "level"):
    """Show leaderboards"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    if board_type.lower() == "level":
        c.execute('''
            SELECT username, level, total_xp
            FROM user_xp
            ORDER BY level DESC, total_xp DESC
            LIMIT 10
        ''')
        title = "🏆 Top 10 Levels"
    else:
        c.execute('''
            SELECT username, total_xp, level
            FROM user_xp
            ORDER BY total_xp DESC
            LIMIT 10
        ''')
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
    """Generate content summary for specified time period"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Calculate date range
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    start_iso = start_date.isoformat()
    end_iso = end_date.isoformat()
    
    # Get all PRs in period
    c.execute('''
        SELECT user_id, username, exercise, weight, reps, estimated_1rm, timestamp
        FROM prs
        WHERE timestamp >= ? AND timestamp <= ?
        ORDER BY timestamp DESC
    ''', (start_iso, end_iso))
    all_prs = c.fetchall()
    
    # Get weekly logs in period
    c.execute('''
        SELECT user_id, COUNT(*) as log_count
        FROM weekly_logs
        WHERE timestamp >= ? AND timestamp <= ?
        GROUP BY user_id
    ''', (start_iso, end_iso))
    weekly_logs = dict(c.fetchall())
    
    # Get core foods check-ins in period
    c.execute('''
        SELECT user_id, COUNT(*) as checkin_count
        FROM core_foods_checkins
        WHERE timestamp >= ? AND timestamp <= ?
        GROUP BY user_id
    ''', (start_iso, end_iso))
    core_foods = dict(c.fetchall())
    
    # Get all users for total member count
    c.execute('SELECT user_id, username, total_xp, level FROM user_xp ORDER BY level DESC')
    all_users = c.fetchall()
    
    conn.close()
    
    if not all_prs and not weekly_logs and not core_foods:
        await ctx.send(f"No activity found in the past {days} days!")
        return
    
    # Process PRs by user
    user_prs = {}
    total_pr_count = 0
    exercise_prs = {}
    
    for user_id, username, exercise, weight, reps, est_1rm, timestamp in all_prs:
        if user_id not in user_prs:
            user_prs[user_id] = {
                'username': username,
                'prs': [],
                'pr_count': 0
            }
        user_prs[user_id]['prs'].append({
            'exercise': exercise,
            'weight': weight,
            'reps': reps,
            'est_1rm': est_1rm,
            'timestamp': timestamp
        })
        user_prs[user_id]['pr_count'] += 1
        total_pr_count += 1
        
        # Track PRs by exercise
        if exercise not in exercise_prs:
            exercise_prs[exercise] = 0
        exercise_prs[exercise] += 1
    
    # Find standout moments
    standout_moments = []
    
    for user_id, data in user_prs.items():
        # Check for PR streaks
        consecutive_days = {}
        for pr in data['prs']:
            day = pr['timestamp'][:10]
            if day not in consecutive_days:
                consecutive_days[day] = 0
            consecutive_days[day] += 1
        
        if consecutive_days:
            max_in_day = max(consecutive_days.values())
            if max_in_day >= 5:
                standout_moments.append(f"{data['username']} hit {max_in_day} PRs in a single day")
        
        # Check for big improvements in single exercise
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
    
    # Get top users by PR count
    top_users = sorted(user_prs.items(), key=lambda x: x[1]['pr_count'], reverse=True)[:5]
    
    # Count active members
    active_members = len(user_prs)
    total_members = len(all_users)
    
    # Format the summary
    summary = f"📊 **{period_name.upper()} SUMMARY ({start_date.strftime('%b %d')} - {end_date.strftime('%b %d')})**\n\n"
    
    summary += f"👥 **ACTIVE MEMBERS:** {active_members}/{total_members} ({(active_members/max(total_members,1)*100):.0f}%)\n\n"
    
    summary += f"💪 **PRS THIS {period_name.upper()}:** {total_pr_count} total\n"
    for user_id, data in top_users:
        username = data['username']
        pr_count = data['pr_count']
        
        # Get sample PRs
        sample_prs = data['prs'][:3]
        pr_samples = ", ".join([f"{pr['exercise']} +{pr['weight']:.0f}lbs" for pr in sample_prs])
        
        summary += f"- {username}: {pr_count} PRs ({pr_samples}...)\n"
    
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
        # Estimate XP: PRs * 100 + logs * 800 + core foods * 200
        est_xp = (data['pr_count'] * 100) + (weekly_logs.get(user_id, 0) * 800) + (core_foods.get(user_id, 0) * 200)
        summary += f"{i}. {data['username']}: ~{est_xp:,} XP\n"
    
    if standout_moments:
        summary += f"\n🔥 **STANDOUT MOMENTS:**\n"
        for moment in standout_moments[:5]:
            summary += f"- {moment}\n"
    
    # Top exercises this period
    if exercise_prs:
        top_exercises = sorted(exercise_prs.items(), key=lambda x: x[1], reverse=True)[:5]
        summary += f"\n💥 **MOST POPULAR EXERCISES:**\n"
        for exercise, count in top_exercises:
            summary += f"- {exercise}: {count} PRs\n"
    
    summary += f"\n---\n\n"
    summary += f"**PASTE THIS INTO CLAUDE WITH YOUR CONTENT GENERATION PROMPT**\n"
    
    # Send via DM
    try:
        await ctx.author.send(summary)
        await ctx.send("✅ Content summary sent to your DMs!")
    except discord.Forbidden:
        # If DMs are disabled, send in channel
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
    
    # Calculate date range
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    
    # Get the actual Discord channels
    pr_channel = bot.get_channel(int(PR_CHANNEL_ID))
    logs_channel = bot.get_channel(int(LOGS_CHANNEL_ID))
    
    # Find general channel
    general_channel = None
    for channel in ctx.guild.text_channels:
        if 'general' in channel.name.lower():
            general_channel = channel
            break
    
    output = f"📊 **COMPLETE RAW ACTIVITY EXPORT - PAST {days} DAYS**\n"
    output += f"**Period:** {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}\n"
    output += f"=" * 80 + "\n\n"
    
    # ===== PR CHANNEL MESSAGES =====
    if pr_channel:
        output += f"🏋️ **#PRS CHANNEL - ALL MESSAGES**\n"
        output += "=" * 80 + "\n\n"
        
        pr_messages = []
        async for message in pr_channel.history(limit=500, after=start_date):
            if not message.author.bot:
                pr_messages.append(message)
        
        pr_messages.reverse()  # chronological order
        
        for msg in pr_messages:
            output += f"[{msg.created_at.strftime('%Y-%m-%d %H:%M')}] {msg.author.name}:\n"
            output += f"{msg.content}\n"
            if msg.reactions:
                reactions = " ".join([f"{r.emoji}x{r.count}" for r in msg.reactions])
                output += f"Reactions: {reactions}\n"
            output += "\n"
        
        output += f"\nTotal PR channel messages: {len(pr_messages)}\n\n"
    
    # ===== WEEKLY LOGS CHANNEL =====
    if logs_channel:
        output += f"📝 **#WEEKLY-LOGS CHANNEL - ALL MESSAGES**\n"
        output += "=" * 80 + "\n\n"
        
        log_messages = []
        async for message in logs_channel.history(limit=200, after=start_date):
            if not message.author.bot:
                log_messages.append(message)
        
        log_messages.reverse()
        
        for msg in log_messages:
            output += f"[{msg.created_at.strftime('%Y-%m-%d %H:%M')}] {msg.author.name}:\n"
            output += f"{msg.content}\n"
            if msg.attachments:
                output += f"Attachments: {len(msg.attachments)} file(s)\n"
            if msg.reactions:
                reactions = " ".join([f"{r.emoji}x{r.count}" for r in msg.reactions])
                output += f"Reactions: {reactions}\n"
            output += "\n"
        
        output += f"\nTotal weekly log messages: {len(log_messages)}\n\n"
    
    # ===== GENERAL CHANNEL (if exists) =====
    if general_channel:
        output += f"💬 **#GENERAL CHANNEL - ALL MESSAGES**\n"
        output += "=" * 80 + "\n\n"
        
        general_messages = []
        async for message in general_channel.history(limit=500, after=start_date):
            if not message.author.bot:
                general_messages.append(message)
        
        general_messages.reverse()
        
        for msg in general_messages:
            output += f"[{msg.created_at.strftime('%Y-%m-%d %H:%M')}] {msg.author.name}:\n"
            output += f"{msg.content}\n"
            if msg.reactions:
                reactions = " ".join([f"{r.emoji}x{r.count}" for r in msg.reactions])
                output += f"Reactions: {reactions}\n"
            output += "\n"
        
        output += f"\nTotal general messages: {len(general_messages)}\n\n"
    
    # ===== DATABASE STATS =====
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    start_iso = start_date.isoformat()
    end_iso = end_date.isoformat()
    
    # PR stats
    c.execute('''
        SELECT COUNT(*), COUNT(DISTINCT user_id), COUNT(DISTINCT exercise)
        FROM prs
        WHERE timestamp >= ? AND timestamp <= ?
    ''', (start_iso, end_iso))
    pr_count, unique_users_prs, unique_exercises = c.fetchone()
    
    # XP stats
    c.execute('SELECT username, total_xp, level FROM user_xp ORDER BY total_xp DESC')
    xp_stats = c.fetchall()
    
    conn.close()
    
    output += f"📈 **DATABASE STATISTICS**\n"
    output += "=" * 80 + "\n\n"
    output += f"Total PRs logged: {pr_count}\n"
    output += f"Unique members with PRs: {unique_users_prs}\n"
    output += f"Unique exercises: {unique_exercises}\n\n"
    
    output += f"**Current XP Leaderboard:**\n"
    for username, xp, level in xp_stats:
        output += f"- {username}: Level {level} ({xp:,} XP)\n"
    
    output += "\n" + "=" * 80 + "\n"
    output += f"**END OF RAW DATA EXPORT**\n"
    output += f"Total characters: {len(output):,}\n"
    
    # Send as text file
    file = discord.File(io.BytesIO(output.encode('utf-8')), filename=f'discord_raw_export_{period_name.lower()}.txt')
    try:
        await ctx.author.send(file=file)
        await ctx.send("✅ Raw data export sent to your DMs as a file!")
    except discord.Forbidden:
        await ctx.send(file=file)

@bot.command()
@commands.has_permissions(administrator=True)
async def export_data(ctx):
    """Export all database data as JSON for migration"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Export PRs
    c.execute('SELECT user_id, username, exercise, weight, reps, estimated_1rm, timestamp FROM prs')
    prs = [{"user_id": r[0], "username": r[1], "exercise": r[2], "weight": r[3], "reps": r[4], "estimated_1rm": r[5], "timestamp": r[6]} for r in c.fetchall()]
    
    # Export XP
    c.execute('SELECT user_id, username, total_xp, level FROM user_xp')
    xp = [{"user_id": r[0], "username": r[1], "total_xp": r[2], "level": r[3]} for r in c.fetchall()]
    
    conn.close()
    
    data = {"prs": prs, "xp": xp}
    
    # Send as file
    import json
    file_content = json.dumps(data, indent=2)
    file = discord.File(io.BytesIO(file_content.encode('utf-8')), filename='ttm_data_export.json')
    
    await ctx.author.send(f"Exported {len(prs)} PRs and {len(xp)} XP records")
    await ctx.author.send(file=file)
    await ctx.send("✅ Data exported to your DMs!")

if __name__ == '__main__':
    TOKEN = os.getenv('DISCORD_BOT_TOKEN')
    
    if not TOKEN:
        print("Error: DISCORD_BOT_TOKEN environment variable not set!")
        print("Set it with: set DISCORD_TOKEN=your_token_here")
    else:
        keep_alive()
        bot.run(TOKEN)
