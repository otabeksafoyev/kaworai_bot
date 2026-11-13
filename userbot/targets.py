"""Nishon botlar. Har bir nishon o'z qoidasi bo'yicha: bor-yo'qligini tekshiradi, yangi anime yoki
faqat yangi qismlarni qo'shadi va tegishli news kanallarga e'lon yuboradi.

  KaworaiTarget — Kaworai bazasi + maxfiy kanal ("ID/Qism"), news: tur bo'yicha guruh (Anime/Dorama/Serial/Kino)
  YumoraTarget  — Yumora bazasi (asyncpg) + yuklash kanali ("id/qism"), faqat anime, news: barcha news kanallar
"""
from __future__ import annotations

import asyncio
import html
import logging

from telethon.errors import FloodWaitError

from . import storage
from .runtime import rt

logger = logging.getLogger("userbot")

DEFAULT_KAWORAI = {"id": "kaworai", "kind": "kaworai", "name": "Kaworai", "min_percent": 70, "enabled": True}


def range_text(eps: list[int]) -> str:
    eps = sorted(eps)
    if len(eps) == 1:
        return f"{eps[0]}-qism"
    if eps == list(range(eps[0], eps[-1] + 1)):
        return f"{eps[0]}–{eps[-1]}-qismlar"
    return ", ".join(map(str, eps)) + "-qismlar"


def new_episodes(episodes: dict, last: int) -> dict:
    """Manbadagi qismlardan faqat bazadagi oxirgisidan keyingilari."""
    return {n: m for n, m in episodes.items() if n > last}


async def _send_file_retry(client, chan: int, media, caption: str) -> bool:
    for _ in range(3):
        try:
            await client.send_file(chan, media, caption=caption)
            return True
        except FloodWaitError as e:
            await asyncio.sleep(e.seconds + 1)
        except Exception:
            logger.warning("yuborilmadi: %s", caption.replace("\n", " | "), exc_info=True)
            await asyncio.sleep(3)
    return False


class Target:
    kind = ""

    def __init__(self, cfg: dict):
        self.cfg = cfg

    @property
    def name(self) -> str:
        return self.cfg.get("name") or self.kind

    @property
    def min_percent(self) -> int:
        return int(self.cfg.get("min_percent", 70))

    def accepts(self, ctype: str) -> bool:
        return True

    async def find_existing(self, title: str) -> int | None:
        raise NotImplementedError

    async def max_episode(self, aid: int) -> int:
        raise NotImplementedError

    async def create(self, title: str, ctype: str, info: dict, ep_count: int, poster: bytes | None) -> int:
        raise NotImplementedError

    async def upload(self, client, aid: int, ctype: str, episodes: dict) -> tuple[int, int]:
        """(yuborildi, bazada paydo bo'ldi)"""
        raise NotImplementedError

    async def news(self, aid: int, ctype: str, eps: list[int], is_new: bool) -> int:
        raise NotImplementedError


# ═══════════════════════ Kaworai ═══════════════════════
_NEWS_GROUPS = {
    "anime": {"anime", "animelar"},
    "dorama": {"dorama", "doramalar"},
    "serial": {"serial", "seriallar"},
    "movie": {"kino", "kinolar", "movie", "film", "filmlar"},
}
_TYPE_LABEL = {"anime": "Anime", "movie": "Kino", "serial": "Serial", "dorama": "Dorama"}
_kaworai_username: str | None = None


async def _kaworai_bot_username() -> str:
    global _kaworai_username
    if not _kaworai_username:
        _kaworai_username = (await rt.kaworai_bot.get_me()).username
    return _kaworai_username


def _kaworai_caption(anime, eps: list[int], is_new: bool) -> str:
    from utils.security import esc
    from utils.ui import DIV1

    year = f" ({anime.year})" if anime.year else ""
    if not is_new:
        return f"๏ <b>{esc(anime.title)}</b>{year}\n{DIV1}\n➤ ᐅ Yangi qism: <b>{range_text(eps)}</b>\n➤ № Kode: {anime.id}"
    lines = [f"๏ <b>{esc(anime.title)}</b>{year}", DIV1,
             f"➤ ๏ Tur: {_TYPE_LABEL.get(anime.content_type or 'anime', '—')}",
             f"➤ № Kode: {anime.id}"]
    if anime.episodes_count:
        lines.append(f"➤ ๏ Qismlar: {anime.episodes_count}")
    if anime.genres:
        lines.append(f"➤ ๏ Janri: {esc(', '.join(anime.genres[:3]))}")
    if anime.rating:
        lines.append(f"➤ ★ Reyting: {anime.rating}")
    lines.append(DIV1)
    if anime.description:
        lines.append(f"<blockquote expandable>{esc(anime.description[:500])}</blockquote>")
    return "\n".join(lines)


