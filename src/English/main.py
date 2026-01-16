import os
import asyncio
import random
import csv
from datetime import datetime, timezone
from typing import Optional, Dict, Tuple, Set

import discord
from discord import app_commands
from discord.ext import commands
import cv2

_BASE_DIR = os.path.dirname(__file__)
_TOKEN_PATH = os.path.join(_BASE_DIR, "token.txt")
_QUOTES_CSV_PATH = os.path.join(_BASE_DIR, "quotes.csv")
_TILLEY_DIR = os.path.join(_BASE_DIR, "tilley")
_BADAPPLE_PATH = os.path.join(_BASE_DIR, "badapple.mp4")

_BADAPPLE_ASCII_CHARS = " .:-=+*#%@"
_BADAPPLE_WIDTH = 49
_BADAPPLE_HEIGHT = 20
_BADAPPLE_FPS = 30
_BADAPPLE_BUFFER_SECONDS = 5
_BADAPPLE_SEND_INTERVAL = 5.0  # seconds between messages
_BADAPPLE_MAX_QUEUE = _BADAPPLE_FPS * _BADAPPLE_BUFFER_SECONDS

TOKEN: Optional[str] = None
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
_badapple_tasks: Dict[int, Tuple[asyncio.Event, asyncio.Task, asyncio.Task]] = {}
_synced_once = False


def _display_name(user: discord.abc.User) -> str:
    return getattr(user, "display_name", user.name)


def _load_token() -> str:
    with open(_TOKEN_PATH, "r", encoding="utf-8") as f:
        token = f.read().strip()
    if not token:
        raise RuntimeError("Discord token missing")
    return token


TOKEN = _load_token()


@bot.event
async def on_ready():
    global _synced_once
    if _synced_once:
        return
    try:
        synced = await bot.tree.sync()
        print(f"Global commands synced: {len(synced)}")
        print(f"Logged in as {bot.user} (id={bot.user.id})")
        _synced_once = True
    except Exception as e:  # noqa: BLE001
        print(f"Sync failed: {e}")

@bot.tree.command(name="peap", description="Peaper")
async def peap(interaction: discord.Interaction):
    await interaction.response.send_message("peap")


@bot.tree.command(name="tilley", description="Send a random Tilley image")
async def tilley(interaction: discord.Interaction):
    if not os.path.isdir(_TILLEY_DIR):
        await interaction.response.send_message("No Tilley folder found.", ephemeral=True)
        return

    files = [
        os.path.join(_TILLEY_DIR, f)
        for f in os.listdir(_TILLEY_DIR)
        if os.path.isfile(os.path.join(_TILLEY_DIR, f))
        and f.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))
    ]

    if not files:
        await interaction.response.send_message("No Tilley images available.", ephemeral=True)
        return

    choice = random.choice(files)
    await interaction.response.send_message(file=discord.File(choice))


def _frame_to_ascii(frame, width: int = _BADAPPLE_WIDTH, height: int = _BADAPPLE_HEIGHT) -> str:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if gray.size == 0:
        return ""

    resized = cv2.resize(gray, (width, height), interpolation=cv2.INTER_AREA)
    scale = (len(_BADAPPLE_ASCII_CHARS) - 1) / 255
    lines = [
        "".join(_BADAPPLE_ASCII_CHARS[int(px * scale)] for px in row)
        for row in resized
    ]
    return "\n".join(lines)


async def _badapple_producer(queue: asyncio.Queue, stop_event: asyncio.Event):
    cap = cv2.VideoCapture(_BADAPPLE_PATH)
    try:
        while not stop_event.is_set():
            if queue.qsize() >= _BADAPPLE_MAX_QUEUE:
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
    channel = msg.channel
    while not stop_event.is_set():
        frame = await queue.get()
        if frame is None:
            break
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

        await asyncio.sleep(_BADAPPLE_SEND_INTERVAL)
    stop_event.set()


@bot.tree.command(name="badapple", description="Play Bad Apple!!")
async def badapple(interaction: discord.Interaction):
    channel = interaction.channel
    if channel is None:
        await interaction.response.send_message("No channel to send Bad Apple to.", ephemeral=True)
        return

    existing = _badapple_tasks.get(channel.id)
    if existing:
        stop_event, prod_task, cons_task = existing
        if not stop_event.is_set():
            await interaction.response.send_message(
                "Bad Apple is already playing in this channel", ephemeral=True
            )
            return

    await interaction.response.defer(thinking=True)
    queue: asyncio.Queue = asyncio.Queue(maxsize=_BADAPPLE_MAX_QUEUE)
    stop_event = asyncio.Event()
    producer = asyncio.create_task(_badapple_producer(queue, stop_event))

    first_frame = await queue.get()
    if first_frame is None:
        stop_event.set()
        producer.cancel()
        await interaction.followup.send("Could not load Bad Apple frames.", ephemeral=True)
        return

    playback_message = await interaction.followup.send(f"```{first_frame}```")
    _badapple_tasks[channel.id] = (
        stop_event,
        producer,
        asyncio.create_task(_badapple_sender(playback_message, queue, stop_event)),
    )


