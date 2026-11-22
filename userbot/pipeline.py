"""Asosiy oqim: kanal posti → manba bot → tekshiruv → AI ma'lumot → tasdiq → Kaworai bazasi + qismlar."""
from __future__ import annotations

import asyncio
import io
import logging
import os
import time

from sqlalchemy import func, select
from telethon.errors import FloodWaitError

from data import config
from database.engine import AsyncSessionLocal
from database.models import Anime, Series
from utils.ai_anime import build_content_info
from utils.security import esc

from . import storage, targets
from .parsers import ENG_RE, clean_line, parse_post, same_title
from .postinfo import AI_TRUST, merge_info, post_info
from .scoring import breakdown_text, match_percent
from .runtime import rt
from .source import SourceBlocked, fetch_from_source

logger = logging.getLogger("userbot")

AUTO_CONFIRM = os.environ.get("USERBOT_AUTO_CONFIRM", "0") == "1"
# AI natijasida bo'sh bo'lsa qayta urinadigan asosiy maydonlar
REQUIRED = ("desc", "genres", "year")
FETCH_TIMEOUT = int(os.environ.get("UB_FETCH_TIMEOUT", "240"))     # manba bot bilan butun suhbat eng ko'pi bilan
POSTER_TIMEOUT = int(os.environ.get("UB_POSTER_TIMEOUT", "45"))    # poster yuklab olish
UPLOAD_TIMEOUT = int(os.environ.get("UB_UPLOAD_TIMEOUT", "900"))   # bitta nishonga yuklash
AI_STEP_TIMEOUT = {"_jikan_search": 12, "_anilist_search": 10, "_tmdb_facts": 10, "_gemini_enrich": 25, "_translate_uz": 12}
AI_TIMEOUT = int(os.environ.get("UB_AI_TIMEOUT", "60"))
AI_POLL = 8          # AI kutilayotganda hisobotdagi sekundlar necha soniyada yangilanadi
AI_GRACE = 30        # AI_TIMEOUT dan keyin yana shuncha kutib, baribir davom etamiz      # AI qidiruvi eng ko'pi bilan necha soniya
AI_ATTEMPTS = int(os.environ.get("UB_AI_ATTEMPTS", "1"))     # AI maydonlari bo'sh bo'lsa necha marta urinish


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


async def _bounded(aw, timeout: float):
    """Vaqt chegarasi: `wait_for` dan farqli, ichki vazifa bekor qilinishiga javob bermasa ham `timeout` da qaytadi."""
    task = asyncio.ensure_future(aw)
    try:
        done, _ = await asyncio.wait({task}, timeout=timeout)
    except asyncio.CancelledError:
        task.cancel()
        raise
    if not done:
        task.cancel()
        task.add_done_callback(lambda t: t.cancelled() or t.exception())   # "exception never retrieved" bo'lmasin
        raise asyncio.TimeoutError()
    return task.result()


_AI_PATCHED = False


def _instrument_ai() -> None:
    """Kaworai AI funksiyalariga (faqat shu jarayonda) log va qadam bo'yicha vaqt chegarasi qo'yadi:
    qaysi manba sekinligi logda ko'rinadi, bitta sekin manba butun qidiruvni cho'zib yubormaydi."""
    global _AI_PATCHED
    if _AI_PATCHED:
        return
    _AI_PATCHED = True
    try:
        from utils import ai_anime as A
    except Exception:
        logger.warning("ai_anime topilmadi — qadamlar o'ralmadi", exc_info=True)
        return

    def make(name: str, orig):
        async def wrapper(*a, **k):
            t = time.monotonic()
            logger.info("AI/%s boshlandi", name)
            try:
                r = await asyncio.wait_for(orig(*a, **k), AI_STEP_TIMEOUT[name])
            except asyncio.TimeoutError:
                logger.warning("AI/%s %ss ichida tugamadi — o'tkazib yuboryapman", name, AI_STEP_TIMEOUT[name])
                errs = next((x for x in a if isinstance(x, list)), None)
                if errs is not None:
                    errs.append(f"{name}: {AI_STEP_TIMEOUT[name]}s ichida javob bermadi")
                return ([], "vaqt tugadi") if name in ("_jikan_search", "_anilist_search") else None
            logger.info("AI/%s tugadi (%.1fs)", name, time.monotonic() - t)
            return r
        return wrapper

    for name in AI_STEP_TIMEOUT:
        if hasattr(A, name):
            setattr(A, name, make(name, getattr(A, name)))


