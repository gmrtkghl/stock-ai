"""API-key-free market issue feed for the dashboard.

Collects a broad set of Google News RSS headline metadata, separates domestic
and overseas coverage, removes duplicate headlines, and builds keyword/topic
counts from up to roughly 100 recent items. Article pages are never downloaded.
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
_MAX_BYTES = 1_572_864
_TARGET_ITEMS = 100
_MAX_PER_FEED = 55
_SEARCHES = [
    # Domestic: split searches so one hot topic does not dominate the sample.
    ("국내", "한국 거시경제", "한국 경제 금리 환율 물가 소비 고용 성장 when:1d", "ko", "KR", "KR:ko"),
    ("국내", "한국 증시", "코스피 코스닥 외국인 기관 증시 주가 when:1d", "ko", "KR", "KR:ko"),
    ("국내", "반도체·AI", "삼성전자 SK하이닉스 반도체 HBM AI 데이터센터 when:1d", "ko", "KR", "KR:ko"),
    ("국내", "수출·산업", "한국 수출 자동차 조선 배터리 화학 산업 when:1d", "ko", "KR", "KR:ko"),
    ("국내", "정책·금융", "한국은행 금융위원회 정부 경제정책 부동산 채권 when:1d", "ko", "KR", "KR:ko"),
    ("국내", "기업실적", "한국 기업 실적 매출 영업이익 전망 증권 when:1d", "ko", "KR", "KR:ko"),
    # Overseas: English and Korean searches are mixed to broaden coverage.
    ("해외", "미국 증시", "US stocks Nasdaq S&P 500 Wall Street earnings when:1d", "en-US", "US", "US:en"),
    ("해외", "금리·물가", "Federal Reserve rates inflation CPI PCE Treasury yields when:1d", "en-US", "US", "US:en"),
    ("해외", "AI·반도체", "AI semiconductor Nvidia chip data center memory HBM when:1d", "en-US", "US", "US:en"),
    ("해외", "중국·아시아", "China economy stimulus trade exports stocks Asia when:1d", "en-US", "US", "US:en"),
    ("해외", "에너지·원자재", "oil OPEC energy commodities gold copper market when:1d", "en-US", "US", "US:en"),
    ("해외", "무역·지정학", "tariff trade war sanctions geopolitics Middle East Ukraine markets when:1d", "en-US", "US", "US:en"),
]

_KEYWORDS = {
    "금리·중앙은행": ("금리", "기준금리", "금리인하", "금리 인하", "금리인상", "금리 인상", "연준", "fed", "fomc", "interest rate", "rate cut", "rate hike", "central bank", "bank of korea", "한국은행"),
    "환율·달러": ("환율", "달러", "원화", "원/달러", "usd", "won", "dollar", "dxy"),
    "물가·인플레이션": ("물가", "인플레이션", "cpi", "pce", "inflation", "consumer prices"),
    "AI·반도체": ("ai", "인공지능", "반도체", "semiconductor", "chip", "nvidia", "엔비디아", "하이닉스", "hbm", "memory", "메모리", "data center", "데이터센터"),
    "증시·주가지수": ("코스피", "코스닥", "kospi", "kosdaq", "나스닥", "nasdaq", "s&p 500", "s&p500", "stocks", "wall street", "증시", "주가"),
    "관세·무역": ("관세", "무역", "수출", "수입", "tariff", "trade", "export", "import", "sanction", "제재"),
    "중국": ("중국", "china", "chinese", "beijing", "중국 경기", "중국 증시"),
    "유가·에너지": ("유가", "원유", "석유", "oil", "opec", "energy", "lng", "천연가스", "natural gas"),
    "채권·국채": ("채권", "국채", "bond", "treasury", "yield", "수익률"),
    "기업실적": ("실적", "매출", "영업이익", "earnings", "revenue", "profit", "guidance", "전망"),
    "지정학": ("전쟁", "분쟁", "중동", "우크라이나", "geopolit", "war", "middle east", "ukraine", "iran", "israel"),
    "한국 수출·산업": ("한국 수출", "반도체 수출", "자동차 수출", "조선", "배터리", "export", "korea economy", "한국 경제"),
    "자동차·배터리": ("자동차", "전기차", "배터리", "현대차", "기아", "ev", "battery", "automaker", "tesla"),
    "원자재·금": ("금값", "금 가격", "gold", "copper", "구리", "commodity", "commodities", "원자재"),
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
    headers = {"User-Agent": "Mozilla/5.0 StockAI/1.0"}
    with requests.Session() as session:
        with session.get(url, timeout=(3, 10), stream=True, allow_redirects=False, headers=headers) as response:
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
    cutoff = now - timedelta(hours=32)
    for element in root.findall("./channel/item")[:_MAX_PER_FEED]:
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


def _matches(item, aliases):
    text = item["title"].casefold()
    return any(alias.casefold() in text for alias in aliases)


def _keyword_counts(items, limit=10):
    counts = []
    total = max(1, len(items))
    for label, aliases in _KEYWORDS.items():
        matched = [item["id"] for item in items if _matches(item, aliases)]
        if matched:
            counts.append({
                "keyword": label,
                "count": len(matched),
                "coverage_pct": round(len(matched) / total * 100, 1),
                "item_ids": matched[:8],
            })
    counts.sort(key=lambda x: (-x["count"], x["keyword"]))
    return counts[:limit]


def _topic_rows(items, limit=8):
    by_id = {x.get("id"): x for x in items}
    topics = []
    for row in _keyword_counts(items, limit=14):
        if row["count"] < 2:
            continue
        representative = [by_id[x] for x in row["item_ids"] if x in by_id][:4]
        topics.append({
            "topic": row["keyword"],
            "count": row["count"],
            "coverage_pct": row["coverage_pct"],
            "item_ids": row["item_ids"],
            "representative_headlines": [x["title"] for x in representative],
        })
    return topics[:limit]


def _search_topic_counts(items, limit=8):
    counts = {}
    for item in items:
        topic = item.get("topic") or "기타"
        counts[topic] = counts.get(topic, 0) + 1
    rows = [{"topic": key, "count": value} for key, value in counts.items()]
    rows.sort(key=lambda x: (-x["count"], x["topic"]))
    return rows[:limit]


def _region_payload(items, region):
    subset = [item for item in items if item.get("region") == region]
    return {
        "items": subset,
        "keywords": _keyword_counts(subset),
        "topics": _topic_rows(subset),
        "search_topics": _search_topic_counts(subset),
        "region": region,
        "sample_size": len(subset),
    }


def fetch_market_brief(count=100):
    """Return a broad recent headline sample split into domestic/overseas views.

    The app may pass an older smaller count. The cloud edition intentionally
    keeps an analysis floor of roughly 100 headlines whenever enough RSS items
    are available so keyword/topic estimates are not driven by a tiny sample.
    """
    now = datetime.now(timezone.utc)
    requested = max(_TARGET_ITEMS, int(count or 0))
    batches, errors = [], []
    with ThreadPoolExecutor(max_workers=8) as pool:
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

    items = _balanced_select(batches, requested)
    for index, item in enumerate(items, 1):
        item["id"] = f"M{index}"

    domestic = _region_payload(items, "국내")
    overseas = _region_payload(items, "해외")
    sample_size = len(items)
    return {
        "items": items,
        "keywords": _keyword_counts(items),
        "topics": _topic_rows(items),
        "domestic": domestic,
        "overseas": overseas,
        "sample_size": sample_size,
        "target_sample_size": requested,
        "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": SOURCE,
        "window": "최근 약 24시간(발행 시각 확인 기사)",
        "error": " / ".join(errors) if errors and not items else None,
        "coverage_note": (
            f"국내·해외 12개 경제·증시 검색 묶음에서 중복 제목을 제거한 최근 기사 {sample_size}건을 분석했습니다. "
            f"목표 표본은 약 {requested}건이며 RSS 상황에 따라 실제 건수는 달라질 수 있습니다. "
            "기사 전문은 읽지 않고 제목·발행 메타데이터만 사용합니다. 키워드 빈도와 토픽 분류는 중요도, 호재·악재, 가격 인과를 확정하지 않습니다."
        ),
    }
