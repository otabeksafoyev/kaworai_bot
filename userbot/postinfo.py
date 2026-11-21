"""Postdagi ma'lumotlar (yil, janr, tavsif). AI topa olmasa yoki boshqa asarni topib adashsa — shular ishlatiladi."""
from __future__ import annotations

import re

AI_TRUST = 50          # AI moslik foizi shundan past bo'lsa, AI natijasiga ishonilmaydi (faqat post ma'lumoti olinadi)

_GENRE_LINE = re.compile(r"(?i)(?:janr(?:lari|i)?|genres?|жанр\w*)\s*[:\-–—]\s*(.+)")
_SPLIT = re.compile(r"[,;/|•·]+|\s#")
_DESC_LINE = re.compile(r"(?is)(?:qisqacha|tavsif(?:i)?|syujet|haqida|description|опис\w*|сюжет)\s*[:\-–—]\s*(.+)")
_YEAR_PAREN = re.compile(r"[\(\[]\s*((?:19|20)\d{2})\s*[\)\]]")
_YEAR_LINE = re.compile(r"(?i)(?:yil|year|год)\w*\s*[:\-–—]\s*((?:19|20)\d{2})")
_FOOTER = re.compile(r"(?i)(t\.me/|https?://|^\W*@\w{4,})")


def post_genres(text: str) -> list[str]:
    out: list[str] = []
    for m in _GENRE_LINE.finditer(text or ""):
        for part in _SPLIT.split(m.group(1)):
            g = re.sub(r"\s+", " ", part.strip().lstrip("#").strip(" .,"))
            if 2 <= len(g) <= 30 and g.lower() not in {x.lower() for x in out}:
                out.append(g[:1].upper() + g[1:])
    return out[:6]


def post_desc(text: str) -> str:
    m = _DESC_LINE.search(text or "")
    if not m:
        return ""
    lines: list[str] = []
    for ln in m.group(1).splitlines():
        if not ln.strip() or _FOOTER.search(ln):
            break
        lines.append(ln.strip())
    return re.sub(r"\s+", " ", " ".join(lines)).strip()[:1000]


def post_year(text: str) -> int | None:
    m = _YEAR_PAREN.search(text or "") or _YEAR_LINE.search(text or "")
    return int(m.group(1)) if m else None


def post_info(text: str) -> dict:
    return {"desc": post_desc(text), "genres": post_genres(text), "year": post_year(text)}


def merge_info(ai: dict, post: dict, pct: int | None) -> dict:
    """Post ma'lumoti (tavsif, janr, yil) ustun. AI ishonchsiz (topilmagan yoki pct < AI_TRUST) bo'lsa,
    uning qo'shimchalari (teg, mood, reyting, davomiylik, status) ham tashlanadi."""
    ai = dict(ai or {})
    reliable = pct is not None and pct >= AI_TRUST
    out = ai if reliable else {k: ai[k] for k in ("sources", "errors", "note") if k in ai}
    for k in ("desc", "genres", "year"):
        if post.get(k):
            out[k] = post[k]
    return out