def _ai_in_thread(english: str, ctype: str) -> dict:
    """AI qidiruvi alohida oqimda va o'z hodisalar siklida: ichida nima qotmasin, asosiy jarayonni bloklamaydi."""
    _instrument_ai()
    return asyncio.run(build_content_info(english, ctype))


async def _ai_info(english: str, ctype: str) -> dict:
    """AI ma'lumot yig'adi (qat'iy vaqt chegarasi bilan); asosiy maydonlar bo'sh bo'lsa AI_ATTEMPTS martagacha urinadi."""
    info: dict = {}
    loop = asyncio.get_running_loop()
    for attempt in range(1, max(1, AI_ATTEMPTS) + 1):
        t = time.monotonic()
        try:
            info = await _bounded(loop.run_in_executor(None, _ai_in_thread, english, ctype), AI_TIMEOUT)
            logger.info("AI tugadi (%.1fs): topildi=%s", time.monotonic() - t, bool(info.get("matched_title") or info.get("desc")))
        except asyncio.TimeoutError:
            logger.warning("AI qidiruvi %ss ichida tugamadi (%s)", AI_TIMEOUT, english)
            info = {"errors": [f"AI {AI_TIMEOUT}s ichida javob bermadi"]}
        except Exception:
            logger.exception("build_content_info xato")
            info = {}
        if not _missing(info):
            break
        logger.info("AI maydonlar bo'sh %s (urinish %s)", _missing(info), attempt)
        if attempt < AI_ATTEMPTS:
            await asyncio.sleep(2)
    return info


async def _timed_ai(english: str, ctype: str, timings: dict) -> dict:
    t = time.monotonic()
    try:
        return await _ai_info(english, ctype)
    finally:
        timings["AI"] = round(time.monotonic() - t)


async def _download_poster(client, msg) -> bytes | None:
    buf = io.BytesIO()
    await client.download_media(msg, file=buf)
    return buf.getvalue() or None


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
                if e.seconds > 20:
                    await rt.notify(f"◌ Telegram {e.seconds}s kutishni so'radi (qism {n}) — kutyapman...")
                await asyncio.sleep(e.seconds + 1)
            except Exception:
                logger.warning("qism %s yuborilmadi", n, exc_info=True)
                await asyncio.sleep(3)
        await asyncio.sleep(2)  # tartib saqlansin (bot navbat bilan qabul qiladi)
    return sent


RETRY_MIN = int(os.environ.get("UB_RETRY_MIN", "10"))     # majburiy obuna tugallanmasa — necha daqiqadan keyin qayta urinish
MAX_RETRY = int(os.environ.get("UB_MAX_RETRY", "6"))


async def _noop(*a, **k) -> None:
    return None


async def _fetch(client, cfg: dict, code: str, msg, prog) -> tuple:
    """Manba bot bilan suhbat — vaqt chegarasi bilan (qotib qolsa SourceBlocked: keyinroq qayta uriniladi)."""
    try:
        return await _bounded(
            fetch_from_source(client, cfg["source_bot"], code, post=msg, notify=rt.notify, progress=prog.step),
            FETCH_TIMEOUT)
    except asyncio.TimeoutError:
        raise SourceBlocked(f"Manba bot {FETCH_TIMEOUT}s ichida tugamadi.\nOxirgi bosqich: {rt.stage or '—'}")


async def process_post(client, msg, cfg: dict, attempt: int = 0) -> None:
    bag: dict = {}
    prog = rt.progress()
    try:
        await _process_post(client, msg, cfg, attempt, bag, prog)
    finally:
        await prog.flush()
        rt.stage = None                                   # erta qaytilsa — fonda ishlayotgan AI/poster vazifalarini to'xtatamiz
        for t in bag.values():
            if not t.done():
                t.cancel()


