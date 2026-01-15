import discord
from discord.ext import commands
import sqlite3
from datetime import datetime
import re
import os
from flask import Flask
from threading import Thread
from rapidfuzz import fuzz, process

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
    
    conn.commit()
    conn.close()

def calculate_1rm(weight, reps):
    """Calculate estimated 1 rep max using Epley formula"""
    return (weight * reps * 0.0333) + weight

def calculate_level(total_xp):
    """Calculate level based on total XP. Each level requires 250 + (level * 250) XP"""
    level = 1
    xp_needed = 500  # Level 1 -> 2 requires 500 XP
    
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
    
    # Get or create user XP record
    c.execute('SELECT total_xp, level FROM user_xp WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    
    if result:
        old_xp, old_level = result
        new_xp = old_xp + xp_amount
    else:
        old_xp, old_level = 0, 1
        new_xp = xp_amount
    
    new_level = calculate_level(new_xp)
    
    # Update or insert user XP
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
    """Check if user can receive weekly log XP (once per 6 days)"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Get most recent weekly log
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
    
    # Must wait 6 days between weekly logs
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
        # Already checked in today
        success = False
    
    conn.close()
    return success

def normalize_exercise_name(exercise):
    """Normalize exercise names to standardize variations"""
    exercise = exercise.lower().strip()
    
    # Remove trailing 's' to handle plurals
    words = exercise.split()
    normalized_words = []
    
    for word in words:
        if len(word) > 2 and word.endswith('s') and not word.endswith('ss'):
            normalized_words.append(word[:-1])
        else:
            normalized_words.append(word)
    
    exercise = ' '.join(normalized_words)
    
    # Standardize arm variations
    exercise = re.sub(r'\b(1|one|single)\s+arm\b', 'single arm', exercise)
    
    # Standardize grip variations
    exercise = re.sub(r'\b(uh|underhand\s+grip)\b', 'underhand', exercise)
    
    # Standardize equipment
    exercise = re.sub(r'\bdb\b', 'dumbbell', exercise)
    exercise = re.sub(r'\bbb\b', 'barbell', exercise)
    
    # Standardize fly variations
    exercise = re.sub(r'\bflye?\b', 'fly', exercise)
    
    # Standardize raise variations
    exercise = re.sub(r'\blateral\b', 'lateral raise', exercise)
    
    # Standardize rear delt fly
    exercise = re.sub(r'\brdf\b', 'rear delt fly', exercise)
    
    # Standardize supported
    exercise = re.sub(r'\bsupp\b', 'supported', exercise)
    
    # Handle extensions - only convert to "tricep extension" if NOT preceded by leg/back/reverse/hyper/hip
    if 'extension' in exercise:
        if not re.search(r'\b(leg|back|reverse|hyper|hip)\s+extension', exercise):
            exercise = re.sub(r'\bextension\b', 'tricep extension', exercise)
    
    # Clean up extra spaces
    exercise = re.sub(r'\s+', ' ', exercise).strip()
    
    return exercise

def parse_single_pr(text):
    """Parse a single PR from text"""
    text = text.strip().lower()
    
    if not text:
        return None
    
    # Handle bodyweight notation
    text = re.sub(r'\bbw\b', '0', text, flags=re.IGNORECASE)
    text = re.sub(r'\bbodyweight\b', '0', text, flags=re.IGNORECASE)
    
    # Remove common filler words
    text = re.sub(r'\b(pr|new pr|hit|got|did|at|for|with|just|finally|crushed)\b', ' ', text)
    text = re.sub(r'\b(reps?|rep|repetitions?)\b', '', text)
    text = re.sub(r'\b(lbs?|pounds?|kgs?|kilos?)\b', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Define patterns
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
            
            # Normalize exercise name
            exercise = re.sub(r'[^\w\s]', '', exercise)
            exercise = re.sub(r'\s+', ' ', exercise).strip()
            exercise = normalize_exercise_name(exercise)
            
            # Sanity checks
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
    """
    Match exercise name to existing exercises in database using fuzzy matching.
    Returns the most common spelling if a close match is found, otherwise returns the input.
    """
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Get all unique exercise names with their counts
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
    
    # Create a list of just the exercise names
    exercise_names = [ex[0] for ex in existing_exercises]
    
    # Find the best match using fuzzy matching
    best_match = process.extractOne(exercise, exercise_names, scorer=fuzz.ratio)
    
    # If match is 85% or better, use the canonical name
    # Otherwise, use the input as-is (it's a new exercise)
    if best_match and best_match[1] >= 85:
        return best_match[0]
    
    return exercise

def store_pr(user_id, username, exercise, weight, reps, estimated_1rm, message_id, channel_id):
    """Store a PR entry in the database"""
    
    # Use fuzzy matching to find canonical exercise name
    exercise = get_canonical_exercise_name(exercise)
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    timestamp = datetime.utcnow().isoformat()
    
    c.execute('''
        INSERT INTO prs (user_id, username, exercise, weight, reps, estimated_1rm, timestamp, message_id, channel_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, username, exercise, weight, reps, estimated_1rm, timestamp, message_id, channel_id))
    
    conn.commit()
    conn.close()

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
    
    # Handle PR channel (also handles core foods in same channel)
    if channel_id == PR_CHANNEL_ID:
        # Check if this is a core foods check-in first
        content_lower = message.content.lower()
        core_foods_keywords = ['core foods', 'core', 'food', 'ate', 'eating', 'meal', 'diet', 'nutrition', 'check in', 'checkin']
        
        is_core_foods = any(keyword in content_lower for keyword in core_foods_keywords)
        
        if is_core_foods:
            # Handle as core foods check-in
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
                # Already checked in today
                await message.add_reaction('✅')
        else:
            # Handle as PR
            parsed_prs = parse_all_prs(message.content)
            
            if parsed_prs:
                logged_count = 0
                
                for exercise, weight, reps in parsed_prs:
                    estimated_1rm = calculate_1rm(weight, reps)
                    
                    store_pr(
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
                
                # Award XP for PRs (100 XP each) - silently
                xp_earned = logged_count * 100
                add_xp(
                    str(message.author.id),
                    message.author.name,
                    xp_earned,
                    f"{logged_count} PR(s)"
                )
                
                # React to confirm
                if logged_count == 1:
                    await message.add_reaction('💪')
                elif logged_count > 1:
                    await message.add_reaction('💪')
                    await message.add_reaction('🔥')
    
    # Handle weekly logs channel
    elif channel_id == LOGS_CHANNEL_ID:
        # Check if message is long enough (300+ characters)
        if len(message.content) >= 300:
            if can_award_weekly_log_xp(str(message.author.id)):
                # Award 800 XP for weekly log
                xp_earned = 800
                
                # Bonus XP if message includes attachments (photos)
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
                # Too soon for another weekly log
                await message.add_reaction('⏰')
    
    await bot.process_commands(message)

@bot.event
async def on_message_edit(before, after):
    """Handle edited messages in the PR channel"""
    if after.author.bot:
        return
    
    PR_CHANNEL_ID = '1459000944028028970'
    
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
            
            store_pr(
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
    
    # Get all exercises with 2+ PRs
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
    
    # Calculate percentage gain for each exercise
    exercise_gains = []
    total_percentage = 0
    
    for exercise, first_1rm, current_1rm, pr_count, first_date, latest_date in exercises:
        pct_gain = ((current_1rm - first_1rm) / first_1rm) * 100
        exercise_gains.append((exercise, pct_gain, pr_count, current_1rm - first_1rm))
        total_percentage += pct_gain
    
    # Calculate average % gain across all exercises
    avg_gain = total_percentage / len(exercise_gains)
    
    # Calculate time span and improvement rate
    first_pr_date = datetime.fromisoformat(exercises[0][4])
    latest_pr_date = datetime.fromisoformat(exercises[0][5])
    
    # Find earliest and latest across all exercises
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
    
    # Build response
    response = f"**📊 Your Overall Strength Progress**\n\n"
    response += f"**Overall Improvement: +{avg_gain:.1f}%**\n"
    response += f"_(Average across {len(exercise_gains)} exercises)_\n\n"
    response += f"📈 Improvement Rate: **+{improvement_rate:.2f}% per week**\n"
    response += f"📅 Training Duration: **{days_training} days** ({weeks_training:.1f} weeks)\n\n"
    response += f"**Exercise Breakdown:**\n"
    
    # Sort by percentage gain
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
    
    # Calculate XP progress in current level
    xp_for_current = 0
    for i in range(1, level):
        xp_for_current += 250 + (i * 250)
    
    xp_in_level = total_xp - xp_for_current
    xp_needed_for_next = get_xp_for_next_level(level)
    progress_pct = (xp_in_level / xp_needed_for_next) * 100
    
    # Create progress bar
    bar_length = 20
    filled = int((progress_pct / 100) * bar_length)
    bar = '█' * filled + '░' * (bar_length - filled)
    
    # Get PR count
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
    """Show leaderboards - !leaderboard level or !leaderboard xp"""
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

if __name__ == '__main__':
    TOKEN = os.getenv('DISCORD_BOT_TOKEN')
    
    if not TOKEN:
        print("Error: DISCORD_BOT_TOKEN environment variable not set!")
        print("Set it with: set DISCORD_TOKEN=your_token_here")
    else:
        keep_alive()
        bot.run(TOKEN)
