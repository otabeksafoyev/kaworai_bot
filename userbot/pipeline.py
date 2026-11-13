"""Asosiy oqim: kanal posti → manba bot → tekshiruv → AI ma'lumot → tasdiq → Kaworai bazasi + qismlar."""
from __future__ import annotations

import asyncio
import io
import logging
import os

from sqlalchemy import func, select
from telethon.errors import FloodWaitError

from data import config
from database.engine import AsyncSessionLocal
from database.models import Anime, Series
from utils.ai_anime import build_content_info
from utils.security import esc

from . import storage, targets
from .parsers import ENG_RE, clean_line, parse_post, same_title
from .scoring import breakdown_text, match_percent
from .runtime import rt
from .source import fetch_from_source

logger = logging.getLogger("userbot")

AUTO_CONFIRM = os.environ.get("USERBOT_AUTO_CONFIRM", "0") == "1"
# AI natijasida bo'sh bo'lsa qayta urinadigan asosiy maydonlar
REQUIRED = ("desc", "genres", "year")


def _secret_channel(ctype: str) -> int:
    by = {
        "anime": getattr(config, "SECRET_ANIME_CHANNEL_ID", 0),
        "dorama": getattr(config, "SECRET_DORAMA_CHANNEL_ID", 0),
        "serial": getattr(config, "SECRET_SERIAL_CHANNEL_ID", 0),
        "movie": getattr(config, "SECRET_KINO_CHANNEL_ID", 0),
    }
    return by.get(ctype) or config.SECRET_CHANNEL_ID


def _missing(info: dict) -> list[str]:
    return [k for k in REQUIRED if not info.get(k)]


async def _ai_info(english: str, ctype: str) -> dict:
    """AI ma'lumot yig'adi; asosiy maydonlar bo'sh bo'lsa BIR marta qayta urinadi."""
    info: dict = {}
    for attempt in (1, 2):
        try:
            info = await build_content_info(english, ctype)
        except Exception:
            logger.exception("build_content_info xato")
            info = {}
        if not _missing(info):
            break
        logger.info("AI maydonlar bo'sh %s (urinish %s)", _missing(info), attempt)
        await asyncio.sleep(2)
    return info


def _preview(title: str, english: str, ctype: str, info: dict, ep_count: int, code: str) -> str:
    def v(x):
        return esc(str(x)) if x not in (None, "", [], 0, 0.0) else "—"
    note = f"\n! {esc(info['note'])}" if info.get("note") else ""
    errs = f"\n! {esc('; '.join(info['errors']))}" if info.get("errors") else ""
    return (
        f"◈ <b>AI natijasi</b>  ({esc(' + '.join(info.get('sources') or ['—']))})\n"
        f"↗ Topilgan nom: {v(info.get('matched_title') or english)}{note}{errs}\n\n"
        f"✎ <b>{esc(title)}</b>  •  manba kodi: <code>{esc(code)}</code>\n"
        f"≡ Tur: {v(ctype)}\n"
        f"๏ Janr: {v(', '.join(info.get('genres') or []))}\n"
        f"# Teglar: {v(', '.join(info.get('tags') or []))}\n"
        f"☺ Mood: {v(', '.join(info.get('mood') or []))}\n"
        f"◎ Yil: {v(info.get('year'))}  •  ★ Reyting: {v(info.get('rating'))}\n"
        f"๏ Qismlar: <b>{ep_count}</b> (manba botdan)  •  ◷ {v(info.get('duration'))} daq\n"
        f"◈ Status: {v(info.get('status'))}\n\n"
        f"๏ {esc((info.get('desc') or '—')[:700])}\n\n"
        f"To'g'rimi?"
    )


async def _poster_file_id(poster: bytes) -> str | None:
    """Poster baytlarini Kaworai bot orqali yuborib file_id oladi (file_id bot'ga xos)."""
    from aiogram.types import BufferedInputFile
    try:
        m = await rt.kaworai_bot.send_photo(rt.admin_id, BufferedInputFile(poster, "poster.jpg"), disable_notification=True)
        fid = m.photo[-1].file_id
        try:
            await m.delete()
        except Exception:
            pass
        return fid
    except Exception:
        logger.warning("poster file_id olinmadi", exc_info=True)
        return None


