"""Kanal posti va manba bot javobini tahlil qilish.
Manba kanal/bot formati o'zgarsa — faqat shu fayldagi regexlarni o'zgartiring."""
from __future__ import annotations

import os
import re
from difflib import SequenceMatcher

# Postdagi kod: "Kod: 123", "Kodi - 123", "Code: 123", "ID: 123"
CODE_RE = re.compile(os.environ.get("UB_CODE_RE", r"(?i)(?:kodi?|code|id|№|#)\s*[:\-–—=]?\s*(\d{1,7})"))
# Ingliz nom (bo'lsa): "English: Solo Leveling", "Inglizcha: ...", "Romaji: ..."
ENG_RE = re.compile(r"(?i)(?:english|inglizcha|inglis|romaji|eng)\s*(?:nomi)?\s*[:\-–—]\s*(.+)")
# Nom qatori: "Nomi: ...", "Anime: ..."
NAME_RE = re.compile(r"(?i)(?:nomi|nom|name|anime|dorama|serial|kino)\s*[:\-–—]\s*(.+)")
EP_RE = [
    re.compile(r"(?i)(\d{1,4})\s*[-–]?\s*(?:qism|seriya|эпизод|серия|ep(?:isode)?)"),
    re.compile(r"(?i)(?:qism|seriya|ep(?:isode)?|part)\s*[:#\-–]?\s*(\d{1,4})"),
]

_JUNK = re.compile(r"[^\w\s'ʻ’‘`-]", re.UNICODE)


def clean_line(s: str) -> str:
    s = _JUNK.sub(" ", s or "")
    s = re.sub(r"\s+", " ", s).strip(" -–—:|")
    return s


def parse_post(text: str) -> tuple[str | None, str | None, str | None]:
    """(nom, kod, inglizcha_nom) — topilmasa None."""
    text = (text or "").strip()
    if not text:
        return None, None, None
    m = CODE_RE.search(text)
    code = m.group(1) if m else None
    em = ENG_RE.search(text)
    eng = clean_line(em.group(1)) if em else None
    nm = NAME_RE.search(text)
    if nm:
        title = clean_line(nm.group(1))
    else:
        title = None
        for line in text.splitlines():
            c = clean_line(line)
            if len(c) >= 2 and not CODE_RE.fullmatch(line.strip()) and not ENG_RE.search(line):
                title = c
                break
    return title or None, code, eng


def episode_no(caption: str | None) -> int | None:
    for p in EP_RE:
        m = p.search(caption or "")
        if m:
            return int(m.group(1))
    return None


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[ʻ’‘`']", "", s)
    return re.sub(r"[^\w]+", " ", s, flags=re.UNICODE).strip()


def same_title(a: str, b_text: str, threshold: float = 0.72) -> bool:
    """Kanal nomi (a) manba bot javobida (b_text) bormi — erkin taqqoslash."""
    a, b = _norm(a), _norm(b_text)
    if not a or not b:
        return False
    if a in b:
        return True
    best = 0.0
    for line in (_norm(x) for x in b_text.splitlines()):
        if line:
            best = max(best, SequenceMatcher(None, a, line).ratio())
    ta, tb = set(a.split()), set(b.split())
    overlap = len(ta & tb) / max(1, len(ta))
    return best >= threshold or overlap >= 0.8