@bot.tree.command(name="stopapple", description="Stop Bad Apple printing")
async def stopapple(interaction: discord.Interaction):
    channel = interaction.channel
    if channel is None:
        await interaction.response.send_message("No channel to stop.", ephemeral=True)
        return

    existing = _badapple_tasks.get(channel.id)
    if not existing:
        await interaction.response.send_message(
            "Bad Apple isn't running in this channel", ephemeral=True
        )
        return

    stop_event, prod_task, send_task = existing
    stop_event.set()
    for task in (prod_task, send_task):
        if task and not task.done():
            task.cancel()
    _badapple_tasks.pop(channel.id, None)
    await interaction.response.send_message("Bad Apple stopped in this channel", ephemeral=True)


@bot.tree.command(name="quote", description="Send a random text quote.")
@app_commands.describe(user="User to get the quote from (optional)", include_id="Include snowflake id")
async def quote(
    interaction: discord.Interaction,
    user: Optional[discord.User] = None,
    include_id: Optional[bool] = False,
):
    rows = []
    with open(_QUOTES_CSV_PATH, "r", encoding="utf-8", newline="") as f:
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
        target = _display_name(user)
        rows = [r for r in rows if r[1] == target]

    # Worst case scenario the csv/sql or whatever we're using fucked itself over
    if not rows:
        await interaction.response.send_message("The program went up in flames.", ephemeral=True)
        return

    quote_text, author_name, unix_ts_str, snowflake = random.choice(rows)

    try:
        unix_ts = int(float(unix_ts_str))
        dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
        date_str = dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:  # fallback
        date_str = unix_ts_str

    msg = f"{quote_text} \\- {author_name} said on {date_str}"
    if include_id:
        msg += f" (snowflake: {snowflake})"

    await interaction.response.send_message(msg)


@bot.tree.context_menu(name="Add a quote")
async def add_quote(interaction: discord.Interaction, message: discord.Message):
    author_name = _display_name(message.author)
    created_ts = message.created_at.replace(tzinfo=timezone.utc).timestamp()
    with open(_QUOTES_CSV_PATH, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([message.content.strip(), author_name, created_ts, message.id])

    await interaction.response.send_message("Quote noted", ephemeral=True)


@bot.tree.command(name="add_quote_poll")
async def add_quote_poll(interaction: discord.Interaction, message: str, author: discord.User):
    quote_text = message.strip()
    author_name = _display_name(author)
    needed = 3
    poll_text = (
        f'Did the quote actually happen irl?\n"{quote_text}" \\- {author_name}\nNeeds {needed} 👍 votes to confirm'
    )

    quote_embed = discord.Embed(
        title="Quote Poll",
        description=quote_text,
        color=discord.Color.blurple(),
    )

    class PollView(discord.ui.View):
        def __init__(self, base_content: str):
            super().__init__(timeout=None)
            self.base_content = base_content
            self.yes = 0
            self.no = 0
            self.completed = False

        def _status(self) -> str:
            return f"👍 Yes: {self.yes}\n👎 No: {self.no}"

        def _embed(self, extra: Optional[str] = None) -> discord.Embed:
            description = f"{self.base_content}\n\n{self._status()}"
            if extra:
                description += f"\n\n{extra}"
            return discord.Embed(description=description, color=discord.Color.blurple())

        async def _edit(self, interaction: discord.Interaction, extra: Optional[str] = None) -> None:
            embed = self._embed(extra)
            try:
                if interaction.response.is_done():
                    await interaction.edit_original_response(embed=embed, view=self)
                else:
                    await interaction.response.edit_message(embed=embed, view=self)
            except discord.NotFound:
                return

        async def _maybe_complete(self, interaction: discord.Interaction) -> bool:
            if self.completed:
                return True
            if self.yes >= needed:
                self.completed = True
                for child in self.children:
                    child.disabled = True
                with open(_QUOTES_CSV_PATH, "a", encoding="utf-8", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(
                        [
                            quote_text,
                            author_name,
                            datetime.now(tz=timezone.utc).timestamp(),
                            interaction.message.id if interaction.message else 0,
                        ]
                    )
                await self._edit(interaction, "Quote added successfully, 👍 threshold reached")
                return True
            return False

        @discord.ui.button(label="👍 Yes", style=discord.ButtonStyle.green)
        async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.yes += 1
            if await self._maybe_complete(interaction):
                return
            await self._edit(interaction)

        @discord.ui.button(label="👎 No", style=discord.ButtonStyle.red)
        async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.no += 1
            await self._edit(interaction)

    view = PollView(poll_text)

    await interaction.response.send_message(
        embed=view._embed(),
        view=view,
        ephemeral=False,
    )


if __name__ == "__main__":
    bot.run(TOKEN)