"""
utils/season.py — mavsumiy bayramlar: bosh menyu salomi va (ixtiyoriy) bayram banneri.

Banner rasmlari kodda emas: Railway'da `BANNER_<KALIT>` o'zgaruvchisiga file_id yoki URL qo'yiladi
(masalan BANNER_NEWYEAR). O'zgaruvchi bo'lmasa — odatdagi rasm ishlatiladi, faqat salom qatori chiqadi.
Ramazon sanalari taxminiy (oy kalendari): har yili tekshirib turing.
"""

from __future__ import annotations

import os
from datetime import date

# (kalit, matn, boshlanish (oy, kun), tugash (oy, kun))
_FIXED = [
    ("newyear", "✧ Yangi yil bilan! ✧", (12, 25), (1, 3)),
    ("navruz", "✧ Navro'z muborak! ✧", (3, 20), (3, 23)),
    ("independence", "✧ Mustaqillik kuni muborak! ✧", (8, 31), (9, 2)),
]
# Ramazon (taxminiy): yil → (boshlanish, tugash)
_RAMADAN = {
    2027: (date(2027, 2, 8), date(2027, 3, 9)),
    2028: (date(2028, 1, 28), date(2028, 2, 26)),
    2029: (date(2029, 1, 16), date(2029, 2, 14)),
}


def current_season(today: date) -> tuple[str, str] | None:
    """(kalit, matn) yoki None."""
    rng = _RAMADAN.get(today.year)
    if rng and rng[0] <= today <= rng[1]:
        return "ramadan", "✧ Ramazon muborak! ✧"
    md = (today.month, today.day)
    for key, text, start, end in _FIXED:
        if start <= end:
            if start <= md <= end:
                return key, text
        elif md >= start or md <= end:  # yil oxiridan boshiga o'tadigan oraliq
            return key, text
    return None


def season_banner(key: str | None) -> str | None:
    """Railway'dagi BANNER_<KALIT> (file_id yoki URL)."""
    if not key:
        return None
    return os.getenv(f"BANNER_{key.upper()}") or None
