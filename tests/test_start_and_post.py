"""Start tugmalari mantig'i va yangi post caption formati."""

from types import SimpleNamespace

from utils.start_cfg import audience_ok, to_inline


def test_audience_filter():
    pro = {"audience": "pro"}
    usr = {"audience": "user"}
    allb = {"audience": "all"}
    assert audience_ok(pro, True) and not audience_ok(pro, False)
    assert audience_ok(usr, False) and not audience_ok(usr, True)
    assert audience_ok(allb, True) and audience_ok(allb, False)


def test_link_button_opens_url_reply_button_is_callback():
    link = to_inline({"id": "a1", "label": "Kanal", "kind": "link", "url": "https://t.me/x"})
    reply = to_inline({"id": "b2", "label": "Pro haqida", "kind": "reply", "text": "hi"})
    assert link.url == "https://t.me/x" and link.callback_data is None
    assert reply.callback_data == "sbtn_b2" and reply.url is None


def _anime(**kw):
    base = dict(
        id=101, title="Katta sichqon", year=2022, genres=["Drama", "Sirli", "Sci-Fi"], rating=8.7, rating_count=2,
        episodes_count=16, total_episodes=16, duration=70, status="completed", content_type="dorama",
        description="Hikoya oddiy advokat haqida. " * 30, tags=["crime"], mood=["dark"], views=5, popularity=8.7,
        is_pro_locked=True, is_hidden_gem=True,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_post_caption_is_short_and_clean():
    from handlers.admin import _build_post_caption, _build_short_caption

    cap = _build_post_caption(_anime())
    assert "Katta sichqon" in cap and "#Drama #Sirli #SciFi" in cap and "Kodi: <code>101</code>" in cap
    assert "<blockquote expandable>" in cap
    for removed in ("Tag:", "Kayfiyat", "Hidden gem", "⊘ Pro", "(2)"):
        assert removed not in cap
    assert len(cap) < 1024  # Telegram caption limit
    assert len(_build_short_caption(_anime())) < len(cap)


def test_post_caption_without_optional_fields():
    from handlers.admin import _build_post_caption

    cap = _build_post_caption(_anime(rating=0, description="", duration=None, episodes_count=None, total_episodes=0, genres=[]))
    assert "Reyting" not in cap and "Qism" not in cap and "Janr" not in cap and "blockquote" not in cap