class KaworaiTarget(Target):
    kind = "kaworai"

    async def find_existing(self, title: str) -> int | None:
        from sqlalchemy import func, select
        from database.engine import AsyncSessionLocal
        from database.models import Anime

        async with AsyncSessionLocal() as s:
            row = (await s.execute(select(Anime.id).where(func.lower(Anime.title) == title.lower()))).first()
        return row[0] if row else None

    async def max_episode(self, aid: int) -> int:
        from sqlalchemy import func, select
        from database.engine import AsyncSessionLocal
        from database.models import Series

        async with AsyncSessionLocal() as s:
            return (await s.execute(select(func.max(Series.episode)).where(Series.anime_id == aid))).scalar() or 0

    async def create(self, title, ctype, info, ep_count, poster) -> int:
        from . import pipeline as p

        fid = await p._poster_file_id(poster) if poster else None
        return await p._save_anime(title, ctype, info, ep_count, fid, poster)

    async def upload(self, client, aid, ctype, episodes) -> tuple[int, int]:
        from . import pipeline as p

        before = await self.count_episodes(aid)
        sent = await p._upload_episodes(client, aid, ctype, episodes)
        saved = 0
        for _ in range(12):             # Kaworai bot maxfiy kanaldan qabul qilguncha kutamiz (~1 daqiqagacha)
            saved = await self.count_episodes(aid) - before
            if saved >= len(episodes):
                break
            await asyncio.sleep(5)
        return sent, saved

    async def count_episodes(self, aid: int) -> int:
        from sqlalchemy import func, select
        from database.engine import AsyncSessionLocal
        from database.models import Series

        async with AsyncSessionLocal() as s:
            return (await s.execute(select(func.count(Series.id)).where(Series.anime_id == aid))).scalar() or 0

    async def news(self, aid, ctype, eps, is_new) -> int:
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        from database.engine import AsyncSessionLocal
        from database.models import Anime
        from database.queries import get_news_channels

        async with AsyncSessionLocal() as s:
            anime = await s.get(Anime, aid)
            chans = await get_news_channels(s)
        names = _NEWS_GROUPS.get(ctype, {ctype})
        chans = [c for c in chans if (c.news_group or "").strip().lower() in names and c.channel_id]
        if not (anime and chans):
            return 0
        username = await _kaworai_bot_username()
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="ᐅ Tomosha qilish", url=f"https://t.me/{username}?start=anime_{aid}")]])
        caption = _kaworai_caption(anime, eps, is_new)
        sent = 0
        for ch in chans:
            try:
                if anime.poster_file_id:
                    await rt.kaworai_bot.send_photo(ch.channel_id, anime.poster_file_id, caption=caption,
                                                    reply_markup=kb, parse_mode="HTML")
                else:
                    await rt.kaworai_bot.send_message(ch.channel_id, caption, reply_markup=kb, parse_mode="HTML")
                sent += 1
            except Exception:
                logger.warning("Kaworai news xato (%s)", ch.channel_name, exc_info=True)
            await asyncio.sleep(0.5)
        return sent


# ═══════════════════════ Yumora ═══════════════════════
_pools: dict = {}
_bots: dict = {}
_DIV = "✨━━━━━━━━━━━━✨"


def _dsn(url: str) -> str:
    url = url.strip()
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql://" + url[len("postgresql+asyncpg://"):]
    return url


