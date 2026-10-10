from contextvars import copy_context
from datetime import datetime

from utils.ui import (
    anime_start_link, current_user_id, greeting, parse_start_args,
    progress_bar, rating_stars, referral_link, share_anime_url,
)


def test_rating_stars():
    assert rating_stars(10) == "★★★★★"
    assert rating_stars(8.9) == "★★★★☆"
    assert rating_stars(9.6) == "★★★★★"
    assert rating_stars(6.0) == "★★★☆☆"
    assert rating_stars(0) == "☆☆☆☆☆"
    assert rating_stars(None) == "☆☆☆☆☆"


def test_progress_bar():
    assert progress_bar(4, 12) == "▰▰▰▱▱▱▱▱"
    assert progress_bar(12, 12) == "▰" * 8
    assert progress_bar(1, 100).startswith("▰")  # 1-qism ham ko'rinsin
    assert progress_bar(0, 0) == "▱" * 8


def test_greeting_uses_uzbek_time():
    assert "tong" in greeting(datetime(2026, 1, 1, 1, 0))   # UTC 01 → 06:00 UZT
    assert "kun" in greeting(datetime(2026, 1, 1, 8, 0))    # 13:00
    assert "kech" in greeting(datetime(2026, 1, 1, 14, 0))  # 19:00
    assert "tun" in greeting(datetime(2026, 1, 1, 20, 0))   # 01:00


def test_parse_start_args():
    assert parse_start_args("anime_623") == (623, None)
    assert parse_start_args("anime_623_r555") == (623, 555)
    assert parse_start_args("ref_555") == (None, 555)
    assert parse_start_args("kod_12") == (12, None)
    assert parse_start_args("77") == (77, None)
    assert parse_start_args("anime_x") == (None, None)
    assert parse_start_args(None) == (None, None)


def test_links_carry_referrer_only_when_known():
    assert "_r" not in share_anime_url(5)
    ctx = copy_context()

    def inside():
        current_user_id.set(42)
        return share_anime_url(5), anime_start_link(5)

    share, link = ctx.run(inside)
    assert share.endswith("anime_5_r42") and link.endswith("anime_5_r42")
    assert referral_link(42).endswith("?start=ref_42")
