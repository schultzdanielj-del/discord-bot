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
    """Monitor all messages in the specified channel"""
    if message.author.bot:
        return
    
    PR_CHANNEL_ID = '1459000944028028970'
    
    if str(message.channel.id) != PR_CHANNEL_ID:
        await bot.process_commands(message)
        return
    
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
        
        if logged_count == 1:
            await message.add_reaction('✅')
        elif logged_count > 1:
            await message.add_reaction('✅')
            await message.add_reaction('💪')
    
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

if __name__ == '__main__':
    TOKEN = os.getenv('DISCORD_BOT_TOKEN')
    
    if not TOKEN:
        print("Error: DISCORD_BOT_TOKEN environment variable not set!")
        print("Set it with: set DISCORD_TOKEN=your_token_here")
    else:
        keep_alive()
        bot.run(TOKEN)
