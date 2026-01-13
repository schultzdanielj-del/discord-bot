import discord
from discord.ext import commands
import sqlite3
from datetime import datetime
import re
import os
from flask import Flask
from threading import Thread

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

def init_db():
    """Initialize the database with required tables"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Create table for storing PRs
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
    """
    Calculate estimated 1 rep max using Epley formula
    Formula: (weight * reps * 0.0333) + weight
    """
    return (weight * reps * 0.0333) + weight

def parse_all_prs(message_content):
    """
    Parse multiple PR entries from a single message
    Returns: list of (exercise, weight, reps) tuples
    """
    print(f"[DEBUG parse_all_prs] Input: '{message_content}'")
    prs = []
    text = message_content.strip()
    
    # Split by common delimiters that separate different exercises
    # Look for newlines or patterns that suggest a new exercise
    lines = text.split('\n')
    print(f"[DEBUG parse_all_prs] Split into {len(lines)} lines")
    
    for i, line in enumerate(lines):
        print(f"[DEBUG parse_all_prs] Processing line {i}: '{line}'")
        parsed = parse_single_pr(line)
        if parsed:
            print(f"[DEBUG parse_all_prs] Line {i} parsed successfully")
            prs.append(parsed)
        else:
            print(f"[DEBUG parse_all_prs] Line {i} failed to parse")
    
    # If no newlines, try to find multiple PRs in a single line
    if not prs:
        print(f"[DEBUG parse_all_prs] No PRs from line splitting, trying single line parse")
        # Look for multiple weight/rep patterns in one line
        parsed = parse_single_pr(text)
        if parsed:
            print(f"[DEBUG parse_all_prs] Single line parsed successfully")
            prs.append(parsed)
        else:
            print(f"[DEBUG parse_all_prs] Single line failed to parse")
    
    print(f"[DEBUG parse_all_prs] Total PRs found: {len(prs)}")
    return prs

def normalize_exercise_name(exercise):
    """
    Normalize exercise names to standardize variations
    Returns the standardized exercise name
    """
    exercise = exercise.lower().strip()
    
    # Remove trailing 's' to handle plurals (we'll add it back consistently later)
    # But preserve words that end in 'ss' like 'press'
    words = exercise.split()
    normalized_words = []
    
    for word in words:
        # Don't strip 's' from words ending in 'ss' or very short words
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
    # Check if "extension" exists and is NOT part of leg/back/reverse/hyper/hip extension
    if 'extension' in exercise:
        if not re.search(r'\b(leg|back|reverse|hyper|hip)\s+extension', exercise):
            # It's a tricep extension - keep other modifiers like "lying", "overhead", etc.
            exercise = re.sub(r'\bextension\b', 'tricep extension', exercise)
    
    # Clean up extra spaces
    exercise = re.sub(r'\s+', ' ', exercise).strip()
    
    return exercise

def parse_single_pr(text):
    """
    Parse a single PR from text with flexibility for typos and format variations
    Examples: 'bench press 110/15', 'squat 225x10', 'deadlift: 315 for 5 reps', 'chinups bw/10'
    Returns: (exercise, weight, reps) or None if invalid
    """
    text = text.strip().lower()
    
    if not text:
        return None
    
    # Handle bodyweight notation - replace BW with 0
    text = re.sub(r'\bbw\b', '0', text, flags=re.IGNORECASE)
    text = re.sub(r'\bbodyweight\b', '0', text, flags=re.IGNORECASE)
    
    # Remove common filler words and normalize
    text = re.sub(r'\b(pr|new pr|hit|got|did|at|for|with|just|finally|crushed)\b', ' ', text)
    text = re.sub(r'\b(reps?|rep|repetitions?)\b', '', text)
    text = re.sub(r'\b(lbs?|pounds?|kgs?|kilos?)\b', '', text)  # Remove units
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Try multiple patterns to handle different formats
    patterns = [
        # exercise weight/reps or weight*reps or weight x reps
        r'^(.+?)\s+([\d.]+)\s*[/*x×]\s*(\d+)',
        # exercise weight - reps
        r'^(.+?)\s+([\d.]+)\s*-\s*(\d+)',
        # reps x weight exercise (reversed format)
        r'^(\d+)\s*[x×]\s*([\d.]+)\s+(.+)',
        # exercise: weight/reps (with colon)
        r'^(.+?):\s*([\d.]+)\s*[/*x×]\s*(\d+)',
        # exercise weight reps (space separated, must be at end)
        r'^(.+?)\s+([\d.]+)\s+(\d+)

def store_pr(user_id, username, exercise, weight, reps, estimated_1rm, message_id, channel_id):
    """Store a PR entry in the database"""
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
    """Monitor all messages in the specified channel"""
    # Ignore bot's own messages
    if message.author.bot:
        return
    
    # Set your PR channel ID here
    PR_CHANNEL_ID = '1459000944028028970'
    
    print(f"[DEBUG on_message] Message received in channel {message.channel.id}")
    print(f"[DEBUG on_message] Content: '{message.content}'")
    
    # Only process messages from the designated PR channel
    if str(message.channel.id) != PR_CHANNEL_ID:
        print(f"[DEBUG on_message] Not the PR channel, skipping")
        await bot.process_commands(message)
        return
    
    print(f"[DEBUG on_message] This is the PR channel, attempting to parse")
    
    # Try to parse the message for multiple PR entries
    parsed_prs = parse_all_prs(message.content)
    
    print(f"[DEBUG on_message] Parsed {len(parsed_prs)} PR(s)")
    
    if parsed_prs:
        logged_count = 0
        
        for exercise, weight, reps in parsed_prs:
            # Calculate estimated 1RM
            estimated_1rm = calculate_1rm(weight, reps)
            
            # Store in database
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
        
        # React to confirm the PR(s) were logged
        if logged_count == 1:
            await message.add_reaction('✅')
        elif logged_count > 1:
            # Use different reactions for multiple PRs
            await message.add_reaction('✅')
            await message.add_reaction('💪')
    else:
        print(f"[DEBUG on_message] No valid PRs found in message")
    
    # Process other commands if any
    await bot.process_commands(message)

@bot.event
async def on_message_edit(before, after):
    """Handle edited messages in the PR channel"""
    # Ignore bot's own messages
    if after.author.bot:
        return
    
    # Set your PR channel ID here
    PR_CHANNEL_ID = '1459000944028028970'
    
    # Only process messages from the designated PR channel
    if str(after.channel.id) != PR_CHANNEL_ID:
        return
    
    # If the content hasn't changed, ignore
    if before.content == after.content:
        return
    
    # Delete old PR entries for this message
    deleted_count = delete_prs_by_message(str(after.id))
    
    # Try to parse the edited message for PR entries
    parsed_prs = parse_all_prs(after.content)
    
    if parsed_prs:
        logged_count = 0
        
        for exercise, weight, reps in parsed_prs:
            # Calculate estimated 1RM
            estimated_1rm = calculate_1rm(weight, reps)
            
            # Store in database with updated info
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
        
        # React to show the edit was processed
        await after.add_reaction('🔄')
        
        if deleted_count > 0:
            print(f'Replaced {deleted_count} old PR(s) with {logged_count} new PR(s) for message {after.id}')
    else:
        # If edited message no longer contains valid PRs, just delete old entries
        if deleted_count > 0:
            await after.add_reaction('❌')
            print(f'Removed {deleted_count} PR(s) from edited message {after.id} (no longer valid)')

# Optional admin commands for testing
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

# Run the bot
if __name__ == '__main__':
    # Get token from environment variable for security
    TOKEN = os.getenv('DISCORD_BOT_TOKEN')
    
    if not TOKEN:
        print("Error: DISCORD_BOT_TOKEN environment variable not set!")
        print("Set it with: set DISCORD_TOKEN=your_token_here")
    else:
        keep_alive()
        bot.run(TOKEN),
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            groups = match.groups()
            
            # Check if format is reversed (reps/weight/exercise)
            if pattern == patterns[2]:  # The reversed pattern
                reps = int(groups[0])
                weight = float(groups[1])
                exercise = groups[2].strip()
            else:
                exercise = groups[0].strip()
                weight = float(groups[1])
                reps = int(groups[2])
            
            # Normalize exercise name (remove special chars first)
            exercise = re.sub(r'[^\w\s]', '', exercise)
            exercise = re.sub(r'\s+', ' ', exercise).strip()
            
            # Apply exercise name standardization
            exercise = normalize_exercise_name(exercise)
            
            # Sanity checks (allow weight = 0 for bodyweight exercises)
            if exercise and weight >= 0 and reps > 0 and reps < 1000:
                return (exercise, weight, reps)
    
    return None

def store_pr(user_id, username, exercise, weight, reps, estimated_1rm, message_id, channel_id):
    """Store a PR entry in the database"""
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
    """Monitor all messages in the specified channel"""
    # Ignore bot's own messages
    if message.author.bot:
        return
    
    # Set your PR channel ID here
    PR_CHANNEL_ID = '1459000944028028970'
    
    # Only process messages from the designated PR channel
    if str(message.channel.id) != PR_CHANNEL_ID:
        await bot.process_commands(message)
        return
    
    # Try to parse the message for multiple PR entries
    parsed_prs = parse_all_prs(message.content)
    
    if parsed_prs:
        logged_count = 0
        
        for exercise, weight, reps in parsed_prs:
            # Calculate estimated 1RM
            estimated_1rm = calculate_1rm(weight, reps)
            
            # Store in database
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
        
        # React to confirm the PR(s) were logged
        if logged_count == 1:
            await message.add_reaction('✅')
        elif logged_count > 1:
            # Use different reactions for multiple PRs
            await message.add_reaction('✅')
            await message.add_reaction('💪')
    
    # Process other commands if any
    await bot.process_commands(message)

@bot.event
async def on_message_edit(before, after):
    """Handle edited messages in the PR channel"""
    # Ignore bot's own messages
    if after.author.bot:
        return
    
    # Set your PR channel ID here
    PR_CHANNEL_ID = '1459000944028028970'
    
    # Only process messages from the designated PR channel
    if str(after.channel.id) != PR_CHANNEL_ID:
        return
    
    # If the content hasn't changed, ignore
    if before.content == after.content:
        return
    
    # Delete old PR entries for this message
    deleted_count = delete_prs_by_message(str(after.id))
    
    # Try to parse the edited message for PR entries
    parsed_prs = parse_all_prs(after.content)
    
    if parsed_prs:
        logged_count = 0
        
        for exercise, weight, reps in parsed_prs:
            # Calculate estimated 1RM
            estimated_1rm = calculate_1rm(weight, reps)
            
            # Store in database with updated info
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
        
        # React to show the edit was processed
        await after.add_reaction('🔄')
        
        if deleted_count > 0:
            print(f'Replaced {deleted_count} old PR(s) with {logged_count} new PR(s) for message {after.id}')
    else:
        # If edited message no longer contains valid PRs, just delete old entries
        if deleted_count > 0:
            await after.add_reaction('❌')
            print(f'Removed {deleted_count} PR(s) from edited message {after.id} (no longer valid)')

# Optional admin commands for testing
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

# Run the bot
if __name__ == '__main__':
    # Get token from environment variable for security
    TOKEN = os.getenv('DISCORD_BOT_TOKEN')
    
    if not TOKEN:
        print("Error: DISCORD_BOT_TOKEN environment variable not set!")
        print("Set it with: set DISCORD_TOKEN=your_token_here")
    else:
        keep_alive()
        bot.run(TOKEN)
