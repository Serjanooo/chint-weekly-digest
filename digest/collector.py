from __future__ import annotations

import hashlib
import gzip
import html
import json
import re
import ssl
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from difflib import SequenceMatcher

from googlenewsdecoder import new_decoderv1

from .models import Article

USER_AGENT = "Mozilla/5.0 (compatible; CHINTDigest/1.0; +https://github.com/)"
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
URL_DATE_RE = re.compile(r"/(20\d{2})/(\d{2})/(\d{2})/")


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _fetch(url: str, timeout: int = 20) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        payload = response.read()
        if response.headers.get("Content-Encoding", "").lower() == "gzip" or payload.startswith(b"\x1f\x8b"):
            return gzip.decompress(payload)
        return payload


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


def _date_from_url(url: str) -> datetime | None:
    match = URL_DATE_RE.search(url)
    if not match:
        return None
    try:
        return datetime(int(match[1]), int(match[2]), int(match[3]), 12, tzinfo=timezone.utc)
    except ValueError:
        return None


def _page_metadata(payload: bytes) -> tuple[str, str, datetime | None]:
    page = payload.decode("utf-8", errors="ignore")
    title_match = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', page, re.I)
    if not title_match:
        title_match = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
    description_match = re.search(
        r'<meta[^>]+(?:property|name)=["\'](?:og:description|description)["\'][^>]+content=["\']([^"\']+)',
        page,
        re.I,
    )
    date_match = re.search(r'"datePublished"\s*:\s*"([^"]+)"', page)
    title = _clean(title_match.group(1)) if title_match else ""
    description = _clean(description_match.group(1)) if description_match else ""
    published = _parse_date(date_match.group(1)) if date_match else None
    return title, description, published


def _article_from_page(url: str, source: str, fallback_title: str = "") -> Article | None:
    try:
        title, summary, published = _page_metadata(_fetch(url))
    except Exception:
        return None
    published = published or _date_from_url(url)
    title = title or fallback_title
    if not title or not published:
        return None
    article_id = hashlib.sha1(f"{title}|{url}".encode()).hexdigest()[:12]
    return Article(
        article_id,
        title,
        url,
        source,
        published,
        summary,
        source_home=f"https://{_hostname(url)}",
        is_chint_russia=True,
    )


def _collect_chint_sources(start: date, end: date) -> tuple[list[Article], list[str]]:
    articles: list[Article] = []
    warnings: list[str] = []

    try:
        sitemap = ET.fromstring(_fetch("https://www.elec.ru/sitemap_news_1.xml"))
        urls = {
            (node.text or "").strip()
            for node in sitemap.iter()
            if node.tag.rsplit("}", 1)[-1] == "loc" and node.text and "chint" in node.text.lower()
        }
        urls = {url for url in urls if (published := _date_from_url(url)) and start <= published.date() <= end}
        with ThreadPoolExecutor(max_workers=3) as executor:
            articles.extend(item for item in executor.map(lambda url: _article_from_page(url, "Elec.ru"), urls) if item)
    except Exception as exc:
        warnings.append(f"Прямой поиск CHINT на Elec.ru: {exc}")

    try:
        page = _fetch("https://www.ruscable.ru/search/?q=CHINT").decode("utf-8", errors="ignore")
        links = re.findall(r'<a[^>]+href=["\'](https://www\.ruscable\.ru/news/[^"\']+)["\'][^>]*>(.*?)</a>', page, re.I | re.S)
        for url, title_html in links:
            published = _date_from_url(url)
            if published and start <= published.date() <= end:
                title = _clean(title_html)
                article_id = hashlib.sha1(f"{title}|{url}".encode()).hexdigest()[:12]
                articles.append(
                    Article(
                        article_id,
                        title,
                        url,
                        "RusCable.Ru",
                        published,
                        title,
                        source_home="https://www.ruscable.ru",
                        is_chint_russia=True,
                    )
                )
    except Exception as exc:
        warnings.append(f"Прямой поиск CHINT на RusCable.Ru: {exc}")

    try:
        profile = _fetch("https://companies.rbc.ru/id/1107746822700-chint-v-rossii/").decode("utf-8", errors="ignore")
        paths = set(re.findall(r'href=["\'](/news/[^"\']*chint[^"\']*)["\']', profile, re.I))
        urls = {urllib.parse.urljoin("https://companies.rbc.ru", path) for path in paths}
        with ThreadPoolExecutor(max_workers=3) as executor:
            rbc_articles = list(executor.map(lambda url: _article_from_page(url, "РБК Компании"), urls))
        articles.extend(
            item for item in rbc_articles if item and start <= item.published_at.date() <= end
        )
    except Exception as exc:
        warnings.append(f"Прямой поиск CHINT в РБК Компании: {exc}")

    return articles, warnings


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
        source_home = ""
        for child in item.iter():
            if child.tag.rsplit("}", 1)[-1].lower() == "source":
                source_home = child.attrib.get("url", "")
                break
        if title and link and published:
            article_id = hashlib.sha1(f"{title}|{link}".encode()).hexdigest()[:12]
            articles.append(
                Article(
                    article_id,
                    title,
                    link,
                    source,
                    published,
                    summary[:5000],
                    query,
                    source_home=source_home,
                )
            )
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


