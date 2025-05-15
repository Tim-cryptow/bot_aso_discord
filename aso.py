import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
import os
import asyncpg
import asyncio

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents)

DATABASE_URL = os.environ['DATABASE_URL']
db_pool = None

# Database setup
async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    async with db_pool.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            last_feed TIMESTAMP,
            streak INTEGER DEFAULT 0,
            hatched INTEGER DEFAULT 0
        )""")
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS eggs (
            user_id TEXT REFERENCES users(user_id),
            laid_at TIMESTAMP
        )""")

@bot.event
async def on_ready():
    await init_db()
    egg_cleanup.start()
    print(f'Logged in as {bot.user}')

# Commands
@bot.command()
async def feed(ctx):
    user_id = str(ctx.author.id)
    now = datetime.utcnow()
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id=$1", user_id)
        if user and user['last_feed'] and user['last_feed'].date() == now.date():
            await ctx.send("You can only feed the chicken once a day!")
            return

        streak = 1
        if user and user['last_feed'] and (now.date() - user['last_feed'].date()).days == 1:
            streak = user['streak'] + 1 if user['streak'] else 1

        await conn.execute("""
            INSERT INTO users (user_id, last_feed, streak, hatched)
            VALUES ($1, $2, $3, COALESCE((SELECT hatched FROM users WHERE user_id=$1), 0))
            ON CONFLICT (user_id) DO UPDATE SET last_feed=$2, streak=$3
        """, user_id, now, streak)

        await conn.execute("INSERT INTO eggs (user_id, laid_at) VALUES ($1, $2)", user_id, now)

        await ctx.send(f"You fed the chicken! It laid an egg 🥚\nCurrent feeding streak: {streak} 🔥")

@bot.command()
async def wealth(ctx):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, hatched FROM users ORDER BY hatched DESC LIMIT 10")
        message = "**Chicken Leaderboard 🏆**\n"
        badges = ["🥇", "🥈", "🥉"]
        for i, row in enumerate(rows, 1):
            member = await bot.fetch_user(int(row['user_id']))
            badge = badges[i-1] + " " if i <= 3 else ""
            message += f"{i}. {badge}{member.name} - {row['hatched']} chickens\n"
        await ctx.send(message)

@bot.command()
async def hatch(ctx):
    user_id = str(ctx.author.id)
    now = datetime.utcnow()
    async with db_pool.acquire() as conn:
        eggs = await conn.fetch("SELECT laid_at FROM eggs WHERE user_id=$1", user_id)
        hatched = 0
        for egg in eggs:
            if (now - egg['laid_at']).days >= 21:
                hatched += 1

        await conn.execute("DELETE FROM eggs WHERE user_id=$1 AND laid_at <= $2", user_id, now - timedelta(days=21))
        await conn.execute("""
            INSERT INTO users (user_id, hatched)
            VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET hatched = users.hatched + $2
        """, user_id, hatched)

        await ctx.send(f"You hatched {hatched} eggs into chickens! 🐣")

@bot.command()
async def chicken(ctx):
    user_id = str(ctx.author.id)
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT hatched, streak FROM users WHERE user_id=$1", user_id)
        eggs = await conn.fetchval("SELECT COUNT(*) FROM eggs WHERE user_id=$1", user_id)
        chickens = user['hatched'] if user else 0
        streak = user['streak'] if user else 0
        await ctx.send(f"You have {chickens} chickens 🐔 and {eggs} unhatched eggs 🥚\nFeeding streak: {streak} 🔥")

# Cleanup expired eggs
@tasks.loop(hours=24)
async def egg_cleanup():
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM eggs WHERE laid_at < $1", datetime.utcnow() - timedelta(days=21))

bot.run(os.environ['TOKEN'])
