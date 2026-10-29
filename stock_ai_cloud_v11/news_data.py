"""API-key-free news metadata for a personal research dashboard.

Sources: yfinance Ticker.get_news(), then the public Google News RSS search feed
when no relevant, dated Yahoo items remain. No article pages are downloaded.
Headlines and publisher-provided summaries are not evidence of price causality.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import html
from html.parser import HTMLParser
import re
import threading
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import xml.etree.ElementTree as ET

import requests
import yfinance as yf


_YAHOO = "Yahoo Finance / yfinance"
_GOOGLE = "Google News RSS"
_MAX_FEED_BYTES = 1_048_576
_WAIT_SECONDS = 12.0
_WORKERS = threading.BoundedSemaphore(4)
_SPECS = {
    "005930.KS": ("삼성전자", ("삼성전자", "Samsung Electronics", "005930")),
    "000660.KS": ("SK하이닉스", ("SK하이닉스", "SK 하이닉스", "SK hynix", "hynix", "000660")),
    "GOOGL": ("Alphabet Google stock", ("Alphabet", "Google", "알파벳", "구글", "GOOGL", "GOOG")),
    "GOOG": ("Alphabet Google stock", ("Alphabet", "Google", "알파벳", "구글", "GOOGL", "GOOG")),
    "NVDA": ("NVIDIA", ("NVIDIA", "NVDA", "엔비디아")),
    "QQQ": ("QQQ ETF", ("QQQ", "Invesco QQQ")),
    "^GSPC": ("S&P 500", ("S&P 500", "S&P500", "Standard & Poor's 500", "스탠더드앤드푸어스")),
    "VOO": ("VOO ETF", ("VOO", "Vanguard S&P 500")),
    "SPY": ("SPY ETF", ("SPY ETF", "SPDR S&P 500")),
}
_BENCHMARKS = {
    "QQQ": ("Nasdaq", "Nasdaq-100", "Nasdaq 100", "나스닥"),
    "^GSPC": ("S&P 500", "S&P500", "월가", "Wall Street"),
    "VOO": ("S&P 500", "S&P500", "Wall Street", "월가"),
    "SPY": ("S&P 500", "S&P500", "Wall Street", "월가"),
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _bounded(fn: Callable[[], Any]) -> Any:
    """Bound caller wait and outstanding jobs, including slow third-party calls."""
    if not _WORKERS.acquire(blocking=False):
        raise TimeoutError("News workers busy")
    done = threading.Event()
    box: dict[str, Any] = {}

    def work():
        try:
            box["value"] = fn()
        except Exception as exc:
            box["error"] = exc
        finally:
            _WORKERS.release()
            done.set()

    try:
        threading.Thread(target=work, daemon=True, name="news-metadata").start()
    except Exception:
        _WORKERS.release()
        raise
    if not done.wait(_WAIT_SECONDS):
        raise TimeoutError("News response timeout")
    if "error" in box:
        raise box["error"]
    return box.get("value")


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data):
        self.parts.append(data)


def _plain(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1\s*>", "", value[:20000], flags=re.I | re.S)
    parser = _Text()
    parser.feed(text)
    text = " ".join(html.unescape(" ".join(parser.parts)).split())
    return text[:limit].rstrip() + ("…" if len(text) > limit else "")


def _safe_url(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("url")
    if not isinstance(value, str):
        return None
    value = value.strip()
    if len(value) > 4000 or re.search(r"[\x00-\x20\\]", value):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.username or parsed.password or parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}:
            return None
        _ = parsed.port  # Reject malformed ports.
        return urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path, parsed.query, ""))
    except (ValueError, TypeError):
        return None


def _canonical_url(value: str) -> str:
    parsed = urlsplit(value)
    tracking = {"gclid", "fbclid", "guccounter", "guce_referrer", "guce_referrer_sig"}
    query = [(key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True)
             if not key.lower().startswith("utm_") and key.lower() not in tracking]
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"),
                       urlencode(sorted(query)), ""))


def _date(value: Any) -> datetime | None:
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            stamp = float(value)
            if stamp > 1e12:
                stamp /= 1000
            return datetime.fromtimestamp(stamp, timezone.utc)
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            result = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            result = parsedate_to_datetime(value)
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def _recent(value: Any, now: datetime, days: int) -> datetime | None:
    stamp = _date(value)
    if stamp is None or stamp < now - timedelta(days=days) or stamp > now + timedelta(minutes=5):
        return None
    return stamp


def _has_keyword(text: str, keyword: str) -> bool:
    if not keyword:
        return False
    # ASCII ticker boundaries avoid matches such as GOOG inside GOOGLE or SPY in SPYWARE.
    pattern = re.escape(keyword)
    if keyword[0].isascii() and keyword[0].isalnum():
        pattern = r"(?<![A-Za-z0-9])" + pattern
    if keyword[-1].isascii() and keyword[-1].isalnum():
        pattern += r"(?![A-Za-z0-9])"
    return re.search(pattern, text, flags=re.I) is not None


def _ticker_tags(item: dict, content: dict) -> set[str]:
    tags: set[str] = set()
    for container in (item, content, content.get("finance", {})):
        if not isinstance(container, dict):
            continue
        for key in ("relatedTickers", "stockTickers"):
            values = container.get(key, [])
            if not isinstance(values, list):
                continue
            for value in values:
                symbol = value.get("symbol") if isinstance(value, dict) else value
                if isinstance(symbol, str):
                    tags.add(symbol.strip().upper())
    return tags


def _relevance(symbol: str, name: str | None, text: str, tags: set[str] | None = None) -> str | None:
    aliases = list(_SPECS.get(symbol, (symbol, ()))[1])
    if symbol not in _SPECS:
        if len(symbol) >= 3:
            aliases.append(symbol)
        if name and len(name.strip()) >= 2:
            aliases.append(name.strip()[:150])
    if any(_has_keyword(text, alias) for alias in aliases):
        return "지수·시장 관련" if symbol.startswith("^") else "종목명·키워드 일치"
    if any(_has_keyword(text, alias) for alias in _BENCHMARKS.get(symbol, ())):
        return "지수·시장 관련"
    related_symbols = {symbol}
    if symbol in {"GOOG", "GOOGL"}:
        related_symbols.update({"GOOG", "GOOGL"})
    if tags and related_symbols.intersection(tags):
        return "제공자 종목 연결 · 직접 언급 미확인"
    return None


def _normalize_yahoo(raw: Any, symbol: str, name: str | None, now: datetime, days: int) -> list[dict]:
    if not isinstance(raw, list):
        raise ValueError("Unexpected news response")
    items = []
    for item in raw[:100]:
        if not isinstance(item, dict) or item.get("ad"):
            continue
        content = item.get("content") if isinstance(item.get("content"), dict) else item
        title = _plain(content.get("title") or item.get("title"), 350)
        summary = _plain(content.get("summary") or content.get("description") or item.get("summary"), 480) or None
        date_value = content.get("pubDate") or content.get("providerPublishTime") or item.get("providerPublishTime")
        published = _recent(date_value, now, days)
        urls = [content.get("canonicalUrl"), content.get("clickThroughUrl"), content.get("link"),
                content.get("url"), item.get("link")]
        url = next((safe for candidate in urls if (safe := _safe_url(candidate))), None)
        relevance = _relevance(symbol, name, title + " " + (summary or ""), _ticker_tags(item, content))
        if not (title and published and url and relevance):
            continue
        provider = content.get("provider")
        publisher = _plain(provider.get("displayName"), 100) if isinstance(provider, dict) else ""
        publisher = publisher or _plain(content.get("publisher") or item.get("publisher"), 100) or "출처 미제공"
        items.append({"id": "", "title": title, "publisher": publisher, "url": url,
                      "published_at": _iso(published), "summary": summary, "source": _YAHOO,
                      "relevance": relevance})
    return items


def _rss_url(symbol: str, name: str | None, days: int) -> str:
    korean = symbol.endswith((".KS", ".KQ"))
    query = _SPECS.get(symbol, (name or symbol, ()))[0]
    query = " ".join(str(query).split())[:150] + f" when:{days}d"
    params = {"q": query, "hl": "ko" if korean else "en-US", "gl": "KR" if korean else "US",
              "ceid": "KR:ko" if korean else "US:en"}
    return "https://news.google.com/rss/search?" + urlencode(params)


def _read_rss(url: str) -> bytes:
    # A fixed Google feed URL is read once. Article links are never fetched.
    with requests.Session() as session:
        with session.get(url, timeout=(3, 8), stream=True, allow_redirects=False) as response:
            if not 200 <= response.status_code < 300:
                raise requests.exceptions.HTTPError(response=response)
            length = response.headers.get("Content-Length", "")
            if str(length).isdigit() and int(length) > _MAX_FEED_BYTES:
                raise ValueError("RSS size limit")
            chunks, size = [], 0
            for chunk in response.iter_content(chunk_size=16384):
                size += len(chunk)
                if size > _MAX_FEED_BYTES:
                    raise ValueError("RSS size limit")
                chunks.append(chunk)
            return b"".join(chunks)


def _parse_rss(body: bytes, symbol: str, name: str | None, now: datetime, days: int) -> list[dict]:
    if not isinstance(body, bytes) or len(body) > _MAX_FEED_BYTES:
        raise ValueError("Invalid RSS body")
    if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise ValueError("RSS entity declarations are not accepted")
    root = ET.fromstring(body)
    items = []
    for element in root.findall("./channel/item")[:100]:
        title = _plain(element.findtext("title"), 350)
        publisher = _plain(element.findtext("source"), 100) or "출처 미제공"
        suffix = " - " + publisher
        if title.endswith(suffix):
            title = title[:-len(suffix)].strip()
        published = _recent(element.findtext("pubDate"), now, days)
        url = _safe_url(element.findtext("link"))
        relevance = _relevance(symbol, name, title)
        if not (title and published and url and relevance):
            continue
        items.append({"id": "", "title": title, "publisher": publisher, "url": url,
                      "published_at": _iso(published), "summary": None, "source": _GOOGLE,
                      "relevance": relevance})
    return items


def _deduplicate(items: list[dict], count: int) -> list[dict]:
    seen_urls, seen_titles, result = set(), set(), []
    for item in sorted(items, key=lambda value: _date(value["published_at"]) or datetime.min.replace(tzinfo=timezone.utc), reverse=True):
        url = _canonical_url(item["url"])
        title = re.sub(r"[^\w]+", "", item["title"].casefold())
        if url in seen_urls or title in seen_titles:
            continue
        seen_urls.add(url)
        seen_titles.add(title)
        result.append(dict(item, id=f"N{len(result) + 1}"))
        if len(result) >= count:
            break
    return result


def _error(exc: Exception) -> str:
    name = type(exc).__name__
    if "ratelimit" in name.lower() or getattr(getattr(exc, "response", None), "status_code", None) == 429:
        return "요청 제한(429)"
    if isinstance(exc, (TimeoutError, requests.exceptions.Timeout)):
        return "응답 시간 초과"
    return f"조회 실패({name})"


def fetch_news(symbol: str, name: str | None = None, count: int = 8, days: int = 7) -> dict:
    """Return recent relevant headline metadata; failures return an empty list.

    Dates without a timezone are excluded. A five-minute future tolerance allows
    minor publisher clock differences. IDs N1..Nn belong to this result snapshot.
    """
    now = _utc_now()
    result = {"symbol": str(symbol), "items": [], "fetched_at": _iso(now),
              "source": _YAHOO, "error": None, "coverage_note": ""}
    symbol = str(symbol).strip().upper()
    if not re.fullmatch(r"[A-Z0-9^][A-Z0-9.^=\-]{0,23}", symbol):
        result["error"] = "뉴스를 조회할 종목 티커를 확인해 주세요."
        return result
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 30:
        result["error"] = "뉴스 개수는 1~30개로 설정하세요."
        return result
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 30:
        result["error"] = "뉴스 조회 기간은 1~30일로 설정하세요."
        return result
    name = name.strip()[:150] if isinstance(name, str) else None
    result["symbol"] = symbol
    result["coverage_note"] = (
        f"최근 {days}일 이내 발행 시각이 확인된 기사 중 최대 {count}개입니다. "
        "제목과 제공자가 제공한 짧은 요약만 사용하며 기사 전문을 읽지 않습니다. "
        "발행 시각이 없거나 범위를 벗어난 기사는 제외하므로 뉴스 전체를 포괄하지 않습니다. "
        "키워드·제공자 연결은 관련성 단서이며 가격 상승·하락의 원인을 입증하지 않습니다."
    )
    failures = []
    try:
        raw = _bounded(lambda: yf.Ticker(symbol).get_news(count=min(30, max(15, count * 3)), tab="news"))
        items = _normalize_yahoo(raw, symbol, name, now, days)
    except Exception as exc:
        failures.append("Yahoo Finance: " + _error(exc))
        items = []
    if not items:
        result["source"] = _GOOGLE
        result["coverage_note"] += " Yahoo에서 적합한 기사를 확인하지 못해 공개 Google News 검색 피드로 보완했습니다. 이 피드는 제목만 사용합니다."
        try:
            body = _bounded(lambda: _read_rss(_rss_url(symbol, name, days)))
            items = _parse_rss(body, symbol, name, now, days)
        except Exception as exc:
            failures.append("Google News RSS: " + _error(exc))
    result["items"] = _deduplicate(items, count)
    result["fetched_at"] = _iso(_utc_now())
    if not result["items"]:
        result["error"] = "관련 뉴스가 확인되지 않았습니다. " + (" / ".join(failures) if failures else "기간·검색 범위 또는 제공자 상태를 확인해 주세요.")
    return result
