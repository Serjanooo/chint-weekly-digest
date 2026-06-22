from datetime import date

from digest.collector import (
    _google_news_url,
    _date_from_url,
    _is_chint_russia,
    _normalize_title,
    _resolve_google_article,
    _score,
    parse_feed,
)
from digest.models import Article
from datetime import datetime, timezone


def test_parse_rss_item():
    payload = b'''<?xml version="1.0"?><rss><channel><item><title>AI &amp; energy</title><link>https://example.com/a</link><pubDate>Sun, 21 Jun 2026 12:00:00 +0000</pubDate><description><![CDATA[<b>Useful</b> text]]></description><source>Test</source></item></channel></rss>'''
    items = parse_feed(payload, "Fallback")
    assert len(items) == 1
    assert items[0].title == "AI & energy"
    assert items[0].summary == "Useful text"
    assert items[0].source == "Test"


def test_google_query_has_exclusive_end():
    url = _google_news_url("энергетика", date(2026, 6, 15), date(2026, 6, 22))
    assert "after%3A2026-06-15" in url
    assert "before%3A2026-06-22" in url


def test_date_is_read_from_news_url():
    parsed = _date_from_url("https://www.ruscable.ru/news/2026/06/17/example/")
    assert parsed and parsed.date().isoformat() == "2026-06-17"


def test_title_normalization_removes_source_suffix():
    assert _normalize_title("Новая энергетика — РБК") == "новая энергетика"


def test_negative_news_penalty():
    config = {
        "topic_keywords": [{"weight": 4, "terms": ["энерг"]}],
        "source_weights": {},
        "negative_keywords": [{"weight": 5, "terms": ["обстрел"]}],
    }
    article = Article("1", "Обстрел объекта энергетики", "https://example.com", "Test", datetime.now(timezone.utc), "")
    assert _score(article, config) == -1


def test_google_url_is_replaced_with_direct_source(monkeypatch):
    article = Article(
        "1",
        "CHINT в России представил новое решение",
        "https://news.google.com/rss/articles/example?oc=5",
        "Elec.ru",
        datetime.now(timezone.utc),
        "",
        source_home="https://www.elec.ru",
    )
    monkeypatch.setattr(
        "digest.collector.new_decoderv1",
        lambda _: {"status": True, "decoded_url": "https://www.elec.ru/news/example/?utm_source=google"},
    )
    resolved = _resolve_google_article(article, ["elec.ru"])
    assert resolved is article
    assert article.url == "https://www.elec.ru/news/example/"


def test_google_url_with_untrusted_domain_is_rejected(monkeypatch):
    article = Article(
        "1",
        "Новость",
        "https://news.google.com/rss/articles/example?oc=5",
        "Elec.ru",
        datetime.now(timezone.utc),
        "",
        source_home="https://www.elec.ru",
    )
    monkeypatch.setattr(
        "digest.collector.new_decoderv1",
        lambda _: {"status": True, "decoded_url": "https://untrusted.example/news"},
    )
    assert _resolve_google_article(article, ["elec.ru"]) is None


def test_any_chint_mention_on_approved_russian_site_is_marked():
    approved = Article(
        "1", "CHINT построил новый завод", "https://elec.ru/a", "Elec.ru", datetime.now(timezone.utc), ""
    )
    unapproved = Article(
        "2", "CHINT построил новый завод", "https://example.com/b", "Example", datetime.now(timezone.utc), ""
    )
    assert _is_chint_russia(approved)
    assert not _is_chint_russia(unapproved)
