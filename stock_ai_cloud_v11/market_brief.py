"""API-key-free daily market issue feed for the dashboard.

Uses fixed Google News RSS searches that are separated into Korean/domestic and
overseas/global buckets. Only headline metadata is read; article pages are never
downloaded. Keyword counts are deterministic headline mentions, not an
assessment of importance, sentiment, or causality.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import html
from html.parser import HTMLParser
import re
from urllib.parse import urlencode, urlsplit, urlunsplit
import xml.etree.ElementTree as ET

import requests

SOURCE = "Google News RSS"
_MAX_BYTES = 1_048_576
_SEARCHES = [
    ("국내", "한국 경제", "한국 경제 금리 환율 물가 수출 소비 고용 when:1d", "ko", "KR", "KR:ko"),
    ("국내", "한국 증시", "코스피 코스닥 삼성전자 SK하이닉스 반도체 외국인 원화 when:1d", "ko", "KR", "KR:ko"),
    ("해외", "미국 시장", "미국 증시 나스닥 S&P 500 연준 금리 달러 AI 반도체 when:1d", "ko", "KR", "KR:ko"),
    ("해외", "글로벌 경제", "global economy stocks Federal Reserve inflation dollar oil China trade semiconductor when:1d", "en-US", "US", "US:en"),
]
_KEYWORDS = {
    "금리·중앙은행": ("금리", "기준금리", "연준", "fed", "fomc", "interest rate", "central bank", "bank of korea", "한국은행"),
    "환율·달러": ("환율", "달러", "원화", "원/달러", "usd", "won", "dollar"),
    "물가·인플레이션": ("물가", "인플레이션", "cpi", "pce", "inflation"),
    "AI·반도체": ("ai", "인공지능", "반도체", "semiconductor", "chip", "nvidia", "엔비디아", "하이닉스"),
    "증시·주가지수": ("코스피", "코스닥", "kospi", "kosdaq", "나스닥", "nasdaq", "s&p 500", "s&p500", "stocks", "wall street"),
    "관세·무역": ("관세", "무역", "수출", "수입", "tariff", "trade", "export", "import"),
    "중국": ("중국", "china", "chinese", "beijing"),
    "유가·에너지": ("유가", "원유", "석유", "oil", "opec", "energy"),
    "채권·국채": ("채권", "국채", "bond", "treasury", "yield"),
    "기업실적": ("실적", "매출", "영업이익", "earnings", "revenue", "profit"),
    "지정학": ("전쟁", "분쟁", "중동", "우크라이나", "geopolit", "war", "middle east", "ukraine"),
    "한국 수출·산업": ("수출", "반도체 수출", "자동차 수출", "export", "korea economy", "한국 경제"),
}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def _plain(value, limit=350):
    if not isinstance(value, str):
        return ""
    parser = _Text()
    parser.feed(value[:10000])
    text = " ".join(html.unescape(" ".join(parser.parts)).split())
    return text[:limit].rstrip() + ("…" if len(text) > limit else "")


def _safe_url(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return None
        if parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}:
            return None
        return urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path, parsed.query, ""))
    except (ValueError, TypeError):
        return None


def _date(value):
    try:
        result = parsedate_to_datetime(value)
        return result.astimezone(timezone.utc) if result and result.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def _rss_url(query, hl, gl, ceid):
    return "https://news.google.com/rss/search?" + urlencode({"q": query, "hl": hl, "gl": gl, "ceid": ceid})


def _read(url):
    with requests.Session() as session:
        with session.get(url, timeout=(3, 8), stream=True, allow_redirects=False) as response:
            if not 200 <= response.status_code < 300:
                raise requests.exceptions.HTTPError(response=response)
            chunks, size = [], 0
            for chunk in response.iter_content(chunk_size=16384):
                size += len(chunk)
                if size > _MAX_BYTES:
                    raise ValueError("RSS size limit")
                chunks.append(chunk)
            return b"".join(chunks)


def _parse(body, topic, now, region=""):
    if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise ValueError("RSS entity declarations are not accepted")
    root = ET.fromstring(body)
    result = []
    cutoff = now - timedelta(hours=30)
    for element in root.findall("./channel/item")[:40]:
        title = _plain(element.findtext("title"))
        publisher = _plain(element.findtext("source"), 100) or "출처 미제공"
        suffix = " - " + publisher
        if title.endswith(suffix):
            title = title[:-len(suffix)].strip()
        published = _date(element.findtext("pubDate"))
        url = _safe_url(element.findtext("link"))
        if not title or not published or published < cutoff or published > now + timedelta(minutes=5) or not url:
            continue
        result.append({
            "id": "", "title": title, "publisher": publisher, "url": url,
            "published_at": published.isoformat().replace("+00:00", "Z"),
            "topic": topic, "region": region, "source": SOURCE,
        })
    return result


def _normalize_title(title):
    return re.sub(r"[^\w]+", "", title.casefold())


def _keyword_counts(items):
    counts = []
    for label, aliases in _KEYWORDS.items():
        matched = []
        for item in items:
            text = item["title"].casefold()
            if any(alias.casefold() in text for alias in aliases):
                matched.append(item["id"])
        if matched:
            counts.append({"keyword": label, "count": len(matched), "item_ids": matched[:4]})
    counts.sort(key=lambda x: (-x["count"], x["keyword"]))
    return counts[:8]


def _dedupe(items):
    seen, result = set(), []
    for item in sorted(items, key=lambda x: x["published_at"], reverse=True):
        key = _normalize_title(item["title"])
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(dict(item))
    return result


def _balanced_select(items, count):
    domestic = _dedupe([x for x in items if x.get("region") == "국내"])
    overseas = _dedupe([x for x in items if x.get("region") == "해외"])
    target = max(1, count // 2)
    selected = domestic[:target] + overseas[:target]
    selected_keys = {_normalize_title(x["title"]) for x in selected}
    leftovers = [
        x for x in _dedupe(domestic[target:] + overseas[target:])
        if _normalize_title(x["title"]) not in selected_keys
    ]
    selected.extend(leftovers[: max(0, count - len(selected))])
    return sorted(selected[:count], key=lambda x: x["published_at"], reverse=True)


def _region_payload(items, region):
    subset = [item for item in items if item.get("region") == region]
    return {"items": subset, "keywords": _keyword_counts(subset), "region": region}


def fetch_market_brief(count=18):
    """Return recent market headlines split into domestic and overseas views."""
    now = datetime.now(timezone.utc)
    batches, errors = [], []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(_read, _rss_url(query, hl, gl, ceid)): (region, topic)
            for region, topic, query, hl, gl, ceid in _SEARCHES
        }
        for future in as_completed(futures):
            region, topic = futures[future]
            try:
                batches.extend(_parse(future.result(), topic, now, region=region))
            except Exception as exc:
                errors.append(f"{region}/{topic}: {type(exc).__name__}")

    items = _balanced_select(batches, max(2, int(count)))
    for index, item in enumerate(items, 1):
        item["id"] = f"M{index}"

    domestic = _region_payload(items, "국내")
    overseas = _region_payload(items, "해외")
    return {
        "items": items,
        "keywords": _keyword_counts(items),
        "domestic": domestic,
        "overseas": overseas,
        "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": SOURCE,
        "window": "최근 약 24시간(발행 시각 확인 기사)",
        "error": " / ".join(errors) if errors and not items else None,
        "coverage_note": (
            "국내·해외로 분리한 고정 경제·증시 검색어의 공개 RSS 제목을 모은 참고 자료입니다. "
            "기사 전문을 읽지 않으며, 키워드 빈도는 중요도·호재·악재 또는 가격 인과를 뜻하지 않습니다. "
            "국내와 해외의 상호 영향은 생성형 AI 분석을 실행했을 때 제공 자료 범위 안에서만 가설로 정리합니다."
        ),
    }
