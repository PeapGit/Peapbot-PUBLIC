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
import datetime, pytz
import csv

_base_dir = os.path.dirname(__file__)
_token_file = os.path.join(_base_dir, "token.txt")
TOKEN = None
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
_quotes_csv_path = os.path.join(_base_dir, "quotes.csv")

with open(_token_file, "r", encoding="utf-8") as f:
    TOKEN = f.read().strip()
    if not TOKEN:
        print("no token")
        exit(1)

# This can only run on my server and fairview linux club server PERIOD
# For security reasons............
# GUILD_ID = [1276099166522572832, 1157073803382378597] when fairview server is added this will be uncommented
GUILD_ID = [1276099166522572832]
_badapple_path = os.path.join(_base_dir, "badapple.mp4")
_badapple_tasks: Dict[int, tuple] = {}
_badapple_ascii_chars = " .:-=+*#%@"
_badapple_width = 49
_badapple_height = 20
_badapple_fps = 30
_badapple_buffer_seconds = 5
_badapple_send_interval = 5.0  # seconds between edits
_badapple_max_queue = _badapple_fps * _badapple_buffer_seconds

# Some may ask why this is a function, I say im not gonna type discord.object... every fucking time
def guildo():
    return [discord.Object(id=g) for g in GUILD_ID]

@bot.event
async def on_ready():
    # I HATE ERROR HANDLING
    try:
        total = 0
        for guild_obj in guildo():
            synced = await bot.tree.sync(guild=guild_obj)
            total += len(synced)

        print(f"Total commands synced: {total}")
        print(f"Logged in as {bot.user}, ID: {bot.user.id}")
    except Exception as e:
        print(f"Sync failed: {e}")

@bot.tree.command(
    name="peap",
    description="Peaper",
    guilds=guildo()
)
async def peap(interaction: discord.Interaction):
    await interaction.response.send_message("peap")

_accounts_path = os.path.join(_base_dir, "accounts.txt")
_tilley_dir = os.path.join(_base_dir, "tilley")

