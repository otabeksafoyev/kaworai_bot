from datetime import date

from utils.gamification import BADGES, earned_badges, level_info, xp_bar
from utils.season import current_season


def test_levels():
    assert level_info(0)[1] == "Yangi"
    assert level_info(99)[1] == "Yangi"
    assert level_info(100)[1] == "Otaku"
    assert level_info(500)[1] == "Senpai"
    assert level_info(1500)[1] == "Sensei"
    assert level_info(99999)[4] is None  # eng yuqori daraja


def test_xp_bar():
    bar, label = xp_bar(310)  # Otaku: 100 → 500
    assert label == "310 / 500 XP" and bar.startswith("▰") and len(bar) == 8
    assert xp_bar(2000)[1].endswith("MAX")
    assert xp_bar(None)[1] == "0 / 100 XP"


def test_badges():
    assert earned_badges({}) == []
    got = earned_badges({"episodes": 10, "ratings": 5, "streak": 7, "night": 1})
    assert {"first_ep", "ep_10", "rate_5", "streak_3", "streak_7", "night_owl"} <= set(got)
    assert "ep_50" not in got and "dorama_10" not in got
    assert earned_badges({"dorama_eps": 10}) == ["dorama_10"]
    assert all(k in BADGES for k in earned_badges({"episodes": 500, "ratings": 99, "streak": 99,
                                                    "favs": 9, "dorama_eps": 99, "night": 1, "invites": 9}))


def test_season():
    assert current_season(date(2026, 12, 31))[0] == "newyear"
    assert current_season(date(2027, 1, 2))[0] == "newyear"
    assert current_season(date(2026, 3, 21))[0] == "navruz"
    assert current_season(date(2027, 2, 20))[0] == "ramadan"
    assert current_season(date(2026, 6, 15)) is None
