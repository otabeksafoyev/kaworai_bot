"""Manba bot bilan suhbat: deep link (yoki kod) yuboradi, nom va qismlarni yig'adi.

Oqim:
  1) Postdagi tugmadan  t.me/<bot>?start=<payload>  topilsa — botga `/start <payload>` yuboriladi
     (aks holda `/start <kod>`, javob kelmasa — oddiy `<kod>`).
  2) Majburiy obuna so'ralsa (t.me havolali tugmalar) — akkaunt o'sha kanallarga a'zo bo'ladi, "tekshirish" bosiladi.
  3) Raqamli tugmalar (qism raqamlari) birma-bir bosiladi; sifat tanlovi chiqsa (UB_QUALITY, standart 720) tanlanadi;
     "keyingi" tugmasi bo'lsa sahifalar o'tiladi. Kelgan videolar bosilgan qism raqamiga bog'lanadi.
Tugma bosilganda bot callback'ga javob bermasa ham (timeout) kelgan videolar yig'iladi."""
from __future__ import annotations

import asyncio
import logging
import os
import re

from telethon import errors, functions

from .parsers import episode_no

logger = logging.getLogger("userbot")

QUALITY_PREF = os.environ.get("UB_QUALITY", "720")
MAX_JOIN = 10          # bitta obuna so'rovida eng ko'pi bilan nechta kanalga a'zo bo'ladi
MAX_GATE_ROUNDS = 3
MAX_STEPS = 80

_QUALITY_RE = re.compile(r"(?i)(?<!\d)(2160|1440|1080|720|576|480|360|240)\s*p\b|\b(4k|2k|fhd|uhd)\b")
_EP_BTN_RE = re.compile(r"^\D{0,3}(\d{1,4})\D{0,3}$")
_NEXT_RE = re.compile(r"(?i)(keyingi|oldinga|next|далее|вперед|»|›|▶|➡|→)")
_CHECK_RE = re.compile(r"(?i)(tekshir|obuna\s*bo['ʻ’`]?ldim|a['ʻ’`]?zo\s*bo['ʻ’`]?ldim|check|подтверд|проверить|✅|✔)")
_GATE_TEXT_RE = re.compile(r"(?i)(obuna|a['ʻ’`]?zo\s*bo|subscribe|подпиш)")
_SKIP_BTN_RE = re.compile(r"(?i)(menyu|menu|baholash|ko['ʻ’`]?rmoqchiman|orqaga|back|bosh sahifa)")
_START_URL_RE = re.compile(r"(?i)^https?://(?:t|telegram)\.me/([A-Za-z0-9_]{4,})\?start=([\w\-]+)")
_TME_RE = re.compile(r"(?i)^(?:https?://)?(?:t|telegram)\.me/([^?\s]+)")


def is_video(m) -> bool:
    if getattr(m, "video", None):
        return True
    doc = getattr(m, "document", None)
    return bool(doc and (doc.mime_type or "").startswith("video"))


def flat_buttons(m) -> list:
    return [b for row in (getattr(m, "buttons", None) or []) for b in row]


def deep_links(post, source_bot: str) -> list[tuple[str, str]]:
    """Postdagi tugmalardan manba botning deep linklari: [(bot, payload)]."""
    want = (source_bot or "").lstrip("@").lower()
    out = []
    for b in flat_buttons(post):
        m = _START_URL_RE.match(getattr(b, "url", None) or "")
        if m and m.group(1).lower() == want:
            out.append((m.group(1), m.group(2)))
    return out


def _quality_value(text: str) -> int | None:
    m = _QUALITY_RE.search(text or "")
    if not m:
        return None
    if m.group(1):
        return int(m.group(1))
    return {"4k": 2160, "uhd": 2160, "2k": 1440, "fhd": 1080}[m.group(2).lower()]


def _pick_quality(buttons: list):
    """Afzal sifat (UB_QUALITY) — bo'lmasa eng yuqorisi."""
    opts = [(b, _quality_value(b.text)) for b in buttons]
    for b, q in opts:
        if str(q) == str(QUALITY_PREF).rstrip("p"):
            return b
    return max(opts, key=lambda x: x[1])[0]