@bot.tree.command(
    name="tilley",
    description="Send a random Tilley image",
    guilds=guildo()
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

def _frame_to_ascii(frame, width: int = _badapple_width, height: int = _badapple_height) -> str:

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if gray.size == 0:
        return ""

    resized = cv2.resize(gray, (width, height), interpolation=cv2.INTER_AREA)
    scale = (len(_badapple_ascii_chars) - 1) / 255
    lines = [
        "".join(_badapple_ascii_chars[int(px * scale)] for px in row)
        for row in resized
    ]
    return "\n".join(lines)

async def _badapple_producer(queue: asyncio.Queue, stop_event: asyncio.Event):
    # Sometimes try is necessary as it needs to stop if something goes wrong
    cap = cv2.VideoCapture(_badapple_path)
    try:
        while not stop_event.is_set():
            if queue.qsize() >= _badapple_max_queue:
                await asyncio.sleep(0.05)
                continue

            ok, frame = await asyncio.to_thread(cap.read)
            if not ok:
                break

            ascii_frame = await asyncio.to_thread(_frame_to_ascii, frame)
            await queue.put(ascii_frame)
    finally:
        cap.release()
        await queue.put(None)

async def _badapple_sender(msg: discord.Message, queue: asyncio.Queue, stop_event: asyncio.Event):
    frame_interval = _badapple_send_interval
    channel = msg.channel
    while not stop_event.is_set():
        frame = await queue.get()
        if frame is None:
            break
        # I FUCKING HATE RATE LIMITS WHY DO THEY EXIST FUCKING QI#EHJGOIQHERGOL
        try:
            await channel.send(f"```{frame}```")
        except discord.HTTPException as e:
            if e.status == 429 and hasattr(e, "retry_after"):
                await asyncio.sleep(getattr(e, "retry_after", 1))
                try:
                    await channel.send(f"```{frame}```")
                except Exception:
                    break
            else:
                break
        except Exception:
            break

        await asyncio.sleep(frame_interval)
    stop_event.set()

@bot.tree.command(
    name="badapple",
    description="Play Bad Apple!!",
    guilds=guildo()
)
async def badapple(interaction: discord.Interaction):
    channel = interaction.channel
    existing = _badapple_tasks.get(channel.id)
    if existing:
        stop_event, prod_task, cons_task = existing
        if not stop_event.is_set():
            await interaction.response.send_message("Bad Apple is already playing in this channel", ephemeral=True)
            return

    await interaction.response.defer(thinking=True)
    queue: asyncio.Queue = asyncio.Queue(maxsize=_badapple_max_queue)
    stop_event = asyncio.Event()
    producer = asyncio.create_task(_badapple_producer(queue, stop_event))

    first_frame = await queue.get()

    playback_message = await interaction.followup.send(f"```{first_frame}```")
    _badapple_tasks[channel.id] = (stop_event, producer, asyncio.create_task(_badapple_sender(playback_message, queue, stop_event)))

@bot.tree.command(
    name="stopapple",
    description="Stop Bad Apple printing",
    guilds=guildo()
)
async def stopapple(interaction: discord.Interaction):
    channel = interaction.channel

    existing = _badapple_tasks.get(channel.id)
    if not existing:
        # I swear the next thing your gonna ask is an param which stops it in a channel you specify even though
        # THAT IS USELESS and if you can't type it in the correct channel you are a retard
        await interaction.response.send_message("Bad Apple isn't running in this channel", ephemeral=True)
        return

    stop_event, prod_task, send_task = existing
    stop_event.set()
    for task in (prod_task, send_task):
        if task and not task.done():
            task.cancel()
    _badapple_tasks.pop(channel.id, None)
    # Baddy appley has been stoopyed in this channely
    await interaction.response.send_message("Bad apple == stopped in channel", ephemeral=True)

@bot.tree.command(
    name="quote",
    description="Send a random text quote.",
    guilds=guildo()
)
@app_commands.describe(
    user="User to get the quote from (optional)"
)

async def quote(
    interaction: discord.Interaction,
    user: Optional[discord.Member] = None,
    include_id: Optional[bool] = False,
):
    rows = []
    with open(_quotes_csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        for r in reader:
            if len(r) < 4:
                continue
            quote_text, author_name, unix_ts_str, snowflake = (
                r[0].strip(),
                r[1].strip(),
                r[2].strip(),
                r[3].strip(),
            )
            if not quote_text:
                continue
            rows.append((quote_text, author_name, unix_ts_str, snowflake))

    if user:
        target = user.display_name
        rows = [r for r in rows if r[1] == target]

    if not rows:
        await interaction.response.send_message("Error code YOU-ARE-FUCKED, aka your fucked", ephemeral=True)
        return

    quote_text, author_name, unix_ts_str, snowflake = random.choice(rows)

    try:
        unix_ts = int(float(unix_ts_str))
        dt = datetime.datetime.fromtimestamp(unix_ts, tz=datetime.timezone.utc)
        date_str = dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        date_str = unix_ts_str

    msg = f"{quote_text} \\- {author_name} said on {date_str}"
    if include_id:
        msg += f" (snowflake: {snowflake})"


    await interaction.response.send_message(msg)

@bot.tree.context_menu(name="Add a quote", guilds=guildo())
async def add_quote(interaction: discord.Interaction, message: discord.Message):


    with open(_quotes_csv_path, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([message.content.strip(), message.author.display_name, message.created_at.replace(tzinfo=datetime.timezone.utc).timestamp(), message.id])

    await interaction.response.send_message("Quote noted", ephemeral=True)

@bot.tree.command(name="add_quote_poll", guilds=guildo())
async def add_quote_poll(interaction: discord.Interaction, message: str, author: discord.Member):
    quote_text = message.strip()

    await interaction.response.send_message(
        f"Did the quote actually happen?\n\"{quote_text}\"\n- {author.display_name}\n Needs 3 ✅ reactions (4 below on the thing) to confirm",
        ephemeral=False,
    )
    poll_message = await interaction.original_response()

    await poll_message.add_reaction("✅")

    needed = 3
    timeout_seconds = 86400

    yes_voters: set[int] = set()

    def check(payload: discord.RawReactionActionEvent) -> bool:
        if payload.message_id != poll_message.id:
            return False
        return str(payload.emoji) == "✅"

    async def refresh_yes_voters() -> None:
        yes_voters.clear()
        poll_message_fresh = await poll_message.channel.fetch_message(poll_message.id)
        for reaction in poll_message_fresh.reactions:
            if str(reaction.emoji) != "✅":
                continue
            async for user in reaction.users():
                if not user.bot:
                    yes_voters.add(user.id)

    deadline = asyncio.get_running_loop().time() + timeout_seconds

    try:
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError

            await bot.wait_for("raw_reaction_add", timeout=remaining, check=check)
            await refresh_yes_voters()

            if len(yes_voters) >= needed:
                with open(_quotes_csv_path, "a", encoding="utf-8", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(
                        [
                            quote_text,
                            author.display_name,
                            datetime.datetime.now(tz=datetime.timezone.utc).timestamp(),
                            poll_message.id,
                        ]
                    )
                await poll_message.edit(content="Quote added successfully, 3 ✅ reached")
                break

    except asyncio.TimeoutError:
        await poll_message.edit(
            content=f"Poll timed out, quote not added (✅ {len(yes_voters)}/{needed})"
        )

if __name__ == "__main__":
    bot.run(TOKEN)