async def _process_post(client, msg, cfg: dict, attempt: int, bag: dict, prog) -> None:
    if await storage.is_done(msg.chat_id, msg.id):
        logger.info("O'tkazildi (allaqachon qayta ishlangan): %s/%s", msg.chat_id, msg.id)
        return
    title, code, eng = parse_post(msg.message or "")
    if not (title and code):
        logger.info("O'tkazildi: nom/kod topilmadi (nom=%r, kod=%r) matn=%r", title, code, (msg.message or "")[:200])
        return  # anime posti emas
    ctype = cfg.get("content_type", "anime")
    header = (f"Yangi post • № manba kodi: {code}" if attempt == 0
              else f"Qayta tekshiryapman ({attempt}/{MAX_RETRY}) • № manba kodi: {code}")
    await prog.begin(title, header)

    # Fonda bir vaqtda: AI qidiruvi (avtomatik rejimda) va poster yuklab olish — manba bot bilan parallel
    t0 = time.monotonic()
    timings: dict = {}
    tcfgs = await targets.load_targets()
    if tcfgs:
        bag["ai"] = asyncio.create_task(_timed_ai(eng or title, cfg.get("content_type", "anime"), timings))
    if msg.photo:
        bag["poster"] = asyncio.create_task(_download_poster(client, msg))

    # 1) manba bot
    ts0 = time.monotonic()
    try:
        info_text, episodes, debug = await _fetch(client, cfg, code, msg, prog)
        timings["manba"] = round(time.monotonic() - ts0)
        await prog.step(f"✓ Manba bot: {len(episodes)} ta qism ({timings['manba']}s)")
    except SourceBlocked as e:
        if attempt < MAX_RETRY:
            asyncio.get_running_loop().call_later(RETRY_MIN * 60, rt.queue.put_nowait, (msg, cfg, attempt + 1))
            return await rt.notify(f"! <b>{esc(title)}</b>:\n{esc(str(e))}\n◌ {RETRY_MIN} daqiqadan keyin qayta uriniladi ({attempt + 1}/{MAX_RETRY}).")
        return await rt.notify(f"✕ <b>{esc(title)}</b>: urinishlar tugadi — qo'shilmadi.\n{esc(str(e))}")
    except Exception as e:
        return await rt.notify(f"✕ Manba bot bilan ishlashda xato: {esc(type(e).__name__)}")
    if not episodes:
        return await rt.notify(f"✕ Manba botdan qismlar topilmadi — qo'shilmadi.\n<code>{esc(debug[:700])}</code>")

    # 2) nom tekshiruvi (post nomi == manba bot nomi)
    if not same_title(title, info_text):
        return await rt.notify(
            f"✕ Nom mos kelmadi — qo'shilmadi.\nPost: <b>{esc(title)}</b>\nManba bot javobi:\n<code>{esc(info_text[:300])}</code>"
        )

    # 3) inglizcha nom
    if not eng:
        em = ENG_RE.search(info_text)
        eng = clean_line(em.group(1)) if em else None
    if not eng and await targets.load_targets():
        eng = title      # avtomatik rejimda admindan so'ramaymiz: AI post nomi bilan qidiradi (topilmasa foiz past chiqadi)
    if not eng:
        eng = await rt.ask_text(f"⌕ <b>{esc(title)}</b> uchun inglizcha nomni yuboring:")
        if not eng:
            return await rt.notify("✕ Inglizcha nom kelmadi — bekor qilindi.")

    poster = None
    if "poster" in bag:
        try:
            poster = await _bounded(bag["poster"], POSTER_TIMEOUT)
            await prog.step(f"✓ Poster yuklandi ({len(poster or b'') // 1024} KB)")
        except asyncio.TimeoutError:
            logger.warning("poster %ss ichida yuklanmadi — manba tugagach qayta urinaman", POSTER_TIMEOUT)
            await prog.step("◌ Poster qotib qoldi, qayta urinyapman...")
            try:
                poster = await _bounded(_download_poster(client, msg), POSTER_TIMEOUT)
                await prog.step(f"✓ Poster yuklandi ({len(poster or b'') // 1024} KB)", True)
            except Exception:
                logger.warning("poster ikkinchi urinishda ham yuklanmadi", exc_info=True)
                await prog.step("! Poster yuklanmadi — posterisiz davom etaman", True)
        except Exception:
            logger.warning("poster yuklanmadi", exc_info=True)
            await prog.step("! Poster yuklanmadi — posterisiz davom etaman")

    # Avtomatik rejim (/targets): bir nechta nishon bot, moslik foizi bo'yicha. Nishon yo'q bo'lsa — eski rejim.
    if tcfgs:
        return await _process_multi(client, msg, tcfgs, title, code, eng, ctype, info_text, episodes, poster,
                                    ai_task=bag.get("ai"), timings=timings, t0=t0, prog=prog)

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
        sent, saved = await _bounded(t.upload(client, aid, ctype, new_eps), UPLOAD_TIMEOUT)
        if saved <= 0:
            return f"! {esc(t.name)}: ID {aid} — qismlar qabul qilinmadi (yuborildi {sent}/{len(new_eps)}). Kanal/admin huquqini tekshiring."
        news = await t.news(aid, ctype, sorted(new_eps), is_new)
        what = "yangi anime" if is_new else f"yangi qism: {targets.range_text(list(new_eps))}"
        return f"✓ {esc(t.name)}: {what} • ID {aid} • qabul: {saved}/{len(new_eps)} • news: {news} ta kanal"
    except Exception as e:
        logger.exception("nishon %s xato", t.name)
        return f"✕ {esc(t.name)}: xato ({esc(type(e).__name__)})"


