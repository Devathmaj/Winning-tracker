import discord
from discord.ext import commands
from discord import app_commands
import re
import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import os

load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client["Winningtrack"]
sessions_collection = db["Sessions"]

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True

bot = commands.Bot(command_prefix="!", intents=intents)

OWO_BOT_ID = 408785106942164992

active_sessions = {}

amount_pattern = re.compile(r"(\d{1,3}(?:,\d{3})*|\d+)")

def extract_last_amount(text):
    text = text.replace(",", "")
    amounts = amount_pattern.findall(text)
    return int(amounts[-1]) if amounts else None

@bot.event
async def on_ready():
    print(f"Bot is ready. Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.")
    except Exception as e:
        print(e)

@bot.tree.command(name="initialize", description="Start a new session to track your winnings")
async def initialize(interaction: discord.Interaction):
    user_id = interaction.user.id
    if user_id in active_sessions:
        await interaction.response.send_message("You already have an active session. Use /result to finish it.", ephemeral=True)
        return
    active_sessions[user_id] = {
        "bets": [],
        "winnings": [],
        "lost": [],
        "start_time": datetime.datetime.now(datetime.timezone.utc)
    }
    await interaction.response.send_message("New session started! Tracking initialized.", ephemeral=True)

@bot.tree.command(name="result", description="End session and show total result")
async def result(interaction: discord.Interaction):
    user_id = interaction.user.id
    if user_id not in active_sessions:
        await interaction.response.send_message("You don't have an active session. Use /initialize to start one.", ephemeral=True)
        return
    session = active_sessions.pop(user_id)
    total_bet = sum(session.get("bets", []))
    total_win = sum(session.get("winnings", []))
    total_loss = sum(session.get("lost", []))
    net = total_win - total_bet
    await sessions_collection.insert_one({
        "user_id": str(user_id),
        "start_time": session["start_time"],
        "end_time": datetime.datetime.now(datetime.timezone.utc),
        "total_bet": total_bet,
        "total_win": total_win,
        "total_loss": total_loss,
        "net_gain": net
    })
    await interaction.response.send_message(
        f"**Session Result:**\nLost: `{total_loss:,}`\nWon: `{total_win:,}`\nNet: `{net:,}`"
    )

@bot.event
async def on_message(message):
    if message.author.id != OWO_BOT_ID:
        return

    content = message.content.lower().replace(",", "")
    embeds = message.embeds

    target_user_id = None
    if message.mentions:
        for user in message.mentions:
            if user.id != OWO_BOT_ID:
                target_user_id = user.id
                break

    if target_user_id is None:
        return
    if target_user_id not in active_sessions:
        return

    session = active_sessions[target_user_id]

    if "spent :cowoncy:" in content and "chose" in content and "the coin spins" in content:
        bet = extract_last_amount(content)
        if bet is not None:
            if "you won" in content:
                session["bets"].append(bet)
                session["winnings"].append(bet * 2)
            elif "you lost it all" in content:
                session["bets"].append(bet)
                session["lost"].append(bet)
        return

    if "___slots___" in content or "slots" in content:
        bet = None
        won = None
        bet_search = re.search(r"bet\s*:cowoncy:\s*(\d+(?:,\d{3})*)", content)
        if bet_search:
            bet = int(bet_search.group(1).replace(",", ""))
        won_search = re.search(r"and won(?:\s*:cowoncy:\s*(\d+(?:,\d{3})*))?", content)
        if won_search:
            if won_search.group(1):
                won = int(won_search.group(1).replace(",", ""))
            else:
                won = 0
        if bet is not None and won is not None:
            if won == 0:
                return
            elif won == bet:
                return
            elif won > bet:
                session["bets"].append(bet)
                session["winnings"].append(won - bet)
                return
        return

    if embeds:
        for embed in embeds:
            desc = embed.description.lower().replace(",", "") if embed.description else ""
            foot = embed.footer.text.lower().replace(",", "") if embed.footer and embed.footer.text else ""
            bet = None
            bet_search = re.search(r"you bet (\d+(?:,\d{3})*) to play blackjack", desc)
            if bet_search:
                bet = int(bet_search.group(1).replace(",", ""))
            if bet is None:
                continue
            if "you won" in foot:
                session["bets"].append(bet)
                session["winnings"].append(bet * 2)
                return
            elif "you lost" in foot:
                session["bets"].append(bet)
                session["lost"].append(bet)
                return
            elif "you tied" in foot or "you both bust" in foot:
                return

bot.run(DISCORD_TOKEN)