def _hostname(url: str) -> str:
    return (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")


def _domain_allowed(hostname: str, allowed_domains: list[str]) -> bool:
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in allowed_domains)


def _strip_tracking(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    blocked = {"gclid", "yclid", "fbclid", "oc", "ref", "from"}
    query = [
        (key, value)
        for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in blocked
    ]
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), ""))


def _resolve_google_article(article: Article, allowed_domains: list[str]) -> Article | None:
    if _hostname(article.url) != "news.google.com":
        return article
    try:
        decoded = new_decoderv1(article.url)
    except Exception:
        return None
    if not decoded.get("status"):
        return None
    direct_url = _strip_tracking(decoded.get("decoded_url", ""))
    direct_host = _hostname(direct_url)
    if not direct_host or direct_host == "news.google.com" or not _domain_allowed(direct_host, allowed_domains):
        return None
    expected_host = _hostname(article.source_home)
    if expected_host and not (
        direct_host == expected_host
        or direct_host.endswith(f".{expected_host}")
        or expected_host.endswith(f".{direct_host}")
    ):
        return None
    article.url = direct_url
    return article


def _is_chint_russia(article: Article, source_domains: list[str] | None = None) -> bool:
    source_domains = source_domains or ["elec.ru", "ruscable.ru", "companies.rbc.ru"]
    text = f"{article.title} {article.summary}".lower().replace("ё", "е")
    source_host = _hostname(article.source_home) or _hostname(article.url)
    return "chint" in text and _domain_allowed(source_host, source_domains)


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
    if article.is_chint_russia:
        score += float(config.get("chint_russia_boost", 20))
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

    chint_articles, chint_warnings = _collect_chint_sources(start, end_inclusive)
    found.extend(chint_articles)
    warnings.extend(chint_warnings)

    for query in config["search_queries"]:
        try:
            url = _google_news_url(query, start, end_exclusive)
            found.extend(parse_feed(_fetch(url), "Google News", query))
        except Exception as exc:
            warnings.append(f"Google News ({query}): {exc}")

    dated = [article for article in found if start_dt <= article.published_at < end_dt]
    for article in dated:
        article.is_chint_russia = _is_chint_russia(article, config["chint_source_domains"])
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
    limit = int(config.get("candidate_limit", 80))
    resolution_pool = unique[: limit * 2]
    with ThreadPoolExecutor(max_workers=int(config.get("url_resolver_workers", 6))) as executor:
        resolved = list(
            executor.map(
                lambda article: _resolve_google_article(article, config["preferred_domains"]),
                resolution_pool,
            )
        )
    failed_count = sum(1 for article in resolved if article is None)
    if failed_count:
        warnings.append(f"Исключено Google News-карточек без прямой ссылки на СМИ: {failed_count}")
    direct_articles = [article for article in resolved if article is not None]
    for article in direct_articles:
        article.is_chint_russia = _is_chint_russia(article, config["chint_source_domains"])
        article.score = _score(article, config)
    direct_articles.sort(key=lambda item: (item.score, item.published_at), reverse=True)
    return direct_articles[:limit], warnings