def _is_gate(m) -> bool:
    links = [b for b in flat_buttons(m) if getattr(b, "url", None) and _TME_RE.match(b.url)
             and not _START_URL_RE.match(b.url)]
    if not links:
        return False
    has_check = any(getattr(b, "data", None) and _CHECK_RE.search(b.text or "") for b in flat_buttons(m))
    return bool(_GATE_TEXT_RE.search(m.message or "") or has_check)


async def _join(client, url: str) -> str | None:
    """Kanalga a'zo bo'ladi. Natija matni (adminga) yoki None (o'tkazib yuborildi)."""
    m = _TME_RE.match(url.strip())
    if not m:
        return None
    path = m.group(1).rstrip("/")
    try:
        if path.startswith("+") or path.lower().startswith("joinchat/"):
            h = path.lstrip("+") if path.startswith("+") else path.split("/", 1)[1]
            await client(functions.messages.ImportChatInviteRequest(h))
        else:
            username = path.split("/")[0]
            if username.lower().endswith("bot"):
                return None
            await client(functions.channels.JoinChannelRequest(await client.get_input_entity(username)))
        return f"✓ a'zo bo'ldim: {path}"
    except errors.UserAlreadyParticipantError:
        return None
    except errors.InviteRequestSentError:
        return f"! {path}: a'zolik so'rovi yuborildi (admin tasdiqlashi kerak)"
    except errors.FloodWaitError as e:
        logger.warning("a'zo bo'lishda FloodWait %ss (%s)", e.seconds, path)
        return f"✕ {path}: Telegram {e.seconds}s kutishni so'radi"
    except Exception as e:
        logger.warning("a'zo bo'linmadi %s: %s", path, e)
        return f"✕ {path}: {type(e).__name__}"


async def _drain(conv, idle: float, sink: list) -> None:
    while True:
        try:
            m = await asyncio.wait_for(conv.get_response(), idle)
        except asyncio.TimeoutError:
            return
        sink.append(m)


async def _refresh(client, m):
    """Tahrirlangan xabarning (tugmalari o'zgargan) yangi holatini oladi."""
    try:
        fresh = await client.get_messages(m.chat_id, ids=m.id)
        return fresh or m
    except Exception:
        return m


def _key(m, b, extra=None) -> tuple:
    """Tugma kaliti: xabar + matn + xabardagi tugmalar to'plami (+ joriy qism). Tugmalar o'zgarsa (yangi sahifa,
    qayta chiqqan sifat tanlovi) — yangi kalit, ya'ni qayta bosish mumkin; aynan o'sha holat takrorlanmaydi."""
    return (m.id, b.text, tuple(x.text for x in flat_buttons(m)), extra)


def _next_action(cards: dict, done: set, pages: int, cur_ep=None):
    """('quality'|'episode'|'next', xabar, tugma[, boshqa_sifatlar]) yoki None."""
    msgs = [cards[k] for k in sorted(cards, reverse=True)]
    for m in msgs:                                        # 1) sifat tanlovi (har bir qism uchun alohida)
        q = [b for b in flat_buttons(m) if getattr(b, "data", None) and _quality_value(b.text) and _key(m, b, cur_ep) not in done]
        if q:
            return "quality", m, _pick_quality(q), q
    eps = []
    for m in msgs:                                        # 2) qism raqamlari
        for b in flat_buttons(m):
            mm = _EP_BTN_RE.match(b.text or "")
            if (mm and getattr(b, "data", None) and not _SKIP_BTN_RE.search(b.text) and not _quality_value(b.text)
                    and _key(m, b) not in done):
                eps.append((int(mm.group(1)), m, b))
    if eps:
        n, m, b = min(eps, key=lambda x: x[0])
        return "episode", m, b, n
    if pages < 20:                                        # 3) keyingi sahifa
        for m in msgs:
            for b in flat_buttons(m):
                if getattr(b, "data", None) and _NEXT_RE.search(b.text or "") and _key(m, b) not in done:
                    return "next", m, b, None
    return None


