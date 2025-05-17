import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import re
import logging
from pymongo import MongoClient
from datetime import datetime, timezone
from dotenv import load_dotenv
import os

load_dotenv()

BOT_TOKEN = os.getenv("DISCORD_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_USER_ID = 408785106942164992
MSG_LOG_WORDS = ["won", "lost", "tied", "bust"]
TRACKING_INTERVAL = 2

mongo_client = MongoClient(MONGO_URI)
db = mongo_client["Winningtrack"]
sessions_collection = db["Sessions"]

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True

bot = commands.Bot(command_prefix="/", intents=intents)
tree = bot.tree

session_data = {
    "active": False,
    "channel_id": None,
    "logged_messages": set(),
    "gain": 0,
    "loss": 0,
    "start_time": None
}

def remove_angle_brackets(text):
    return re.sub(r"<[^>]*>", "", text)

def extract_amount(pattern, text):
    cleaned_text = text.replace(",", "")
    match = re.search(pattern, cleaned_text)
    return int(match.group(1)) if match else 0

def detect_game_type(cleaned_content: str):
    if "dealer" in cleaned_content.lower():
        return "blackjack"
    elif "bet" in cleaned_content and "dealer" not in cleaned_content:
        return "slots"
    elif "spent" in cleaned_content:
        return "coinflip"
    return None

def calculate_gain_loss(game_type: str, cleaned_content: str):
    # Ignore tied or both bust results
    if "tied" in cleaned_content.lower() or "you both bust" in cleaned_content.lower():
        return 0, 0

    # Handle Blackjack separately
    if game_type == "blackjack":
        win_match = re.search(r"~\s*you won\s*(\d+)\s*cowoncy", cleaned_content, re.IGNORECASE)
        loss_match = re.search(r"~\s*you lost\s*(\d+)\s*cowoncy", cleaned_content, re.IGNORECASE)

        if win_match:
            gain = int(win_match.group(1))
            return gain, 0
        elif loss_match:
            loss = int(loss_match.group(1))
            return 0, loss

        return 0, 0

    # Extract amounts for coinflip and slots
    bet = extract_amount(r"(?:spent|bet)[^\d]*(\d+)", cleaned_content)
    won = extract_amount(r"won[^\d]*(\d+)", cleaned_content)

    # Slots: specifically check for 'won nothing'
    if game_type == "slots" and "won nothing" in cleaned_content.lower():
        return 0, bet

    # Coinflip or Slots: lost
    if "lost" in cleaned_content.lower():
        return 0, bet

    # Coinflip or Slots: won
    if "won" in cleaned_content.lower():
        return won - bet, 0  # Net gain = winnings - bet

    return 0, 0

@tree.command(name="initialize", description="Start tracking OwO game messages")
async def initialize(interaction: discord.Interaction):
    session_data["active"] = True
    session_data["channel_id"] = interaction.channel_id
    session_data["logged_messages"].clear()
    session_data["gain"] = 0
    session_data["loss"] = 0
    session_data["start_time"] = datetime.now(timezone.utc)

    await interaction.response.send_message("Session has started", ephemeral=False)
    logger.info(f"/initialize received in channel {interaction.channel_id} at {session_data['start_time']}")

@tree.command(name="result", description="End tracking and show session result")
async def result(interaction: discord.Interaction):
    session_data["active"] = False

    total_gain = session_data["gain"]
    total_loss = session_data["loss"]
    net = total_gain - total_loss

    await interaction.response.send_message(
        f"Session ended.\nTotal Gain: {total_gain}\nTotal Loss: {total_loss}\nNet: {net}", ephemeral=False
    )

    sessions_collection.insert_one({
        "timestamp": datetime.now(timezone.utc),
        "channel_id": session_data["channel_id"],
        "gain": total_gain,
        "loss": total_loss,
        "net": net
    })

    session_data["channel_id"] = None
    session_data["logged_messages"].clear()
    session_data["gain"] = 0
    session_data["loss"] = 0
    session_data["start_time"] = None

    logger.info("Session results saved to MongoDB and session data wiped.")

@tasks.loop(seconds=TRACKING_INTERVAL)
async def monitor_messages():
    if not session_data["active"]:
        return

    channel = bot.get_channel(session_data["channel_id"])
    if not channel:
        logger.warning("Invalid channel ID")
        return

    async for message in channel.history(limit=20):
        if message.created_at.replace(tzinfo=timezone.utc) < session_data["start_time"]:
            continue

        if message.author.id != BOT_USER_ID or message.id in session_data["logged_messages"]:
            continue

        content = message.content or ""
        if message.embeds:
            for embed in message.embeds:
                if embed.title:
                    content += f"\n{embed.title}"
                if embed.description:
                    content += f"\n{embed.description}"
                if embed.footer and embed.footer.text:
                    content += f"\n{embed.footer.text}"
                if embed.fields:
                    for field in embed.fields:
                        content += f"\n{field.name} {field.value}"

        cleaned_content = remove_angle_brackets(content).lower()

        if any(word in cleaned_content for word in MSG_LOG_WORDS):
            session_data["logged_messages"].add(message.id)
            logger.info("---- Detected OwO Message ----")
            logger.info(content)
            logger.info("--------------------------------")

            game_type = detect_game_type(cleaned_content)
            if game_type:
                gain, loss = calculate_gain_loss(game_type, cleaned_content)
                session_data["gain"] += gain
                session_data["loss"] += loss

                logger.info(f"Updated -> Gain: {session_data['gain']} | Loss: {session_data['loss']} | Net: {session_data['gain'] - session_data['loss']}")

@bot.event
async def on_ready():
    await tree.sync()
    monitor_messages.start()
    logger.info(f"Bot is ready. Logged in as {bot.user}")

bot.run(BOT_TOKEN)
