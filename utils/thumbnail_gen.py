"""
utils/thumbnail_gen.py — Qism video thumbnail generatsiyasi

Poster rasm ustiga qism raqamini (doira ichida) yozib,
video thumbnail sifatida ishlatish uchun bytes qaytaradi.

Ishlatish:
    bytes_io = await generate_episode_thumbnail(bot, file_id, episode=3)
    # bytes_io ni send_video(..., thumbnail=bytes_io) ga bersa bo'ladi

Talablar:
    Pillow>=10.0.0 (requirements.txt da bor)
"""

import io
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Thumbnail o'lchami — Telegram tavsiyasi: 320x320, JPEG
THUMB_SIZE = (320, 320)
CIRCLE_RELATIVE_SIZE = 0.28   # Doira diametrining rasmdagi ulushi
FONT_SIZE_RATIO = 0.55         # Doira ichidagi raqam fonti kattaligi (doira diametridan)

# Kunduzgi/kechgi chegara soatlari (UTC+5 — Toshkent)
NIGHT_START_HOUR = 22   # 22:00 dan
NIGHT_END_HOUR = 5      # 05:00 gacha (kecha)


def is_night_time(utc_hour_offset: int = 5) -> bool:
    """
    Hozir kechami yoki kunduzmi?
    utc_hour_offset: UTC dan soat farqi (Toshkent = +5)
    """
    utc_now = datetime.now(timezone.utc)
    local_hour = (utc_now.hour + utc_hour_offset) % 24
    return local_hour >= NIGHT_START_HOUR or local_hour < NIGHT_END_HOUR


async def _download_photo_bytes(bot, file_id: str) -> bytes | None:
    """Telegram photo file_id dan bytes yuklab oladi."""
    try:
        file = await bot.get_file(file_id)
        if not file.file_path:
            return None
        bio = await bot.download_file(file.file_path)
        if hasattr(bio, "read"):
            return bio.read()
        return bytes(bio)
    except Exception as e:
        logger.warning("thumbnail_gen: photo yuklab olishda xato: %s", e)
        return None


