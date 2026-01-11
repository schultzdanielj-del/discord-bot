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

def parse_pr(message_content):
    """
    Parse PR format with flexibility for typos and format variations
    Examples: 'bench press 110/15', 'squat 225x10', 'deadlift: 315 for 5 reps'
    Returns: (exercise, weight, reps) or None if invalid
    """
    text = message_content.strip().lower()
    
    # Remove common filler words and normalize
    text = re.sub(r'\b(pr|new pr|hit|got|did|at|for|with)\b', ' ', text)
    text = re.sub(r'\b(reps?|rep|repetitions?)\b', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Try multiple patterns to handle different formats
    patterns = [
        r'^(.+?)\s+([\d.]+)\s*/\s*(\d+)',
        r'^(.+?)\s+([\d.]+)\s*x\s*(\d+)',
        r'^(.+?)\s+([\d.]+)\s*-\s*(\d+)',
        r'^(\d+)\s*[x/]\s*([\d.]+)\s+(.+)',
        r'^(.+?)\s+([\d.]+)\s+(\d+)$',
        r'^(.+?):\s*([\d.]+)\s*/\s*(\d+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            groups = match.groups()
            
            # Check if format is reversed (reps/weight/exercise)
            if pattern == patterns[3]:
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
            
            # Sanity checks
            if exercise and weight > 0 and reps > 0 and reps < 1000:
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
    
    # Try to parse the message as a PR entry
    parsed = parse_pr(message.content)
    
    if parsed:
        exercise, weight, reps = parsed
        
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
        
        # React to confirm the PR was logged
        await message.add_reaction('✅')
        
        print(f'Logged PR: {message.author.name} - {exercise} {weight}/{reps} (Est. 1RM: {estimated_1rm:.1f})')
    
    # Process other commands if any
    await bot.process_commands(message)

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
@commands.has_permissions(administrator=True)
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
