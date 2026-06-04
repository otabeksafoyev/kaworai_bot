"""
utils/sleep_reminder.py — Ko'p ko'rish va uxlash eslatmasi

Trigger shartlari (istalgan biri bajarilsa):
  1. Kechqurun 22:00–05:00 oralig'ida 6+ qism ko'rilsa
  2. Kunduz bo'lsa 12+ qism ko'rilsa
  3. 12+ turli video ko'rilsa (qismdan qatʼi nazar)

Xabar:
  - Kontentning janri/kayfiyatiga mos
  - Hazilomuz, xushchaqchaq, qisqa
  - Global thumbnail (kunduz/kecha) bilan birga yuboriladi
"""

from __future__ import annotations

import random
import time
from datetime import datetime, timezone

# ── Sozlamalar ────────────────────────────────────────────────────
_UZB_UTC_OFFSET = 5
_WINDOW_SEC = 2 * 60 * 60          # 2 soatlik oyna
NIGHT_EP_LIMIT = 6                 # Kecha: 6+ qism → trigger
DAY_EP_LIMIT = 12                  # Kunduz: 12+ qism → trigger
VIDEO_LIMIT = 12                   # 12+ turli video → trigger (har doim)

# user_id → {"episodes": int, "videos": set, "window_start": float}
_SESSION: dict[int, dict] = {}

# Bir oynada faqat bitta alert
_ALERTED: set[int] = set()

# ── Vaqt yordamchilari ────────────────────────────────────────────


def _uzb_hour() -> int:
    utc_now = datetime.now(tz=timezone.utc)
    return (utc_now.hour + _UZB_UTC_OFFSET) % 24


def is_night_time() -> bool:
    h = _uzb_hour()
    return h >= 22 or h < 5


# ── Xabarlar ─────────────────────────────────────────────────────
# Janr → xabarlar ro'yxati
# Har bir xabar qisqa, xushchaqchaq, hazilomuz va o'rinli

GENRE_MESSAGES: dict[str, list[str]] = {
    "romantic": [
        "💕 Romantik qismlarni ko'p ko'rdingiz — ko'zlaringiz ham biroz dam olsin! 😄",
        "🌸 Sevgi dramalarida g'arq bo'libsiz, lekin endi yostig'ingiz bilan muomala qiling! 🛌",
        "💘 Ekrandagi muhabbat chiroyli, lekin tush ko'rish ham yaxshi — uxlang! 😴",
    ],
    "action": [
        "⚔️ Ko'p jang ko'rdingiz, endi o'zingiz dam oling — jangchi ham uxlaydi! 😄",
        "💪 Qahramonlar ham uxlaydi, siz-chi? Biroz dam oling! 🌙",
        "🥊 Adrenaliningiz tushsin endi — ko'zlaringizni yuming! 😴",
    ],
    "comedy": [
        "😂 Qotib kulib charchadingizmi? Kulib-kulib uxlang endi! 🌙",
        "🤣 Yetarli kuldingiz, endi yostiqqa bosh qo'yish vaqti! 😴",
        "😄 Kulgidan ko'zlaringizda yosh — endi rohat bilan uxlang! 💤",
    ],
    "horror": [
        "😱 Ko'rgan narsalaringizni unutish uchun uxlang — tushingiz boshqacha bo'ladi! 🌙",
        "🕷️ Qo'rqinchli qismlar ko'rdingiz, endi chiroqni yoqib uxlang! 😄",
        "👻 Arvohlar ham uxlaydi — siz ham uxlang! 💤",
    ],
    "fantasy": [
        "🧙 Sehrli dunyodan qaytish vaqti — real dunyoda ham tush ko'rasiz! 🌙",
        "✨ Fantastik sayohatingiz tugadi, endi sirli tushlar vaqti! 😴",
        "🐉 Ajdarho ham uxlaydi — siz ham qilichingizni qo'ying! 💤",
    ],
    "drama": [
        "🎭 Ko'p drama ko'rdingiz — endi o'zingizning dramangizni boshlamang, uxlang! 😄",
        "😢 Ko'z yoshlari qurisin — yaxshi uxlash eng yaxshi dori! 🌙",
        "🎬 Dramatik kecha bo'ldi — endi tinch uxlash vaqti! 💤",
    ],
    "thriller": [
        "🔍 Sirlarni hal qildingizmi? Endi miyangizga dam bering! 🌙",
        "⏰ Suspens tugadi — endi relax qiling va uxlang! 😴",
        "🕵️ Detektiv miya ko'p ishladi — dam olish vaqti! 💤",
    ],
}

