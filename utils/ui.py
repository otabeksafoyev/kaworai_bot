"""
utils/ui.py — kichik UI yordamchilar: yulduzli reyting, progress chizig'i,
vaqtga qarab salomlashish, start-argumentlarni tahlil qilish va ulashish havolalari.
"""

from __future__ import annotations

import os
import re
from contextvars import ContextVar
from datetime import datetime, timedelta

BOT_USERNAME = os.getenv("BOT_USERNAME", "kaworai_uz_bot")

# Joriy update egasi — middleware o'rnatadi. Klaviatura quruvchilar (ulashish tugmasi)
# shu orqali havolaga taklif qiluvchi ID sini qo'shadi, har bir chaqiruvga user_id uzatmasdan.
current_user_id: ContextVar[int | None] = ContextVar("current_user_id", default=None)


def rating_stars(rating: float | None, scale: int = 10) -> str:
    """8.9 (10 ballik) → '★★★★★' ; 6.0 → '★★★☆☆'."""
    r = max(0.0, min(float(rating or 0.0), float(scale)))
    filled = int(round(r / scale * 5))
    return "★" * filled + "☆" * (5 - filled)


def progress_bar(done: int, total: int, width: int = 8) -> str:
    """4/12 → '▰▰▰▱▱▱▱▱'."""
    if total <= 0:
        return "▱" * width
    filled = int(round(max(0, min(done, total)) / total * width))
    if done > 0:
        filled = max(filled, 1)
    return "▰" * filled + "▱" * (width - filled)


def greeting(now: datetime | None = None) -> str:
    """O'zbekiston vaqti (UTC+5) bo'yicha salom."""
    local = (now or datetime.utcnow()) + timedelta(hours=5)
    h = local.hour
    if 5 <= h < 11:
        return "🌅 Xayrli tong"
    if 11 <= h < 17:
        return "☀️ Xayrli kun"
    if 17 <= h < 22:
        return "🌆 Xayrli kech"
    return "🌙 Xayrli tun"


_ANIME_ARG = re.compile(r"^anime_(\d+)(?:_r(\d+))?$")
_KOD_ARG = re.compile(r"^kod_(\d+)$")
_REF_ARG = re.compile(r"^ref_(\d+)$")


def parse_start_args(args: str | None) -> tuple[int | None, int | None]:
    """
    /start argumentidan (anime_id, referrer_id) ni ajratadi.
      anime_623        → (623, None)
      anime_623_r555   → (623, 555)
      ref_555          → (None, 555)
      kod_623 / 623    → (623, None)
    """
    args = (args or "").strip()
    if m := _ANIME_ARG.match(args):
        return int(m.group(1)), int(m.group(2)) if m.group(2) else None
    if m := _REF_ARG.match(args):
        return None, int(m.group(1))
    if m := _KOD_ARG.match(args):
        return int(m.group(1)), None
    if args.isdigit():
        return int(args), None
    return None, None


def _ref_suffix() -> str:
    uid = current_user_id.get()
    return f"_r{uid}" if uid else ""


def anime_start_link(anime_id: int) -> str:
    """https://t.me/bot?start=anime_ID[_rUID] — ochiq havola."""
    return f"https://t.me/{BOT_USERNAME}?start=anime_{anime_id}{_ref_suffix()}"


def share_anime_url(anime_id: int) -> str:
    """Telegram 'ulashish' oynasini ochuvchi URL (tugma uchun)."""
    return f"https://t.me/share/url?url=https://t.me/{BOT_USERNAME}%3Fstart%3Danime_{anime_id}{_ref_suffix()}"


def referral_link(user_id: int) -> str:
    return f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"


# ─── Tugma yozuvlari: emoji → oddiy belgi ─────────────────────────────
_EMOJI_RE = re.compile(
    r"[\U0001F000-\U0001FAFF\u2139\u2190-\u21FF\u2300-\u23FF\u25A0-\u25FF\u2600-\u27BF\u2B00-\u2BFF\u2934\u2935]"
    r"\uFE0F?(?:\u200D[\U0001F000-\U0001FAFF\u2600-\u27BF]\uFE0F?)*"
)
_SYMBOLS = {
    "⬅": "ᐊ",
    "◀": "ᐊ",
    "🔙": "ᐊ",
    "↩": "ᐊ",
    "➡": "ᐅ",
    "▶": "ᐅ",
    "⏭": "ᐅ",
    "📢": "ᐅ",
    "📣": "ᐅ",
    "📰": "ᐅ",
    "✉": "ᐅ",
    "⬇": "ᐁ",
    "⬆": "ᐃ",
    "❌": "✕",
    "🚫": "✕",
    "🗑": "✕",
    "🧹": "✕",
    "✅": "✓",
    "☑": "✓",
    "👍": "✓",
    "➕": "+",
    "🆕": "+",
    "✏": "✎",
    "✍": "✎",
    "📝": "✎",
    "🏠": "⌂",
    "🔍": "⌕",
    "🔎": "⌕",
    "🔄": "↻",
    "⭐": "★",
    "❤": "♡",
    "❤‍🔥": "♡",
    "💔": "♡",
    "🔒": "⊘",
    "🔗": "↗",
    "📤": "↗",
    "⚡": "ϟ",
    "💎": "◆",
    "🔥": "✦",
    "🎁": "✦",
    "✨": "✦",
    "🧧": "✦",
    "🎬": "๏",
    "🎞": "๏",
    "🎥": "๏",
    "📺": "๏",
    "🎌": "๏",
    "🌸": "๏",
    "📖": "๏",
    "📋": "≡",
    "📂": "≡",
    "📄": "≡",
    "📦": "≡",
    "📊": "◈",
    "📈": "◈",
    "📉": "◈",
    "⚙": "◈",
    "🤖": "◈",
    "👥": "◉",
    "👤": "◉",
    "🤝": "◉",
    "👁": "◉",
    "🏷": "#",
    "🖼": "▣",
    "📸": "▣",
    "🎨": "▣",
    "⏳": "◌",
    "📡": "◌",
    "🔢": "№",
    "🌙": "☾",
    "😴": "☾",
    "😌": "☺",
    "🌍": "◎",
    "📍": "◎",
    "📅": "◎",
    "⚠": "!",
    "🟢": "●",
    "▫": "○",
    "💾": "⇩",
    "🎲": "◇",
    "☀": "☼",
    "⛔": "✕",
    "ℹ": "ⓘ",
}


def sym(text: str) -> str:
    """Tugma matnidagi emojilarni ᐅ ๏ ✓ ✕ kabi oddiy belgilarga almashtiradi (xaritada yo'qlari — ๏)."""
    return _EMOJI_RE.sub(lambda m: _SYMBOLS.get(m.group(0).replace("\uFE0F", ""), "๏"), text)


def genre_sym(text: str) -> str:
    """Janr nomlari uchun: har qanday emoji o'rniga bir xil ๏ belgisi."""
    return _EMOJI_RE.sub("๏", text)
