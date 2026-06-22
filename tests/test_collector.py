from datetime import date

from digest.collector import _google_news_url, _normalize_title, _score, parse_feed
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