# Umumiy xabarlar (janr aniqlanmasa)
GENERAL_MESSAGES: list[str] = [
    "🌙 Ancha vaqt bo'ldi — ko'zlaringizga biroz dam bering! 😊",
    "✨ Zo'r kontentlar ko'rdingiz! Endi tush ko'rish vaqti — uxlang! 💤",
    "🎬 Film rejissyori ham uxlaydi — siz ham uxlang! 😄",
    "🍿 Popcorn tugadimi? Demak dam olish vaqti! 🌙",
    "😴 Ko'zlaringiz og'irlaşgan bo'lsa — bu signal! Uxlang! 💤",
    "🌟 Ajoyib kecha bo'ldi — endi chiroyli tushlar ko'ring! 🌙",
    "🎭 Bugunlik shuncha — ertaga yangi qismlar kutadi! 😊💤",
    "🛌 Ekran o'chsin, ko'zlar yumilsin — xayrli tun! 🌙",
]

# Kunduz uchun boshqacha xabarlar (dam olish emas, pauza)
DAY_MESSAGES: list[str] = [
    "☀️ Ancha ko'rdingiz! Biroz ko'zlaringizni dam oldirib keling 👁️",
    "🍵 Ko'p qism ko'rdingiz — bir piyola choy iching, ko'zlaringizni dam oldiring! ☕",
    "🚶 Ko'zlaringizga biroz pauza — 5 daqiqa yurish foydali! 😊",
    "🌿 Ekrandan uzoqlashib, uzoqdagi narsaga 20 soniya qarang — ko'z mashqi! 👁️✨",
    "😄 Juda zo'r tanladsiz! Lekin ko'zlaringiz ham siz bilan birga dam olsin!",
]


def _pick_message(genres: list[str], moods: list[str]) -> str:
    """Janr/kayfiyatga mos xabar tanlaydi."""
    if is_night_time():
        # Kechqurun — janrga mos uxlash xabari
        all_tags = [g.lower() for g in (genres or [])] + [m.lower() for m in (moods or [])]
        for tag in all_tags:
            for key, msgs in GENRE_MESSAGES.items():
                if key in tag or tag in key:
                    return random.choice(msgs)
        return random.choice(GENERAL_MESSAGES)
    else:
        # Kunduz — pauza xabari
        return random.choice(DAY_MESSAGES)


# ── Asosiy funksiya ───────────────────────────────────────────────


def record_episode_view(
    user_id: int,
    anime_id: int | None = None,
    genres: list[str] | None = None,
    moods: list[str] | None = None,
) -> str | None:
    """
    Qism ko'rilganini qayd etadi.

    Trigger shartlari:
    - Kecha (22:00-05:00): 6+ qism → alert
    - Kunduz: 12+ qism → alert
    - Har doim: 12+ turli anime → alert

    Returns:
        str: Xabar matni (yuborish uchun)
        None: Hali trigger bo'lmagan
    """
    now = time.monotonic()
    night = is_night_time()

    data = _SESSION.get(user_id)
    if data is None or (now - data.get("window_start", 0)) > _WINDOW_SEC:
        # Yangi oyna
        _SESSION[user_id] = {
            "episodes": 1,
            "videos": {anime_id} if anime_id else set(),
            "window_start": now,
        }
        _ALERTED.discard(user_id)
        return None

    # Mavjud oynadagi counter
    data["episodes"] = data.get("episodes", 0) + 1
    if anime_id:
        data.setdefault("videos", set()).add(anime_id)

    ep_count = int(data["episodes"])
    video_count = len(data.get("videos", set()))

    if user_id in _ALERTED:
        return None

    ep_limit = NIGHT_EP_LIMIT if night else DAY_EP_LIMIT
    triggered = ep_count >= ep_limit or video_count >= VIDEO_LIMIT

    if triggered:
        _ALERTED.add(user_id)
        return _pick_message(genres or [], moods or [])

    return None


def reset_nightly_alerts() -> None:
    """Har kuni ertalab chaqiriladi — kechagi alertlarni tozalaydi."""
    _ALERTED.clear()
