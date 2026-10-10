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
