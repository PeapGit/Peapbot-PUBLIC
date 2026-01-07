# Compact Discord bot variant that shares assets from project root; implements encode/decode plus quotes and images.
import os
import discord
from discord.ext import commands
from discord import app_commands
import random
import base64
from typing import Optional, List

# Use the project root for shared assets (token, accounts, cache, tilley folder).
_base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_token_file = os.path.join("token.txt")
# Load token once; exit early if missing so the bot never runs without credentials.
TOKEN = None
try:
    with open(_token_file, "r", encoding="utf-8") as f:
        TOKEN = f.read().strip()
        if not TOKEN:
            TOKEN = None
except FileNotFoundError:
    TOKEN = None

if TOKEN is None:
    print("token.txt not found or empty, exiting.")
    exit(1)

# Standard intents cover slash commands; no privileged intents required.
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    # Sync global application commands so users see the latest definitions.
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} global commands.")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

    print(f"Logged in as {bot.user} (ID: {bot.user.id})")


@bot.tree.command(name="peap", description="Peaper")
async def peap(interaction: discord.Interaction):
    await interaction.response.send_message("peap")


# Special password enforced for users listed in accounts.txt when they omit a password.
SPECIAL_PASSWORD = 'oBQ69N7aE"\\S'

# Paths and simple caches for accounts, images, and quotes to avoid repeated disk I/O.
_accounts_path = os.path.join(_base_dir, "accounts.txt")
_cached_accounts: Optional[List[str]] = None
_tilley_dir = os.path.join(_base_dir, "tilley")
_quotes_path = os.path.join(_base_dir, "quotes.txt")
_cached_quotes: Optional[List[str]] = None


def _load_accounts_safe() -> List[str]:
    """Return cached accounts list; fall back to empty on read errors."""
    try:
        return load_accounts()
    except Exception:
        return []


def resolve_effective_password(username: str, provided_password: Optional[str], accounts: List[str]) -> str:
    """Apply accounts.txt override rules once and reuse in commands."""
    provided = provided_password or ""
    if username in accounts and provided == "":
        return SPECIAL_PASSWORD
    return provided


def load_accounts() -> List[str]:
    global _cached_accounts
    if _cached_accounts is not None:
        return _cached_accounts

    if not os.path.exists(_accounts_path):
        _cached_accounts = []
        return _cached_accounts

    with open(_accounts_path, "r", encoding="utf-8") as acc_file:
        _cached_accounts = [line.strip() for line in acc_file if line.strip()]
    return _cached_accounts


def load_quotes() -> List[str]:
    global _cached_quotes
    if _cached_quotes is not None:
        return _cached_quotes
    if not os.path.exists(_quotes_path):
        _cached_quotes = []
        return _cached_quotes
    with open(_quotes_path, "r", encoding="utf-8") as quotes_file:
        _cached_quotes = [line.strip() for line in quotes_file if line.strip()]
    return _cached_quotes


def compute_base_l_from_string(source: str) -> int:
    # Derive base L from any string by summing the lengths of Unicode identifiers for every character.
    if not source:
        raise ValueError("Base L source string is empty.")
    total = 0
    for ch in source:
        cp = ord(ch)
        ident = f"U+{cp:04X}"
        total += len(ident)
    return total


