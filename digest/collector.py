from __future__ import annotations

import hashlib
import html
import json
import re
import ssl
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, time, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from difflib import SequenceMatcher

from .models import Article

USER_AGENT = "Mozilla/5.0 (compatible; CHINTDigest/1.0; +https://github.com/)"
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _fetch(url: str, timeout: int = 20) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return response.read()


def _clean(value: str | None) -> str:
    if not value:
        return ""
    return SPACE_RE.sub(" ", html.unescape(TAG_RE.sub(" ", value))).strip()


def _child_text(item: ET.Element, names: tuple[str, ...]) -> str:
    for child in item.iter():
        local = child.tag.rsplit("}", 1)[-1].lower()
        if local in names and child.text:
            return child.text.strip()
    return ""


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_feed(payload: bytes, label: str, query: str = "") -> list[Article]:
    root = ET.fromstring(payload.lstrip(b"\xef\xbb\xbf"))
    articles: list[Article] = []
    nodes = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1].lower() in {"item", "entry"}]
    for item in nodes:
        title = _clean(_child_text(item, ("title",)))
        link = _child_text(item, ("link",))
        if not link:
            for child in item.iter():
                if child.tag.rsplit("}", 1)[-1].lower() == "link" and child.attrib.get("href"):
                    link = child.attrib["href"]
                    break
        published = _parse_date(_child_text(item, ("pubdate", "published", "updated", "date")))
        summary = _clean(_child_text(item, ("description", "summary", "encoded", "content")))
        source = _clean(_child_text(item, ("source",))) or label
        if title and link and published:
            article_id = hashlib.sha1(f"{title}|{link}".encode()).hexdigest()[:12]
            articles.append(Article(article_id, title, link, source, published, summary[:5000], query))
    return articles


def _google_news_url(query: str, start: date, end: date) -> str:
    # Google treats before as exclusive, hence end + one day is supplied by caller.
    expression = f"{query} after:{start.isoformat()} before:{end.isoformat()}"
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": expression, "hl": "ru", "gl": "RU", "ceid": "RU:ru"}
    )


def _normalize_title(title: str) -> str:
    title = title.lower().replace("ё", "е")
    title = re.sub(r"\s+[-—|]\s+[^-—|]{2,40}$", "", title)
    return re.sub(r"[^a-zа-я0-9]+", " ", title).strip()


def _score(article: Article, config: dict) -> float:
    haystack = f"{article.title} {article.summary}".lower().replace("ё", "е")
    score = 0.0
    for group in config["topic_keywords"]:
        matches = sum(1 for word in group["terms"] if word.lower().replace("ё", "е") in haystack)
        score += min(matches, 3) * float(group["weight"])
    source = article.source.lower()
    score += max((weight for name, weight in config["source_weights"].items() if name.lower() in source), default=0)
    if len(article.summary) > 180:
        score += 0.5
    for penalty in config.get("negative_keywords", []):
        matches = sum(1 for word in penalty["terms"] if word.lower().replace("ё", "е") in haystack)
        score -= min(matches, 3) * float(penalty["weight"])
    return score


def collect(config: dict, start: date, end_inclusive: date) -> tuple[list[Article], list[str]]:
    end_exclusive = date.fromordinal(end_inclusive.toordinal() + 1)
    start_dt = datetime.combine(start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(end_exclusive, time.min, tzinfo=timezone.utc)
    found: list[Article] = []
    warnings: list[str] = []

    for feed in config["direct_feeds"]:
        try:
            found.extend(parse_feed(_fetch(feed["url"]), feed["name"]))
        except Exception as exc:  # One unavailable outlet must not abort the digest.
            warnings.append(f"{feed['name']}: {exc}")

    for query in config["search_queries"]:
        try:
            url = _google_news_url(query, start, end_exclusive)
            found.extend(parse_feed(_fetch(url), "Google News", query))
        except Exception as exc:
            warnings.append(f"Google News ({query}): {exc}")

    dated = [article for article in found if start_dt <= article.published_at < end_dt]
    for article in dated:
        article.score = _score(article, config)
    dated.sort(key=lambda item: (item.score, item.published_at), reverse=True)

    unique: list[Article] = []
    normalized: list[str] = []
    for article in dated:
        current = _normalize_title(article.title)
        if any(SequenceMatcher(None, current, previous).ratio() >= 0.82 for previous in normalized):
            continue
        unique.append(article)
        normalized.append(current)
    return unique[: int(config.get("candidate_limit", 80))], warnings
