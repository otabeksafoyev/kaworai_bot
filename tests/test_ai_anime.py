from utils.ai_anime import _clean_list, _map_status, _parse_duration_minutes, jikan_to_fields
from handlers.genres import GENRES


def test_duration_parsing():
    assert _parse_duration_minutes("24 min per ep") == 24
    assert _parse_duration_minutes("1 hr 55 min") == 115
    assert _parse_duration_minutes(None) is None


def test_status_mapping():
    assert _map_status("Finished Airing") == "completed"
    assert _map_status("Currently Airing") == "ongoing"
    assert _map_status("Not yet aired") == "announced"


def test_jikan_to_fields():
    item = {
        "title": "Shingeki no Kyojin", "title_english": "Attack on Titan", "type": "TV",
        "episodes": 25, "status": "Finished Airing", "duration": "24 min per ep",
        "year": 2013, "score": 8.56,
        "genres": [{"name": "Action"}, {"name": "Suspense"}, {"name": "Avant Garde"}],
        "themes": [{"name": "Psychological"}], "demographics": [{"name": "Shounen"}],
        "images": {"jpg": {"large_image_url": "https://cdn.myanimelist.net/x.jpg"}},
        "synopsis": "Humanity vs giants.",
    }
    f = jikan_to_fields(item)
    assert f["year"] == 2013 and f["rating"] == 8.6 and f["episodes_count"] == 25
    assert f["status"] == "completed" and f["content_type"] == "anime" and f["duration"] == 24
    assert set(f["genres"]) == {"Jang", "Triller", "Psixologik", "Shonen"}
    assert all(g in GENRES for g in f["genres"])


def test_clean_list_filters_unknown():
    assert _clean_list(["dark", "bogus", "Dark"], ["dark", "funny"], 3) == ["dark"]


def test_split_season_and_pick():
    from utils.ai_anime import _pick_best, split_season

    assert split_season("mushoku tensei: jobless reincarnation season 3") == ("mushoku tensei: jobless reincarnation", 3)
    assert split_season("Naruto 2nd Season") == ("Naruto", 2)
    assert split_season("Death Note") == ("Death Note", None)
    results = [{"title": "Mushoku Tensei", "title_english": "Jobless Reincarnation"},
               {"title": "Mushoku Tensei II", "title_english": "Jobless Reincarnation Season 2"}]
    assert _pick_best(results, "x", 2)[1] is True
    assert _pick_best(results, "x", 3) == (results[0], False)


def test_parse_edit():
    from handlers.admin_ai import _parse_edit

    assert _parse_edit("year", "2026") == (2026, None)
    assert _parse_edit("year", "-") == (None, None)
    assert _parse_edit("rating", "8,4") == (8.4, None)
    assert _parse_edit("rating", "11")[1]
    assert _parse_edit("episodes_count", "abc")[1]
    assert _parse_edit("mood", "dark, Jangari") == (["dark", "action"], None)   # kalit yoki o'zbekcha nom
    assert _parse_edit("mood", "emotional")[1]                                    # botda bunday kayfiyat yo'q
    assert _parse_edit("mood", "zzz")[1]
    assert _parse_edit("tags", "revenge, magic") == (["revenge", "magic"], None)
    assert _parse_edit("tags", "revenge, bogus")[1]
    assert _parse_edit("genres", "Jang, Drama")[0] == ["Jang", "Drama"]


def test_parse_edit_inline_url():
    from handlers.admin_ai import _parse_edit

    assert _parse_edit("inline_thumbnail_url", "https://x.y/a.jpg") == ("https://x.y/a.jpg", None)
    assert _parse_edit("inline_thumbnail_url", "abc")[1]