class YumoraTarget(Target):
    kind = "yumora"

    def accepts(self, ctype: str) -> bool:
        return ctype == "anime"          # Yumora faqat anime uchun

    def _secret(self) -> dict:
        return storage.unseal(self.cfg["secret"])

    async def _pool(self):
        import asyncpg

        tid = self.cfg["id"]
        if tid not in _pools:
            _pools[tid] = await asyncpg.create_pool(_dsn(self._secret()["database_url"]), min_size=1, max_size=3,
                                                    command_timeout=20, max_inactive_connection_lifetime=300)
        return _pools[tid]

    def _bot(self):
        from aiogram import Bot

        tid = self.cfg["id"]
        if tid not in _bots:
            _bots[tid] = Bot(self._secret()["bot_token"])
        return _bots[tid]

    def _chan(self) -> int:
        return int(self._secret()["upload_channel_id"])

    async def find_existing(self, title: str) -> int | None:
        pool = await self._pool()
        return await pool.fetchval("SELECT id FROM animes WHERE lower(title) = lower($1) LIMIT 1", title)

    async def max_episode(self, aid: int) -> int:
        pool = await self._pool()
        return await pool.fetchval("SELECT COALESCE(MAX(number), 0) FROM episodes WHERE anime_id = $1", aid)

    async def _poster_fid(self, poster: bytes) -> str | None:
        """Poster Yumora bot file_id si bo'lishi kerak: yuklash kanaliga yuborib file_id olamiz, so'ng o'chiramiz."""
        from aiogram.types import BufferedInputFile

        try:
            m = await self._bot().send_photo(self._chan(), BufferedInputFile(poster, "poster.jpg"),
                                             disable_notification=True)
            fid = m.photo[-1].file_id
            try:
                await m.delete()
            except Exception:
                pass
            return fid
        except Exception:
            logger.warning("Yumora poster file_id olinmadi", exc_info=True)
            return None

    async def create(self, title, ctype, info, ep_count, poster) -> int:
        import asyncpg

        pool = await self._pool()
        fid = await self._poster_fid(poster) if poster else None
        thumb = None
        if poster:
            try:
                from data import config
                if getattr(config, "IMGBB_API_KEY", ""):
                    from utils.imgbb import upload_to_imgbb
                    thumb = await upload_to_imgbb(config.IMGBB_API_KEY, poster, name="poster")
            except Exception:
                logger.warning("Yumora ImgBB xato", exc_info=True)
        genres = list(info.get("genres") or [])
        for _ in range(5):
            code = str(await pool.fetchval(
                "SELECT COALESCE(MAX(CASE WHEN code ~ '^[0-9]{1,9}$' THEN code::int END), 0) + 1 FROM animes"))
            try:
                return await pool.fetchval(
                    "INSERT INTO animes (code, title, genres, poster_file_id, thumb_url) "
                    "VALUES ($1, $2, $3, $4, $5) RETURNING id", code, title, genres, fid, thumb)
            except asyncpg.UniqueViolationError:
                await asyncio.sleep(0.2)
        raise RuntimeError("Yumora: bo'sh kod topilmadi")

    async def upload(self, client, aid, ctype, episodes) -> tuple[int, int]:
        pool = await self._pool()
        code = await pool.fetchval("SELECT code FROM animes WHERE id = $1", aid)
        sent = 0
        for n, m in episodes.items():
            if await _send_file_retry(client, self._chan(), m.media, f"id: {code}\nqism: {n}"):
                sent += 1
            await asyncio.sleep(2)
        want = list(episodes)
        saved = 0
        for _ in range(12):             # Yumora bot kanaldan qabul qilguncha kutamiz (~1 daqiqagacha)
            saved = await pool.fetchval("SELECT COUNT(*) FROM episodes WHERE anime_id = $1 AND number = ANY($2::int[])",
                                        aid, want)
            if saved >= len(want):
                break
            await asyncio.sleep(5)
        return sent, saved

    async def news(self, aid, ctype, eps, is_new) -> int:
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        pool = await self._pool()
        a = await pool.fetchrow("SELECT * FROM animes WHERE id = $1", aid)
        chans = [r["chat_id"] for r in await pool.fetch("SELECT DISTINCT chat_id FROM channels WHERE kind = 'news'")]
        if not (a and chans):
            return 0
        title = html.escape(a["title"])
        if is_new:
            cnt = await pool.fetchval("SELECT COUNT(*) FROM episodes WHERE anime_id = $1", aid)
            text = (f"🎬 <b>{title}</b>\n{_DIV}\n🎭 <b>Janr:</b> {html.escape(', '.join(a['genres']) or '—')}\n"
                    f"📺 <b>Qismlar:</b> {cnt}\n🆔 <code>{a['code']}</code>")
        else:
            text = f"🎬 <b>{title}</b>\n{_DIV}\n📺 <b>Yangi qism:</b> {range_text(eps)}\n🆔 <code>{a['code']}</code>"
        poster = a["poster_file_id"]
        if not poster:
            poster = await pool.fetchval("SELECT value FROM settings WHERE key = 'default_poster'")
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text="▶️ Tomosha qilish", url=f"https://t.me/{self.cfg.get('bot_username', '')}?start={a['code']}")]])
        bot, sent = self._bot(), 0
        for chat_id in chans:
            try:
                if poster:
                    await bot.send_photo(chat_id, poster, caption=text, reply_markup=markup, parse_mode="HTML")
                else:
                    await bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")
                sent += 1
            except Exception:
                logger.warning("Yumora news xato (%s)", chat_id, exc_info=True)
            await asyncio.sleep(0.5)
        return sent


# ═══════════════════════ ro'yxat ═══════════════════════
_KINDS = {"kaworai": KaworaiTarget, "yumora": YumoraTarget}


def make(cfg: dict) -> Target:
    return _KINDS[cfg["kind"]](cfg)


async def load_targets() -> list[dict]:
    """Saqlangan nishonlar; bo'sh bo'lsa [] (eski rejim). Kaworai doim ro'yxat boshida bo'ladi."""
    items = await storage.load_targets()
    if items and not any(t["kind"] == "kaworai" for t in items):
        items.insert(0, dict(DEFAULT_KAWORAI))
    return items


async def forget(target_id: str) -> None:
    """Nishon o'chirilganda ochiq pool va bot sessiyasini yopamiz."""
    pool = _pools.pop(target_id, None)
    if pool:
        await pool.close()
    bot = _bots.pop(target_id, None)
    if bot:
        await bot.session.close()