async def fetch_from_source(client, source_bot: str, code: str, post=None, notify=None,
                            idle: float = 12.0, click_idle: float = 8.0):
    """(info_text, {qism_raqami: telethon_message}, debug_matn) qaytaradi."""
    links = deep_links(post, source_bot) if post is not None else []
    payload = links[0][1] if links else code

    got: list = []
    cards: dict = {}                 # id -> xabar (tugmali), tahrirlansa yangilanadi
    ep_msgs: dict[int, object] = {}
    loose: list = []
    done: set = set()
    cur_ep = None
    joined: list[str] = []
    gate_rounds = 0
    pages = 0

    async with client.conversation(source_bot, timeout=120, total_timeout=1800, max_messages=1000) as conv:

        async def pull(wait: float) -> None:
            nonlocal cur_ep
            new: list = []
            await _drain(conv, wait, new)
            for m in new:
                got.append(m)
                if flat_buttons(m):
                    cards[m.id] = m
                if is_video(m):
                    n = cur_ep if cur_ep is not None else episode_no(m.message)
                    if n is not None:
                        ep_msgs.setdefault(n, m)
                    else:
                        loose.append(m)

        await conv.send_message(f"/start {payload}")
        await pull(idle)
        if not got:                                   # deep link javobsiz — oddiy kod
            await conv.send_message(code)
            await pull(idle)

        for _ in range(MAX_STEPS):
            gate = next((cards[k] for k in sorted(cards, reverse=True) if _is_gate(cards[k])
                         and (cards[k].id, "gate") not in done), None)
            if gate and gate_rounds < MAX_GATE_ROUNDS:
                gate_rounds += 1
                done.add((gate.id, "gate"))
                urls = [b.url for b in flat_buttons(gate) if getattr(b, "url", None) and _TME_RE.match(b.url)
                        and not _START_URL_RE.match(b.url)][:MAX_JOIN]
                for u in urls:
                    r = await _join(client, u)
                    if r:
                        joined.append(r)
                    await asyncio.sleep(2)
                chk = next((b for b in flat_buttons(gate) if getattr(b, "data", None) and _CHECK_RE.search(b.text or "")), None)
                if chk:
                    try:
                        await chk.click()
                    except Exception:
                        pass
                else:
                    await conv.send_message(f"/start {payload}")
                await pull(click_idle)
                cards[gate.id] = await _refresh(client, gate)
                continue

            act = _next_action(cards, done, pages, cur_ep)
            if not act:
                break
            kind, m, b = act[0], act[1], act[2]
            if kind == "quality":
                done.update(_key(m, x, cur_ep) for x in act[3])
            else:
                done.add(_key(m, b))
            if kind == "episode":
                cur_ep = act[3]
            elif kind == "next":
                pages += 1
            try:
                await b.click()
            except Exception as e:                    # callback'ga javob bo'lmasligi mumkin — baribir video kelishi mumkin
                logger.info("tugma '%s' bosildi (callback javobsiz: %s)", b.text, type(e).__name__)
            await pull(click_idle)
            cards[m.id] = await _refresh(client, m)

    if joined and notify:
        await notify("◈ Majburiy obuna:\n" + "\n".join(joined))

    episodes = dict(ep_msgs)
    used = set(episodes)
    seq = 0
    for m in loose:
        n = episode_no(m.message)
        if n is None or n in used:
            seq += 1
            while seq in used:
                seq += 1
            n = seq
        used.add(n)
        episodes.setdefault(n, m)

    info_parts = [m.message for m in got if m.message]
    btn_txt = " | ".join(b.text for k in sorted(cards) for b in flat_buttons(cards[k]) if b.text)
    debug = (f"javoblar: {len(got)} ta, videolar: {sum(1 for m in got if is_video(m))} ta\n"
             f"kirish: /start {payload}\ntugmalar: {btn_txt or '—'}\n"
             f"oxirgi matn: {(info_parts[-1] if info_parts else '—')[:200]}")
    return "\n".join(info_parts), dict(sorted(episodes.items())), debug
