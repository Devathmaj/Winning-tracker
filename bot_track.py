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
pending_bets = {}  # To track bets waiting for results

amount_pattern = re.compile(r"(\d{1,3}(?:,\d{3})*|\d+)")

def extract_amount(text):
    text = text.replace(",", "")
    amounts = amount_pattern.findall(text)
    return int(amounts[0]) if amounts else None

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
        "total_won": 0,
        "total_lost": 0,
        "net_gain": 0,
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
    await sessions_collection.insert_one({
        "user_id": str(user_id),
        "start_time": session["start_time"],
        "end_time": datetime.datetime.now(datetime.timezone.utc),
        "total_won": session["total_won"],
        "total_lost": session["total_lost"],
        "net_gain": session["net_gain"]
    })
    await interaction.response.send_message(
        f"**Session Result:**\nTotal Lost: `{session['total_lost']:,}`\nTotal Won (Net Profit): `{session['total_won']:,}`\nNet Gain: `{session['net_gain']:,}`"
    )

@bot.event
async def on_message(message):
    await bot.process_commands(message)

    if message.author.id != OWO_BOT_ID:
        return

    content = message.content
    embeds = message.embeds
    target_user_id = None
    if message.mentions:
        target_user_id = message.mentions[0].id if message.mentions[0].id != OWO_BOT_ID else None

    if not target_user_id or target_user_id not in active_sessions:
        return

    session = active_sessions[target_user_id]

    # COINFLIP
    if "spent :cowoncy:" in content and "chose" in content:
        bet_amount = extract_amount(content)
        if bet_amount:
            pending_bets[target_user_id] = {
                "game": "coinflip",
                "amount": bet_amount,
                "time": datetime.datetime.now(datetime.timezone.utc)
            }
            print(f"[Coinflip] Bet Placed: {bet_amount}")
        return

    if "the coin spins" in content:
        if target_user_id in pending_bets and pending_bets[target_user_id]["game"] == "coinflip":
            bet_info = pending_bets[target_user_id]
            if "you lost it all" in content:
                session["total_lost"] += bet_info["amount"]
                print(f"[Coinflip] Lost: {bet_info['amount']} | Net: {session['total_won'] - session['total_lost']}")
            elif "you won" in content:
                session["total_won"] += bet_info["amount"]
                print(f"[Coinflip] Won: {bet_info['amount']} | Net: {session['total_won'] - session['total_lost']}")
            session["net_gain"] = session["total_won"] - session["total_lost"]
            pending_bets.pop(target_user_id, None)
        return

    # SLOTS
    if "___SLOTS___" in content and "bet :cowoncy:" in content:
        bet_amount = extract_amount(content)
        if bet_amount:
            pending_bets[target_user_id] = {
                "game": "slots",
                "amount": bet_amount,
                "time": datetime.datetime.now(datetime.timezone.utc)
            }
            print(f"[Slots] Bet Placed: {bet_amount}")
        return

    if "and won :cowoncy:" in content:
        if target_user_id in pending_bets and pending_bets[target_user_id]["game"] == "slots":
            bet_info = pending_bets[target_user_id]
            won_amount = extract_amount(content)
            if won_amount:
                net_profit = won_amount - bet_info["amount"]
                session["total_won"] += net_profit
                print(f"[Slots] Won: {net_profit} (Bet: {bet_info['amount']}, Total: {won_amount}) | Net: {session['total_won'] - session['total_lost']}")
                session["net_gain"] = session["total_won"] - session["total_lost"]
                pending_bets.pop(target_user_id, None)
        return

    if "and lost it all" in content:
        if target_user_id in pending_bets and pending_bets[target_user_id]["game"] == "slots":
            bet_info = pending_bets[target_user_id]
            session["total_lost"] += bet_info["amount"]
            print(f"[Slots] Lost: {bet_info['amount']} | Net: {session['total_won'] - session['total_lost']}")
            session["net_gain"] = session["total_won"] - session["total_lost"]
            pending_bets.pop(target_user_id, None)
        return

    # BLACKJACK
    if embeds:
        for embed in embeds:
            description = embed.description or ""
            footer = embed.footer.text if embed.footer else ""

            if "you bet" in description.lower() and "to play blackjack" in description.lower():
                bet_amount = extract_amount(description)
                if bet_amount:
                    pending_bets[target_user_id] = {
                        "game": "blackjack",
                        "amount": bet_amount,
                        "time": datetime.datetime.now(datetime.timezone.utc)
                    }
                    print(f"[Blackjack] Bet Placed: {bet_amount}")
                return

            if "you won" in footer.lower():
                if target_user_id in pending_bets and pending_bets[target_user_id]["game"] == "blackjack":
                    net_profit = extract_amount(footer)
                    if net_profit is not None:
                        session["total_won"] += net_profit
                        print(f"[Blackjack] Won: {net_profit} | Net: {session['total_won'] - session['total_lost']}")
                        session["net_gain"] = session["total_won"] - session["total_lost"]
                        pending_bets.pop(target_user_id, None)
                return

            if "you lost" in footer.lower():
                if target_user_id in pending_bets and pending_bets[target_user_id]["game"] == "blackjack":
                    bet_info = pending_bets[target_user_id]
                    session["total_lost"] += bet_info["amount"]
                    print(f"[Blackjack] Lost: {bet_info['amount']} | Net: {session['total_won'] - session['total_lost']}")
                    session["net_gain"] = session["total_won"] - session["total_lost"]
                    pending_bets.pop(target_user_id, None)
                return

            if "you tied" in footer.lower() or "you both bust" in footer.lower():
                pending_bets.pop(target_user_id, None)
                print("[Blackjack] Tie or Bust - No Change")
                return

bot.run(DISCORD_TOKEN)
