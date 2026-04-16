"""
Kichik yordamchilar — Telegram HTML parse_mode uchun ishonchsiz matnlarni
ekran qilish (HTML injection'dan himoya).

Foydalanuvchilarning `full_name`/`username`/`caption` kabi maydonlari matn
ichiga to'g'ridan-to'g'ri qo'yilsa, ular HTML teglarini o'z ichiga olishi
mumkin. Telegram skriptlarni ishga tushirmasada, <a> teglari orqali
fishing havolalar, buzilgan formatlash va admin xabarlarining
qalbakilashtirilishiga olib kelishi mumkin.
"""

from __future__ import annotations

import html
import logging
from typing import Any

logger = logging.getLogger(__name__)


def esc(value: Any) -> str:
    """
    Istalgan qiymatni HTML-safe satrga aylantiradi.

    None → "—" sifatida qaytariladi, shunda qo'l bilan tekshirish shart emas.
    """
    if value is None:
        return "—"
    return html.escape(str(value), quote=False)


def parse_admin_ids(raw: str) -> list[str]:
    """
    `ADMIN_ID` env o'zgaruvchisidan kelgan qiymatni tozalaydi.

    - Bo'sh bo'laklarni (`""`) olib tashlaydi.
    - Probellarni trim qiladi.

    Bu muhim — chunki bo'sh satr `""` ni ro'yxatda qoldirish `"" in admins`
    chekini buzadi va ba'zi hollarda avtorizatsiya tizimini mantiqan
    noto'g'ri holatga keltirishi mumkin.
    """
    return [part.strip() for part in (raw or "").split(",") if part.strip()]