async def _save_anime(title: str, ctype: str, info: dict, ep_count: int, poster_fid: str | None, poster: bytes | None) -> int:
    inline_url = None
    if poster and getattr(config, "IMGBB_API_KEY", ""):
        try:
            from utils.imgbb import upload_to_imgbb
            inline_url = await upload_to_imgbb(config.IMGBB_API_KEY, poster, name="poster")
        except Exception:
            logger.warning("ImgBB xato", exc_info=True)

    async with AsyncSessionLocal() as s:
        new_id = ((await s.execute(select(func.max(Anime.id)))).scalar() or 0) + 1
        s.add(Anime(
            id=new_id, title=title, content_type=ctype,
            description=info.get("desc") or None,
            genres=info.get("genres") or [], tags=info.get("tags") or [], mood=info.get("mood") or [],
            year=info.get("year") or None, rating=info.get("rating") or 0.0,
            episodes_count=ep_count, duration=info.get("duration") or None,
            status=info.get("status") or "ongoing",
            poster_file_id=poster_fid, inline_thumbnail_url=inline_url, season=1,
        ))
        await s.commit()
    return new_id


async def _upload_episodes(client, anime_id: int, ctype: str, episodes: dict) -> int:
    """Qismlarni maxfiy kanalga 'ID/Qism' caption bilan tashlaydi — Kaworai bot o'zi qabul qiladi.
    send_file(msg.media) — fayl qayta yuklanmaydi, Telegram serverida nusxalanadi."""
    chan = _secret_channel(ctype)
    sent = 0
    for n, m in episodes.items():
        for _ in range(3):
            try:
                await client.send_file(chan, m.media, caption=f"ID: {anime_id}\nQism: {n}")
                sent += 1
                break
            except FloodWaitError as e:
                await asyncio.sleep(e.seconds + 1)
            except Exception:
                logger.warning("qism %s yuborilmadi", n, exc_info=True)
                await asyncio.sleep(3)
        await asyncio.sleep(2)  # tartib saqlansin (bot navbat bilan qabul qiladi)
    return sent


async def process_post(client, msg, cfg: dict) -> None:
    if await storage.is_done(msg.chat_id, msg.id):
        return
    title, code, eng = parse_post(msg.message or "")
    if not (title and code):
        return  # anime posti emas
    ctype = cfg.get("content_type", "anime")
    await rt.notify(f"◈ Yangi post: <b>{esc(title)}</b>\n№ Manba kodi: <code>{esc(code)}</code>\n◌ Manba botdan tekshiryapman...")

    # 1) manba bot
    try:
        info_text, episodes = await fetch_from_source(client, cfg["source_bot"], code)
    except Exception as e:
        return await rt.notify(f"✕ Manba bot bilan ishlashda xato: {esc(type(e).__name__)}")
    if not episodes:
        return await rt.notify("✕ Manba botdan qismlar topilmadi — qo'shilmadi.")

    # 2) nom tekshiruvi (post nomi == manba bot nomi)
    if not same_title(title, info_text):
        return await rt.notify(
            f"✕ Nom mos kelmadi — qo'shilmadi.\nPost: <b>{esc(title)}</b>\nManba bot javobi:\n<code>{esc(info_text[:300])}</code>"
        )

    # 3) inglizcha nom
    if not eng:
        em = ENG_RE.search(info_text)
        eng = clean_line(em.group(1)) if em else None
    if not eng:
        eng = await rt.ask_text(f"⌕ <b>{esc(title)}</b> uchun inglizcha nomni yuboring:")
        if not eng:
            return await rt.notify("✕ Inglizcha nom kelmadi — bekor qilindi.")

    poster = None
    if msg.photo:
        buf = io.BytesIO()
        await client.download_media(msg, file=buf)
        poster = buf.getvalue() or None

    # Avtomatik rejim (/targets): bir nechta nishon bot, moslik foizi bo'yicha. Nishon yo'q bo'lsa — eski rejim.
    tcfgs = await targets.load_targets()
    if tcfgs:
        return await _process_multi(client, msg, tcfgs, title, code, eng, ctype, info_text, episodes, poster)

    # 4) AI ma'lumot + tasdiq (nom noto'g'ri bo'lsa "boshqa nom bilan" qayta urinadi)
    for _ in range(3):
        info = await _ai_info(eng, ctype)
        decision = "ok" if AUTO_CONFIRM and not _missing(info) else await rt.confirm(
            _preview(title, eng, ctype, info, len(episodes), code), poster)
        if decision == "ok":
            break
        if decision == "retry":
            new = await rt.ask_text("⌕ Yangi inglizcha nomni yuboring:")
            if not new:
                return await rt.notify("✕ Bekor qilindi.")
            eng = new
            continue
        return await rt.notify("✕ Bekor qilindi.")
    else:
        return await rt.notify("✕ Urinishlar tugadi — bekor qilindi.")

    # 5) takror tekshiruvi
    async with AsyncSessionLocal() as s:
        dup = (await s.execute(select(Anime.id).where(func.lower(Anime.title) == title.lower()))).first()
    if dup:
        return await rt.notify(f"! «{esc(title)}» botda allaqachon bor (ID {dup[0]}) — qo'shilmadi.")

    # 6) saqlash + qismlar
    poster_fid = await _poster_file_id(poster) if poster else None
    anime_id = await _save_anime(title, ctype, info, len(episodes), poster_fid, poster)
    await rt.notify(f"✓ <b>{esc(title)}</b> qo'shildi!  № <code>{anime_id}</code>\n◌ {len(episodes)} ta qism yuklanyapti...")
    sent = await _upload_episodes(client, anime_id, ctype, episodes)
    await storage.mark_done(msg.chat_id, msg.id)

    async with AsyncSessionLocal() as s:
        saved = (await s.execute(select(func.count(Series.id)).where(Series.anime_id == anime_id))).scalar() or 0
    await rt.notify(f"✓ Tayyor: <b>{esc(title)}</b>\n๏ Yuborildi: {sent}/{len(episodes)}  •  Bazada: {saved}")