def encode_text_to_payload(text: str, base_source: Optional[str]) -> (str, int):
    # Encode text per the custom spec: derive L, convert to hex digits, treat as base-L integer, transform, and base64 wrap.
    if base_source is not None and base_source != "":
        l_source = base_source
    else:
        l_source = text

    L = compute_base_l_from_string(l_source)
    if L <= 15:
        L = 16

    hex_parts: List[str] = []
    for ch in text:
        cp = ord(ch)
        ident = f"U+{cp:04X}"
        hex_part = ident[2:]
        hex_parts.append(hex_part)

    # Concatenate all per-character hex segments to form a long digit string.
    hex_concat = "".join(hex_parts)
    hex_length = len(hex_concat)

    # Interpret that string as a number in base L; every hex digit must be < L.
    value = 0
    for c in hex_concat:
        digit = int(c, 16)
        if digit >= L:
            raise ValueError("Base L is too small for the provided text/password combination.")
        value = value * L + digit

    # Convert the base-L number to raw bytes, tracking exact lengths for lossless decode.
    if value == 0:
        value_bytes = b"\x00"
    else:
        byte_len = (value.bit_length() + 7) // 8
        value_bytes = value.to_bytes(byte_len, "big")

    payload_bytes = hex_length.to_bytes(4, "big")
    payload_bytes += len(value_bytes).to_bytes(4, "big")
    payload_bytes += value_bytes

    # Record hex and lengths, then perform the mandated first-char shift transform.
    codepoints = list(payload_bytes)
    second_hex_parts: List[str] = []
    lengths: List[int] = []
    for cp in codepoints:
        hex2 = f"{cp:02X}"
        second_hex_parts.append(hex2)
        lengths.append(len(hex2))

    if second_hex_parts:
        first_hex = second_hex_parts[0]
        if not first_hex:
            raise ValueError("First hex segment is unexpectedly empty.")
        first_char = first_hex[0]
        second_hex_parts[0] = first_hex[1:]
        second_hex_parts[-1] = second_hex_parts[-1] + first_char
        lengths[0] -= 1
        lengths[-1] += 1

    transformed_concat = "".join(second_hex_parts)

    # Split back according to recorded lengths and map each group to a Unicode codepoint.
    final_groups: List[str] = []
    cursor = 0
    for length in lengths:
        if length <= 0:
            raise ValueError("Invalid recorded length during encoding.")
        next_cursor = cursor + length
        final_groups.append(transformed_concat[cursor:next_cursor])
        cursor = next_cursor

    if cursor != len(transformed_concat):
        raise ValueError("Length tracking mismatch during encoding.")

    encoded_chars = "".join(chr(int(group, 16) % 0x110000) for group in final_groups)
    safe_encoded = base64.b64encode(encoded_chars.encode("utf-8")).decode("ascii")

    return safe_encoded, L


def _transformed_hex_lengths(count: int) -> List[int]:
    # Reconstruct expected group lengths after the transform: first shortens, last lengthens.
    if count <= 0:
        return []
    if count == 1:
        return [2]
    lengths = [2] * count
    lengths[0] = 1
    lengths[-1] = 3
    return lengths