async def _process_multi(client, msg, tcfgs: list[dict], title: str, code: str, eng: str, ctype: str,
                         info_text: str, episodes: dict, poster: bytes | None,
                         ai_task=None, timings: dict | None = None, t0: float | None = None, prog=None) -> None:
    step = prog.step if prog else _noop
    timings = timings if timings is not None else {}
    t0 = t0 if t0 is not None else time.monotonic()
    ts = [t for t in (targets.make(c) for c in tcfgs if c.get("enabled", True)) if t.accepts(ctype)]
    if not ts:
        return await rt.notify(f"✕ «{esc(title)}» ({esc(ctype)}) uchun yoqilgan nishon bot yo'q — qo'shilmadi.")

    await step("◌ AI natijasini kutyapman...")
    ai = {}
    try:
        if ai_task is not None:
            tw = time.monotonic()
            while not ai_task.done():
                await asyncio.wait({ai_task}, timeout=AI_POLL)
                if not ai_task.done():
                    if time.monotonic() - tw > AI_TIMEOUT + AI_GRACE:        # zaxira: AI vazifasi o'zi tugamasa ham kutib o'tirmaymiz
                        ai_task.cancel()
                        logger.error("AI vazifasi %ss dan keyin ham tugamadi — post ma'lumoti bilan davom etaman", AI_TIMEOUT + AI_GRACE)
                        break
                    await step(f"◌ AI natijasini kutyapman... {round(time.monotonic() - tw)}s", True)
            if ai_task.done() and not ai_task.cancelled():
                ai = ai_task.result()
        else:
            ai = await _ai_info(eng, ctype)
    except Exception:
        logger.exception("AI xato")
    ai = ai or {}
    logger.info("[%s] AI natijasi olindi: topildi=%s", title, bool(ai.get("matched_title") or ai.get("desc") or ai.get("genres")))
    post = post_info(msg.message or "")
    ai_found = bool(ai.get("matched_title") or ai.get("desc") or ai.get("genres"))
    if ai_found:
        pct, parts = match_percent(title, eng, f"{msg.message or ''}\n{info_text}", ai)
    else:
        pct, parts = None, {}
    info = merge_info(ai, post, pct)
    logger.info("[%s] moslik=%s, nishonlar=%s", title, pct, [t.name for t in ts])
    if not any(info.get(k) for k in REQUIRED):
        return await rt.notify(f"✕ <b>{esc(title)}</b>: na AI, na postda ma'lumot (tavsif/janr/yil) topildi — hech qaysi botga qo'shilmadi.")

    if pct is None:                               # AI topmadi — postdagi ma'lumot bilan hamma nishonga qo'shamiz
        ok_ts = list(ts)
        lines = [f"◈ <b>{esc(title)}</b> — AI ma'lumot topmadi, postdagi ma'lumot ishlatiladi"]
    else:
        ok_ts = [t for t in ts if pct >= t.min_percent]
        lines = [f"◈ <b>{esc(title)}</b> — moslik <b>{pct}%</b>", f"≡ {esc(breakdown_text(parts))}"]
        if pct < AI_TRUST:
            lines.append("! AI boshqa asarni topgan ko'rinadi — postdagi ma'lumot ishlatiladi")
        lines += [f"✕ {esc(t.name)}: {pct}% < {t.min_percent}% — qo'shilmadi" for t in ts if t not in ok_ts]
    if ai.get("note"):
        lines.append(f"! AI: {esc(ai['note'])}")
    if not ok_ts:
        return await rt.notify("\n".join(lines))
    await rt.notify("\n".join(lines) + "\n◌ Qo'shilyapti...")
    await step("◌ Qo'shilyapti: " + ", ".join(t.name for t in ok_ts))

    td = time.monotonic()
    results = list(await asyncio.gather(*(_deliver(t, client, title, ctype, info, episodes, poster) for t in ok_ts)))
    timings["yuklash"] = round(time.monotonic() - td)
    if any(r.startswith(("✓", "=")) for r in results):
        await storage.mark_done(msg.chat_id, msg.id)
    spent = " • ".join(f"{k} {v}s" for k, v in timings.items())
    await rt.notify(f"◈ <b>{esc(title)}</b> — natija:\n" + "\n".join(results)
                    + f"\n⏱ jami {round(time.monotonic() - t0)}s ({spent})")
