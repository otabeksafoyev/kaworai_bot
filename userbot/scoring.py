"""Moslik foizi: kanal posti / manba bot ma'lumoti  <->  AI topgan ma'lumot.

Faqat ikkala tomonda ham bor bo'lgan belgilar solishtiriladi (nom, yil, janr, tavsif).
Og'irliklar: yil, janr va tavsif nomdan muhimroq — ular mos kelsa foiz ancha ko'tariladi.
Natija: (foiz 0..100, {belgi: foiz|None}).
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from .parsers import _norm

WEIGHTS = {"title": 25, "year": 20, "genres": 25, "desc": 30}
MIN_EVIDENCE = 45          # mavjud belgilar og'irligi yig'indisi shundan kam bo'lsa — dalil yetarli emas
LOW_EVIDENCE_CAP = 60      # dalil yetarli bo'lmasa foiz shundan oshmaydi (faqat nom mos kelsa 70% dan o'tmasin)
NOTE_CAP = 50              # AI "nom aniq topilmadi" (note) desa — foiz shundan oshmaydi

_YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
_GENRE_LINE = re.compile(r"(?i)(?:janr(?:lari|i)?|genres?|жанр\w*)\s*[:\-–—]\s*(.+)")
_DESC_LINE = re.compile(r"(?is)(?:tavsif(?:i)?|syujet|haqida|description|опис\w*|сюжет)\s*[:\-–—]\s*(.+)")
_SPLIT = re.compile(r"[,;/|•·\n]+|\s#")


def _ratio(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _stems(text: str) -> set[str]:
    """So'z o'zaklari (o'zbekcha qo'shimchalar farqi sezilmasin): 3+ harfli so'zlarning dastlabki 5 harfi."""
    return {w[:5] for w in _norm(text).split() if len(w) >= 3}


def title_score(title: str, english: str, info: dict) -> float | None:
    matched = (info.get("matched_title") or "").strip()
    if not matched:
        return None
    return max(_ratio(english or "", matched), _ratio(title or "", matched))


def year_score(claim_text: str, info_year) -> float | None:
    try:
        year = int(info_year)
    except (TypeError, ValueError):
        return None
    found = {int(y) for y in _YEAR_RE.findall(claim_text or "")}
    if not found:
        return None
    if year in found:
        return 1.0
    return 0.5 if any(abs(year - y) == 1 for y in found) else 0.0


def _claimed_genres(claim_text: str) -> list[str]:
    out: list[str] = []
    for m in _GENRE_LINE.finditer(claim_text or ""):
        for part in _SPLIT.split(m.group(1)):
            part = _norm(part)
            if 2 <= len(part) <= 30 and part not in out:
                out.append(part)
    return out


def genre_score(claim_text: str, info_genres) -> float | None:
    ai = [_norm(g) for g in (info_genres or []) if g]
    claimed = _claimed_genres(claim_text)
    if not ai or not claimed:
        return None
    hits = sum(1 for c in claimed if any(_ratio(c, g) >= 0.75 for g in ai))
    return hits / len(claimed)


def _claimed_desc(claim_text: str) -> str:
    m = _DESC_LINE.search(claim_text or "")
    if m:
        return m.group(1).strip()
    lines = [ln.strip() for ln in (claim_text or "").splitlines() if len(ln.strip()) >= 80]
    return max(lines, key=len) if lines else ""


def desc_score(claim_text: str, info_desc: str) -> float | None:
    claimed = _claimed_desc(claim_text)
    if not claimed or not (info_desc or "").strip():
        return None
    a, b = _stems(claimed), _stems(info_desc)
    if not a or not b:
        return None
    containment = len(a & b) / min(len(a), len(b))
    return min(1.0, containment / 0.5)        # 50% umumiy o'zak = to'liq moslik


def match_percent(title: str, english: str, claim_text: str, info: dict) -> tuple[int, dict]:
    parts = {
        "title": title_score(title, english, info),
        "year": year_score(claim_text, info.get("year")),
        "genres": genre_score(claim_text, info.get("genres")),
        "desc": desc_score(claim_text, info.get("desc") or ""),
    }
    have = {k: v for k, v in parts.items() if v is not None}
    total_w = sum(WEIGHTS[k] for k in have)
    if not total_w:
        return 0, {k: None for k in parts}
    score = sum(WEIGHTS[k] * v for k, v in have.items()) / total_w
    if total_w < MIN_EVIDENCE:
        score = min(score, LOW_EVIDENCE_CAP / 100)
    pct = round(score * 100)
    if info.get("note"):
        pct = min(pct, NOTE_CAP)
    return pct, {k: (None if v is None else round(v * 100)) for k, v in parts.items()}


def breakdown_text(parts: dict) -> str:
    names = {"title": "nom", "year": "yil", "genres": "janr", "desc": "tavsif"}
    return ", ".join(f"{names[k]} {'—' if v is None else str(v) + '%'}" for k, v in parts.items())