# ═══════════ Avtomatik rejim: moslik foizi → mos nishon botlarga ═══════════
async def _deliver(t, client, title: str, ctype: str, info: dict, episodes: dict, poster: bytes | None) -> str:
    """Bitta nishonga: yangi anime yoki faqat yangi qismlar + news. Adminga qisqa natija qatori qaytaradi."""
    try:
        aid = await t.find_existing(title)
        if aid is None:
            is_new, new_eps = True, episodes
            aid = await t.create(title, ctype, info, len(episodes), poster)
        else:
            is_new = False
            last = await t.max_episode(aid)
            new_eps = targets.new_episodes(episodes, last)
            if not new_eps:
                return f"= {esc(t.name)}: «{esc(title)}» bor (ID {aid}), yangi qism yo'q ({last}-qismgacha bor)"
        sent, saved = await t.upload(client, aid, ctype, new_eps)
        if saved <= 0:
            return f"! {esc(t.name)}: ID {aid} — qismlar qabul qilinmadi (yuborildi {sent}/{len(new_eps)}). Kanal/admin huquqini tekshiring."
        news = await t.news(aid, ctype, sorted(new_eps), is_new)
        what = "yangi anime" if is_new else f"yangi qism: {targets.range_text(list(new_eps))}"
        return f"✓ {esc(t.name)}: {what} • ID {aid} • qabul: {saved}/{len(new_eps)} • news: {news} ta kanal"
    except Exception as e:
        logger.exception("nishon %s xato", t.name)
        return f"✕ {esc(t.name)}: xato ({esc(type(e).__name__)})"


async def _process_multi(client, msg, tcfgs: list[dict], title: str, code: str, eng: str, ctype: str,
                         info_text: str, episodes: dict, poster: bytes | None) -> None:
    ts = [t for t in (targets.make(c) for c in tcfgs if c.get("enabled", True)) if t.accepts(ctype)]
    if not ts:
        return await rt.notify(f"✕ «{esc(title)}» ({esc(ctype)}) uchun yoqilgan nishon bot yo'q — qo'shilmadi.")

    info = await _ai_info(eng, ctype)
    if _missing(info):
        return await rt.notify(
            f"✕ <b>{esc(title)}</b>: AI ma'lumoti to'liq emas ({esc(', '.join(_missing(info)))}) — hech qaysi botga qo'shilmadi.")

    pct, parts = match_percent(title, eng, f"{msg.message or ''}\n{info_text}", info)
    ok_ts = [t for t in ts if pct >= t.min_percent]
    lines = [f"◈ <b>{esc(title)}</b> — moslik <b>{pct}%</b>", f"≡ {esc(breakdown_text(parts))}"]
    if info.get("note"):
        lines.append(f"! AI: {esc(info['note'])}")
    lines += [f"✕ {esc(t.name)}: {pct}% < {t.min_percent}% — qo'shilmadi" for t in ts if t not in ok_ts]
    if not ok_ts:
        return await rt.notify("\n".join(lines))
    await rt.notify("\n".join(lines) + "\n◌ Qo'shilyapti...")

    results = []
    for t in ok_ts:
        results.append(await _deliver(t, client, title, ctype, info, episodes, poster))
    if any(r.startswith(("✓", "=")) for r in results):
        await storage.mark_done(msg.chat_id, msg.id)
    await rt.notify(f"◈ <b>{esc(title)}</b> — natija:\n" + "\n".join(results))