def _draw_episode_circle(img, episode: int) -> None:
    """
    Rasm pastki o'ng burchagiga doira va raqam chizadi.
    Pillow ishlatadi.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logger.warning("thumbnail_gen: Pillow o'rnatilmagan — doira chizilmaydi")
        return

    w, h = img.size
    circle_d = int(min(w, h) * CIRCLE_RELATIVE_SIZE)
    font_size = max(int(circle_d * FONT_SIZE_RATIO), 14)

    # Doira pozitsiyasi — pastki o'ng burchak, 8px chet qoldirib
    margin = 8
    x1 = w - circle_d - margin
    y1 = h - circle_d - margin
    x2 = w - margin
    y2 = h - margin

    draw = ImageDraw.Draw(img, "RGBA")

    # Soya — ko'rinishni yaxshilaydi
    shadow_offset = 3
    draw.ellipse(
        [x1 + shadow_offset, y1 + shadow_offset, x2 + shadow_offset, y2 + shadow_offset],
        fill=(0, 0, 0, 100),
    )

    # Asosiy doira — qizg'ish-to'q rang (#E84393 — Kaworai rang sxemasiga mos)
    draw.ellipse([x1, y1, x2, y2], fill=(232, 67, 147, 230))

    # Doira ichki chiziq
    draw.ellipse([x1 + 2, y1 + 2, x2 - 2, y2 - 2], outline=(255, 255, 255, 180), width=2)

    # Raqam — oq rang, markazda
    ep_text = str(episode)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
    except Exception:
        try:
            font = ImageFont.truetype("/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()

    # Matn o'lchamini aniqlash
    bbox = draw.textbbox((0, 0), ep_text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    cx = (x1 + x2) // 2 - tw // 2
    cy = (y1 + y2) // 2 - th // 2

    # Ko'linkar soya
    draw.text((cx + 1, cy + 1), ep_text, font=font, fill=(0, 0, 0, 150))
    # Asosiy matn
    draw.text((cx, cy), ep_text, font=font, fill=(255, 255, 255, 255))


def generate_thumbnail_sync(poster_bytes: bytes, episode: int) -> bytes | None:
    """
    Poster bytes dan thumbnail generatsiya qiladi (sinxron).
    Episode raqamini pastki o'ng burchakda doira ichida chiqaradi.

    Returns:
        bytes: JPEG thumbnail bytes
        None: xato bo'lsa
    """
    try:
        from PIL import Image
    except ImportError:
        logger.error("thumbnail_gen: Pillow o'rnatilmagan!")
        return None

    try:
        # Rasmni ochish
        img = Image.open(io.BytesIO(poster_bytes)).convert("RGBA")

        # Thumbnail o'lchamiga keltirish (nisbatni saqlagan holda)
        img.thumbnail(THUMB_SIZE, Image.LANCZOS)

        # Kvadrat canvas — bo'sh joylar qora bilan to'ldiriladi
        canvas = Image.new("RGBA", THUMB_SIZE, (15, 15, 20, 255))
        offset_x = (THUMB_SIZE[0] - img.width) // 2
        offset_y = (THUMB_SIZE[1] - img.height) // 2
        canvas.paste(img, (offset_x, offset_y), mask=img if img.mode == "RGBA" else None)

        # Doira + raqam chizish
        _draw_episode_circle(canvas, episode)

        # JPEG bytes ga aylantirish
        canvas_rgb = canvas.convert("RGB")
        output = io.BytesIO()
        canvas_rgb.save(output, format="JPEG", quality=88, optimize=True)
        output.seek(0)
        return output.getvalue()

    except Exception as e:
        logger.exception("thumbnail_gen: generatsiya xatosi: %s", e)
        return None


async def generate_episode_thumbnail(
    bot,
    anime_id: int,
    episode: int,
    thumbnail_day_file_id: str | None = None,
    thumbnail_night_file_id: str | None = None,
    poster_file_id: str | None = None,
) -> io.BytesIO | None:
    """
    Qism uchun thumbnail generatsiya qiladi.

    Tanlash tartibi:
    1. Global thumbnail (BotSetting dan) — vaqtga qarab kunduz/kecha
    2. Mos global rasm yo'q → poster_file_id
    3. Bari yo'q bo'lsa → None (Telegram o'z previewini ishlatadi)

    Returns:
        io.BytesIO: send_video(..., thumbnail=...) ga beriladigan bytes
        None: thumbnail generatsiya qilib bo'lmasa
    """
    night = is_night_time()

    # Global thumbnail — BotSetting dan olamiz (anime bo'yicha emas)
    global_day = None
    global_night = None
    try:
        from database.engine import AsyncSessionLocal
        from database.queries import get_global_thumbnail
        async with AsyncSessionLocal() as session:
            thumbs = await get_global_thumbnail(session)
            global_day = thumbs.get("day")
            global_night = thumbs.get("night")
    except Exception as e:
        logger.warning("thumbnail_gen: global thumbnail olishda xato: %s", e)

    # Tanlash tartibi: global kecha → global kunduz → poster → None
    if night and global_night:
        source_file_id = global_night
        logger.debug("thumbnail_gen: global kechki rasm (ep=%s)", episode)
    elif not night and global_day:
        source_file_id = global_day
        logger.debug("thumbnail_gen: global kunduzgi rasm (ep=%s)", episode)
    elif global_day:
        # Kecha uchun rasm yo'q — kunduzgini ishlatamiz
        source_file_id = global_day
        logger.debug("thumbnail_gen: global kunduzgi (fallback) rasm (ep=%s)", episode)
    elif global_night:
        # Kunduz uchun rasm yo'q — kechkini ishlatamiz
        source_file_id = global_night
        logger.debug("thumbnail_gen: global kechki (fallback) rasm (ep=%s)", episode)
    elif poster_file_id:
        source_file_id = poster_file_id
        logger.debug("thumbnail_gen: poster fallback (ep=%s)", episode)
    else:
        logger.debug("thumbnail_gen: hech qanday rasm yo'q (ep=%s)", episode)
        return None

    # Rasmni yuklab olish
    photo_bytes = await _download_photo_bytes(bot, source_file_id)
    if not photo_bytes:
        return None

    # Thumbnail generatsiya (sinxron Pillow kodi)
    import asyncio
    loop = asyncio.get_event_loop()
    thumb_bytes = await loop.run_in_executor(
        None, generate_thumbnail_sync, photo_bytes, episode
    )

    if not thumb_bytes:
        return None

    bio = io.BytesIO(thumb_bytes)
    bio.name = f"thumb_ep{episode}.jpg"
    bio.seek(0)
    return bio
