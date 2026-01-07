import os
import discord
from discord.ext import commands
import asyncio
from discord import app_commands
import random
import base64
from typing import Optional, List, Dict
import cv2
import numpy

intents = discord.Intents.default()
_base_dir = os.path.dirname(__file__)
_token_file = os.path.join(_base_dir, "token.txt")
TOKEN = None
bot = commands.Bot(command_prefix="!", intents=intents)

with open(_token_file, "r", encoding="utf-8") as f:
    TOKEN = f.read().strip()
    if not TOKEN:
        TOKEN = None

if TOKEN is None:
    print("no token")
    exit(1)

GUILD_ID = 1276099166522572832
_badapple_path = os.path.join(_base_dir, "badapple.mp4")
_badapple_tasks: Dict[int, tuple] = {}
_badapple_ascii_chars = " .:-=+*#%@"
_badapple_width = 49
_badapple_height = 20
_badapple_fps = 30
_badapple_buffer_seconds = 5
_badapple_send_interval = 5.0
_badapple_max_queue = _badapple_fps * _badapple_buffer_seconds


@bot.event
async def on_ready():
    # I HATE ERROR HANDLING
    try:
        guild_obj = discord.Object(id=GUILD_ID)
        synced = await bot.tree.sync(guild=guild_obj)
        print(f"Synced {len(synced)}")
        print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    except Exception as e:
        print(f"Sync failed: {e}")

@bot.tree.command(
    name="peap",
    description="Peaper",
    guild=discord.Object(id=GUILD_ID)
)
async def peap(interaction: discord.Interaction):
    await interaction.response.send_message("peap")

_accounts_path = os.path.join(_base_dir, "accounts.txt")
_tilley_dir = os.path.join(_base_dir, "tilley")

@bot.tree.command(
    name="tilley",
    description="Send a random Tilley image",
    guild=discord.Object(id=GUILD_ID)
)
async def tilley(interaction: discord.Interaction):
    # All file types and file organization stuff
    files = [
        os.path.join(_tilley_dir, f)
        for f in os.listdir(_tilley_dir)
        if os.path.isfile(os.path.join(_tilley_dir, f))
        and f.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))
    ]

    choice = random.choice(files)
    await interaction.response.send_message(file=discord.File(choice))

if __name__ == "__main__":
    bot.run(TOKEN)