def decode_payload(encoded: str, base_l: int) -> str:
    # Reverse the encoding pipeline using only the encoded string and base L.
    if base_l <= 15:
        raise ValueError("Base L must be greater than 15.")

    if not encoded:
        return ""

    try:
        encoded_bytes = base64.b64decode(encoded, validate=True)
        encoded_chars = encoded_bytes.decode("utf-8")
    except Exception:
        encoded_chars = encoded  # legacy path without base64

    raw_hex_per_char: List[str] = []
    for ch in encoded_chars:
        raw_hex_per_char.append(f"U+{ord(ch):04X}"[2:])

    lengths = _transformed_hex_lengths(len(encoded_chars))
    if len(lengths) != len(raw_hex_per_char):
        raise ValueError("Length bookkeeping mismatch during decode.")

    transformed_groups: List[str] = []
    for raw_hex, needed_len in zip(raw_hex_per_char, lengths):
        if needed_len <= 0 or needed_len > len(raw_hex):
            raise ValueError("Encoded data is malformed (invalid group length).")
        transformed_groups.append(raw_hex[-needed_len:])

    if transformed_groups:
        if len(transformed_groups) == 1:
            raise ValueError("Encoded data is malformed (truncated payload).")
        if not transformed_groups[-1]:
            raise ValueError("Encoded data is malformed (empty last group).")
        moved_char = transformed_groups[-1][-1]
        transformed_groups[-1] = transformed_groups[-1][:-1]
        if not transformed_groups[-1] or not transformed_groups[0]:
            raise ValueError("Encoded data is malformed (empty group after reversal).")
        transformed_groups[0] = moved_char + transformed_groups[0]

    byte_values = [int(group, 16) for group in transformed_groups]
    payload_bytes = bytes(byte_values)

    if len(payload_bytes) < 8:
        raise ValueError("Encoded payload is too short.")

    hex_length = int.from_bytes(payload_bytes[:4], "big")
    value_len = int.from_bytes(payload_bytes[4:8], "big")

    value_bytes = payload_bytes[8:8 + value_len]
    payload_incomplete = len(value_bytes) < value_len
    if payload_incomplete:
        # If Discord dropped bytes, fall back to whatever survived and still try to decode.
        value_bytes = payload_bytes[8:]

    if not value_bytes:
        raise ValueError("Encoded payload missing integer data.")

    value = int.from_bytes(value_bytes, "big")

    # Convert base-L integer back to hex digits string.
    digits: List[str] = []
    if value == 0:
        digits_str = ""
    else:
        v = value
        while v > 0:
            v, rem = divmod(v, base_l)
            if rem >= 16:
                raise ValueError("Encoded payload is corrupted (digit out of hex range).")
            digits.append("0123456789ABCDEF"[rem])
        digits_str = "".join(reversed(digits))

    min_hex_length = ((len(digits_str) + 3) // 4) * 4 if digits_str else 0

    if payload_incomplete:
        hex_length = min_hex_length
    elif min_hex_length and hex_length < min_hex_length:
        raise ValueError(
            f"Specified hex length ({hex_length}) is shorter than required minimum ({min_hex_length})."
        )

    if hex_length == 0:
        hex_concat = ""
    else:
        hex_concat = digits_str.rjust(hex_length, "0")

    if hex_concat and len(hex_concat) % 4 != 0:
        raise ValueError("Recovered hex length is not multiple of 4.")

    chars: List[str] = []
    for i in range(0, len(hex_concat), 4):
        if i + 4 > len(hex_concat):
            raise ValueError("Recovered hex data is misaligned.")
        cp = int(hex_concat[i:i + 4], 16)
        cp %= 0x110000
        chars.append(chr(cp))

    return "".join(chars)


@bot.tree.command(name="encode", description="Encode text with the specified password rules.")
@app_commands.describe(text="Text to encode", password="Password used to derive L (optional)")
async def encode(interaction: discord.Interaction, text: str, password: Optional[str] = None):
    # Entry point for /encode: derive effective password, encode, and publish result publicly after ephemeral success.
    username = interaction.user.name
    accounts = _load_accounts_safe()
    effective_password = resolve_effective_password(username, password, accounts)

    try:
        encoded_result, base_l = encode_text_to_payload(text, effective_password)
    except Exception as e:
        await interaction.response.send_message(f"Error while encoding: {e}", ephemeral=True)
        return

    await interaction.response.send_message("Success", ephemeral=True)

    public_message = f"{encoded_result}\n{base_l}\n{interaction.user.mention}"
    await interaction.channel.send(public_message, allowed_mentions=discord.AllowedMentions(users=[interaction.user]))


@bot.tree.command(name="decode", description="Decode text produced by /encode.")
@app_commands.describe(
    encoded_text="The encoded string output by /encode (first line).",
    l_value="The base L value output by /encode (second line).",
    password="Password used during encoding (optional, follows account rules)."
)
async def decode(interaction: discord.Interaction, encoded_text: str, l_value: int, password: Optional[str] = None):
    # Validate inputs, check password-derived L if provided, then decode and publish output after ephemeral success.
    username = interaction.user.name
    accounts = _load_accounts_safe()
    effective_password = resolve_effective_password(username, password, accounts)

    try:
        if not encoded_text:
            raise ValueError("Encoded text argument is empty.")
        if l_value <= 0:
            raise ValueError("L must be a positive integer.")

        base_l = l_value

        if effective_password:
            derived_l = max(compute_base_l_from_string(effective_password), 16)
            if derived_l != base_l:
                raise ValueError("Provided password does not match the supplied L value.")

        decoded_text = decode_payload(encoded_text, base_l)

    except Exception as e:
        if not interaction.response.is_done():
            await interaction.response.send_message(f"Error while decoding: {e}", ephemeral=True)
        else:
            await interaction.followup.send(f"Error while decoding: {e}", ephemeral=True)
        return

    await interaction.response.send_message("Decoded successfully", ephemeral=True)
    await interaction.channel.send(f"{decoded_text}\n{interaction.user.mention}", allowed_mentions=discord.AllowedMentions(users=[interaction.user]))


@bot.tree.command(
    name="tilley",
    description="Send a random Tilley image."
)
async def tilley(interaction: discord.Interaction):
    # Randomly choose an image file from the tilley directory and send it if available.
    if not os.path.isdir(_tilley_dir):
        await interaction.response.send_message(
            "No tilley directory found on the bot host.",
            ephemeral=True
        )
        return

    files = [
        os.path.join(_tilley_dir, f)
        for f in os.listdir(_tilley_dir)
        if os.path.isfile(os.path.join(_tilley_dir, f))
        and f.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))
    ]

    if not files:
        await interaction.response.send_message(
            "No images available in the tilley directory.",
            ephemeral=True
        )
        return

    choice = random.choice(files)
    try:
        await interaction.response.send_message(file=discord.File(choice))
    except Exception as e:
        await interaction.response.send_message(
            f"Failed to send image: {e}",
            ephemeral=True
        )


@bot.tree.command(name="quote", description="Send a random quote.")
async def quote(interaction: discord.Interaction):
    # Load cached quotes (or disk) and send one at random; fallback message if none exist.
    quotes = load_quotes()
    if not quotes:
        await interaction.response.send_message("No quotes available.")
        return
    await interaction.response.send_message(random.choice(quotes))


if __name__ == "__main__":
    bot.run(TOKEN)
