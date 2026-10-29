"""API 키 없이 Yahoo Finance 데이터를 읽는 개인 학습용 모듈.

무료 공개 데이터는 지연되거나 일시적으로 비어 있을 수 있다. 실제 데이터가
없으면 임의의 가격, 섹터 비중 또는 날짜를 생성하지 않는다.
"""
from __future__ import annotations

import math
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import numpy as np
import pandas as pd
import yfinance as yf


WATCHLIST = [
    {"symbol": "005930.KS", "name": "삼성전자", "kind": "stock", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "000660.KS", "name": "SK하이닉스", "kind": "stock", "market": "KOSPI", "currency": "KRW"},
    {"symbol": "GOOGL", "name": "알파벳 · 구글", "kind": "stock", "market": "미국", "currency": "USD"},
    {"symbol": "NVDA", "name": "엔비디아", "kind": "stock", "market": "미국", "currency": "USD"},
    {"symbol": "QQQ", "name": "Invesco QQQ", "kind": "etf", "market": "미국", "currency": "USD"},
    {"symbol": "^GSPC", "name": "S&P 500 지수", "kind": "index", "market": "미국", "currency": "포인트"},
]
OPTIONAL_INSTRUMENTS = [
    {"symbol": "VOO", "name": "Vanguard S&P 500 ETF", "kind": "etf", "market": "미국", "currency": "USD"},
    {"symbol": "GOOG", "name": "알파벳 Class C", "kind": "stock", "market": "미국", "currency": "USD"},
    {"symbol": "SPY", "name": "SPDR S&P 500 ETF", "kind": "etf", "market": "미국", "currency": "USD"},
]
_KNOWN = {row["symbol"]: row for row in WATCHLIST + OPTIONAL_INSTRUMENTS}
SOURCE = "Yahoo Finance · yfinance"
_WAIT_SECONDS = 12.0
_HISTORY_TIMEOUT = 10


@dataclass
class _Job:
    event: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: Exception | None = None
    finished: float = 0.0


# A caller timeout cannot cancel yfinance's internal HTTP request. Daemon workers
# are capped, shared calls are deduplicated, and transient errors expire quickly.
# The cap prevents unbounded threads if a provider is temporarily unresponsive.
_jobs: dict[tuple, _Job] = {}
_jobs_lock = threading.Lock()
_worker_slots = threading.BoundedSemaphore(12)


def _bounded(key: tuple, fn: Callable, ttl: float = 45.0) -> Any:
    now = time.monotonic()
    with _jobs_lock:
        job = _jobs.get(key)
        if job and job.event.is_set():
            max_age = min(ttl, 30.0) if job.error else ttl
            if now - job.finished >= max_age:
                _jobs.pop(key, None)
                job = None
        if job is None:
            if not _worker_slots.acquire(blocking=False):
                raise TimeoutError("진행 중인 조회가 많습니다. 잠시 후 다시 시도해 주세요.")
            job = _Job()
            _jobs[key] = job

            def run() -> None:
                try:
                    job.result = fn()
                except Exception as exc:
                    job.error = exc
                finally:
                    job.finished = time.monotonic()
                    job.event.set()
                    _worker_slots.release()

            threading.Thread(target=run, daemon=True, name="market-data").start()
        # Remove only old completed entries; never remove active jobs.
        for stale_key, stale in list(_jobs.items()):
            if stale_key != key and stale.event.is_set() and now - stale.finished > 86400:
                _jobs.pop(stale_key, None)
    if not job.event.wait(_WAIT_SECONDS):
        raise TimeoutError("데이터 제공자 응답이 지연되고 있습니다. 잠시 후 다시 조회해 주세요.")
    if job.error is not None:
        raise job.error
    return job.result


def clear_caches() -> None:
    """Clear finished requests; retain in-flight work to avoid duplicate calls."""
    with _jobs_lock:
        for key, job in list(_jobs.items()):
            if job.event.is_set():
                _jobs.pop(key, None)


def normalize_symbol(symbol: str) -> str:
    """Accept Yahoo symbols, including Korean suffixes, index and FX symbols."""
    value = str(symbol).strip().upper()
    if not re.fullmatch(r"[A-Z0-9^][A-Z0-9.\-^=]{0,24}", value):
        raise ValueError("티커 형식을 확인해 주세요. 예: 005930.KS, GOOGL, QQQ, ^GSPC")
    return value


def search_instruments(query: str, max_results: int = 8) -> dict:
    """Search Yahoo Finance for stocks, ETFs and indices by name or ticker.

    The return value is deliberately small and JSON-friendly so the Streamlit
    sidebar can keep search results in session state. Search failures never
    fabricate instruments; they return an error message instead.
    """
    text = str(query or "").strip()
    if len(text) < 1:
        return {"query": text, "items": [], "error": "종목명이나 티커를 입력해 주세요."}
    max_results = max(1, min(int(max_results), 12))

    def read():
        search = yf.Search(
            text,
            max_results=max_results,
            news_count=0,
            lists_count=0,
            include_cb=False,
            include_nav_links=False,
            include_research=False,
            enable_fuzzy_query=True,
            recommended=0,
            timeout=8,
            raise_errors=False,
        )
        return list(search.quotes or [])

    try:
        rows = _bounded(("search", text.casefold(), max_results), read, ttl=300)
    except Exception as exc:
        return {"query": text, "items": [], "error": _error(exc)}

    allowed = {"EQUITY", "ETF", "INDEX"}
    items = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_symbol = row.get("symbol")
        if not raw_symbol:
            continue
        try:
            symbol = normalize_symbol(raw_symbol)
        except ValueError:
            continue
        quote_type = str(row.get("quoteType") or row.get("typeDisp") or "").upper()
        if quote_type and quote_type not in allowed:
            continue
        if symbol in seen:
            continue
        seen.add(symbol)
        name = row.get("longname") or row.get("shortname") or row.get("name") or symbol
        exchange = row.get("exchDisp") or row.get("exchange") or row.get("exchangeDisplay") or ""
        type_label = row.get("typeDisp") or row.get("quoteType") or ""
        items.append({
            "symbol": symbol,
            "name": str(name),
            "exchange": str(exchange),
            "quote_type": str(row.get("quoteType") or ""),
            "type_label": str(type_label),
        })
        if len(items) >= max_results:
            break

    if not items:
        return {"query": text, "items": [], "error": "검색 결과가 없습니다. 종목명 또는 티커를 다시 확인해 주세요."}
    return {"query": text, "items": items, "error": None}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _positive(value: Any) -> float | None:
    number = _number(value)
    return number if number is not None and number > 0 else None


def _error(exc: Exception) -> str:
    name = type(exc).__name__
    if "RateLimit" in name or "429" in str(exc):
        return "제공자 요청 한도에 도달했습니다. 새로고침을 멈추고 잠시 뒤 시도해 주세요."
    if isinstance(exc, TimeoutError) or "Timeout" in name:
        return "데이터 제공자 응답이 지연되고 있습니다. 잠시 뒤 다시 시도해 주세요."
    return f"데이터를 불러오지 못했습니다 ({name}). 티커·인터넷 연결·제공자 상태를 확인해 주세요."


def _is_rate_limit(exc: Exception) -> bool:
    return "RateLimit" in type(exc).__name__ or "429" in str(exc)


def _is_timeout(exc: Exception) -> bool:
    return isinstance(exc, TimeoutError) or "Timeout" in type(exc).__name__


def _delay_note(symbol: str) -> str:
    if symbol.endswith((".KS", ".KQ")):
        return "Yahoo 안내 기준 한국 주식은 20분 지연입니다. 조회 시각과 시세 기준 시각은 다릅니다."
    return "시장·종목별 지연 및 누락이 있을 수 있습니다. 기준 시각을 확인해 주세요."


def _info(symbol: str) -> dict:
    result = _bounded(("info", symbol), lambda: yf.Ticker(symbol).get_info(), ttl=45)
    return dict(result) if isinstance(result, dict) else {}


def _kind(symbol: str, info: dict) -> str:
    quote_type = str(info.get("quoteType", "")).upper()
    if quote_type in {"ETF", "MUTUALFUND"}:
        return "etf"
    if quote_type == "INDEX" or symbol.startswith("^"):
        return "index"
    return _KNOWN.get(symbol, {}).get("kind", "stock")


def _currency(symbol: str, info: dict) -> str | None:
    if _kind(symbol, info) == "index":
        return "포인트"
    return info.get("currency") or _KNOWN.get(symbol, {}).get("currency")


def _epoch_iso(value: Any) -> str | None:
    value = _positive(value)
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(value, timezone.utc).isoformat()
    except (ValueError, OSError, OverflowError):
        return None


def _history(symbol: str, period: str, interval: str) -> tuple[pd.DataFrame, dict]:
    def read():
        ticker = yf.Ticker(symbol)
        frame = ticker.history(
            period=period,
            interval=interval,
            auto_adjust=False,
            back_adjust=False,
            actions=False,
            prepost=False,
            timeout=_HISTORY_TIMEOUT,
        )
        # history already fetched this metadata; the property normally reuses it.
        meta = {}
        if isinstance(frame, pd.DataFrame) and not frame.empty:
            try:
                raw_meta = ticker.history_metadata
                # Recent yfinance versions return a lazy Mapping, not a dict.
                # Read only needed fields; converting all keys can fetch extra data.
                meta = {key: raw_meta.get(key) for key in
                        ("currency", "instrumentType", "exchangeTimezoneName")}
            except Exception:
                pass
        return frame, meta

    frame, meta = _bounded(("history", symbol, period, interval), read, ttl=45 if interval == "1m" else 300)
    if not isinstance(frame, pd.DataFrame) or frame.empty or "Close" not in frame:
        return pd.DataFrame(), dict(meta) if isinstance(meta, dict) else {}
    frame = frame.copy()
    frame = frame.loc[~frame.index.duplicated(keep="last")].sort_index()
    frame["Close"] = pd.to_numeric(frame["Close"], errors="coerce")
    frame = frame.loc[np.isfinite(frame["Close"]) & (frame["Close"] > 0)]
    frame.attrs["symbol"] = symbol
    frame.attrs["source"] = SOURCE
    frame.attrs["interval"] = interval
    return frame, dict(meta) if isinstance(meta, dict) else {}


def _quote_shell(symbol: str) -> dict:
    return {
        "symbol": str(symbol), "price": None, "currency": None, "asof": None,
        "asof_label": "기준 시각 없음", "source": SOURCE, "previous_close": None,
        "change_pct": None, "error": None, "delay_note": "", "fetched_at": _now(),
    }


def _default_currency(symbol: str) -> str | None:
    known = _KNOWN.get(symbol, {})
    if known.get("kind") == "index" or symbol.startswith("^"):
        return "포인트"
    if known.get("currency"):
        return known["currency"]
    if symbol.endswith((".KS", ".KQ")):
        return "KRW"
    # Yahoo symbols without an exchange suffix are predominantly US-listed
    # equities/ETFs in this app's supported search results. Other exchanges
    # normally carry suffixes (.L, .T, .TO, ...).
    if not symbol.startswith("^") and "." not in symbol:
        return "USD"
    return None


def _series_from_download(frame: pd.DataFrame, symbol: str, field: str = "Close") -> pd.Series:
    """Return one ticker/field series from yfinance.download across API layouts."""
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.Series(dtype=float)
    try:
        if isinstance(frame.columns, pd.MultiIndex):
            level0 = set(map(str, frame.columns.get_level_values(0)))
            level1 = set(map(str, frame.columns.get_level_values(1))) if frame.columns.nlevels > 1 else set()
            if symbol in level0:
                sub = frame[symbol]
                if isinstance(sub, pd.DataFrame) and field in sub.columns:
                    return pd.to_numeric(sub[field], errors="coerce")
            if field in level0:
                sub = frame[field]
                if isinstance(sub, pd.DataFrame) and symbol in sub.columns:
                    return pd.to_numeric(sub[symbol], errors="coerce")
            if symbol in level1:
                try:
                    sub = frame.xs(symbol, axis=1, level=1)
                    if field in sub.columns:
                        return pd.to_numeric(sub[field], errors="coerce")
                except Exception:
                    pass
        elif field in frame.columns:
            return pd.to_numeric(frame[field], errors="coerce")
    except Exception:
        pass
    return pd.Series(dtype=float)


def fetch_quotes_batch(symbols: list[str] | tuple[str, ...]) -> dict[str, dict]:
    """Fetch many displayed prices with at most two Yahoo chart requests.

    Price retrieval deliberately avoids ``get_info``.  Yahoo's quote-summary
    endpoint can be slow/rate-limited even when chart data is available; a
    dashboard should not lose all prices because company metadata failed.
    """
    normalized: list[str] = []
    invalid: dict[str, str] = {}
    for raw in symbols:
        try:
            value = normalize_symbol(raw)
            if value not in normalized:
                normalized.append(value)
        except ValueError as exc:
            invalid[str(raw)] = str(exc)

    results: dict[str, dict] = {}
    for symbol in normalized:
        shell = _quote_shell(symbol)
        shell.update(currency=_default_currency(symbol), delay_note=_delay_note(symbol))
        results[symbol] = shell
    for raw, message in invalid.items():
        shell = _quote_shell(raw)
        shell["error"] = message
        results[raw] = shell
    if not normalized:
        return results

    def download(period: str, interval: str):
        return yf.download(
            tickers=normalized,
            period=period,
            interval=interval,
            group_by="ticker",
            auto_adjust=False,
            actions=False,
            threads=False,
            progress=False,
            prepost=False,
            timeout=_HISTORY_TIMEOUT,
        )

    minute = pd.DataFrame()
    daily = pd.DataFrame()
    minute_error = None
    daily_error = None
    try:
        minute = _bounded(("download", tuple(normalized), "5d", "1m"),
                          lambda: download("5d", "1m"), ttl=45)
    except Exception as exc:
        minute_error = exc
    try:
        daily = _bounded(("download", tuple(normalized), "1mo", "1d"),
                         lambda: download("1mo", "1d"), ttl=180)
    except Exception as exc:
        daily_error = exc

    for symbol in normalized:
        result = results[symbol]
        intraday = _series_from_download(minute, symbol).dropna()
        days = _series_from_download(daily, symbol).dropna()
        intraday = intraday[np.isfinite(intraday) & (intraday > 0)]
        days = days[np.isfinite(days) & (days > 0)]
        previous = _positive(days.iloc[-2]) if len(days) >= 2 else None

        if not intraday.empty:
            stamp = pd.Timestamp(intraday.index[-1])
            price = _positive(intraday.iloc[-1])
            asof = stamp.isoformat() if stamp.tzinfo is not None else str(stamp)
            result.update(
                price=price,
                asof=asof,
                asof_label="최근 정규장 1분봉 시작 시각 · 봉 종가",
                previous_close=previous,
                change_pct=(price / previous - 1) * 100 if price and previous else None,
                source=f"{SOURCE} · 일괄 1분봉 가격 데이터",
            )
            continue

        if not days.empty:
            stamp = pd.Timestamp(days.index[-1])
            price = _positive(days.iloc[-1])
            result.update(
                price=price,
                asof=stamp.date().isoformat(),
                asof_label="최근 일봉 날짜 · 당일 봉은 미완성일 수 있음",
                previous_close=previous,
                change_pct=(price / previous - 1) * 100 if price and previous else None,
                source=f"{SOURCE} · 일괄 일봉 가격 데이터",
            )
            continue

        # Batch download can occasionally omit one ticker while returning others.
        # Retry only that symbol with the existing single-ticker history path.
        fallback_error = None
        for period, interval in [("5d", "1m"), ("1mo", "1d")]:
            try:
                frame, meta = _history(symbol, period, interval)
                if frame.empty:
                    continue
                stamp = pd.Timestamp(frame.index[-1])
                price = _positive(frame["Close"].iloc[-1])
                result["currency"] = _currency(symbol, meta) or result.get("currency")
                if interval == "1m":
                    asof = stamp.isoformat()
                    label = "최근 정규장 1분봉 시작 시각 · 봉 종가"
                    prev = None
                else:
                    asof = stamp.date().isoformat()
                    label = "최근 일봉 날짜 · 당일 봉은 미완성일 수 있음"
                    prev = _positive(frame["Close"].iloc[-2]) if len(frame) >= 2 else None
                result.update(
                    price=price, asof=asof, asof_label=label, previous_close=prev,
                    change_pct=(price / prev - 1) * 100 if price and prev else None,
                    source=f"{SOURCE} · 개별 {interval} 대체 조회",
                )
                break
            except Exception as exc:
                fallback_error = exc
        if result.get("price") is None:
            error = fallback_error or minute_error or daily_error
            result["error"] = _error(error) if error else "가격 데이터가 없습니다. 티커 또는 제공자 상태를 확인해 주세요."
    return results


def fetch_quote(symbol: str) -> dict:
    """Fetch one price through the history-first batch-safe path."""
    try:
        normalized = normalize_symbol(symbol)
    except ValueError as exc:
        result = _quote_shell(symbol)
        result["error"] = str(exc)
        return result
    return fetch_quotes_batch([normalized]).get(normalized, _quote_shell(normalized))


def fetch_profile(symbol: str) -> dict:
    result = {
        "symbol": str(symbol), "name": str(symbol), "kind": "stock", "currency": None,
        "sector": None, "industry": None, "source": SOURCE, "fetched_at": _now(), "error": None,
    }
    try:
        symbol = normalize_symbol(symbol)
        known = _KNOWN.get(symbol, {})
        result.update(symbol=symbol, name=known.get("name", symbol), kind=_kind(symbol, {}), currency=_currency(symbol, {}))
        info = _info(symbol)
        result.update(name=info.get("longName") or info.get("shortName") or result["name"],
                      kind=_kind(symbol, info), currency=_currency(symbol, info),
                      sector=info.get("sector") or None, industry=info.get("industry") or None)
        if not info:
            result["error"] = "기업·펀드 설명 데이터를 제공받지 못했습니다."
    except Exception as exc:
        result["error"] = str(exc) if isinstance(exc, ValueError) else _error(exc)
    return result


def fetch_fund(symbol: str) -> dict:
    result = {"symbol": str(symbol), "sectors": {}, "holdings": pd.DataFrame(),
              "source": SOURCE, "fetched_at": _now(), "asof": None, "error": None}
    try:
        symbol = normalize_symbol(symbol)
        result["symbol"] = symbol

        def read():
            data = yf.Ticker(symbol).funds_data
            errors = []
            try:
                sectors = data.sector_weightings or {}
            except Exception as exc:
                sectors = {}
                errors.append(_error(exc))
            try:
                holdings = data.top_holdings
            except Exception as exc:
                holdings = pd.DataFrame()
                errors.append(_error(exc))
            return sectors, holdings, errors

        sectors, holdings, errors = _bounded(("fund", symbol), read, ttl=21600)
        result["sectors"] = {str(k): float(v) for k, v in sectors.items()
                             if _number(v) is not None and 0 <= float(v) <= 1}
        if isinstance(holdings, pd.DataFrame):
            result["holdings"] = holdings.copy()
        # funds_data does not expose a trustworthy portfolio-as-of date here.
        # Do not promote fetched_at to a holdings report date.
        if errors:
            result["error"] = "일부 펀드 정보 누락: " + " / ".join(dict.fromkeys(errors))
        elif not result["sectors"] and result["holdings"].empty:
            result["error"] = "ETF 구성 데이터가 제공되지 않았습니다. 운용사 자료를 확인해 주세요."
    except Exception as exc:
        result["error"] = str(exc) if isinstance(exc, ValueError) else _error(exc)
    return result


def fetch_history(symbol: str, period: str = "1y") -> tuple[pd.DataFrame, str | None]:
    try:
        symbol = normalize_symbol(symbol)
        if period not in {"1mo", "3mo", "6mo", "1y", "2y", "5y", "max"}:
            raise ValueError("조회 기간을 확인해 주세요.")
        frame, meta = _history(symbol, period, "1d")
        if frame.empty:
            return frame, "일별 가격 데이터가 없습니다. 티커 또는 제공자 상태를 확인해 주세요."
        frame.attrs["currency"] = _currency(symbol, meta)
        frame.attrs["fetched_at"] = _now()
        return frame, None
    except Exception as exc:
        return pd.DataFrame(), str(exc) if isinstance(exc, ValueError) else _error(exc)


def _rsi_wilder(close: pd.Series, length: int = 14) -> pd.Series:
    """Wilder RSI with an initial SMA seed; flat windows are defined as 50."""
    out = pd.Series(np.nan, index=close.index, dtype=float)
    if len(close) <= length:
        return out
    changes = close.diff()
    up = changes.clip(lower=0).to_numpy(dtype=float)
    down = (-changes.clip(upper=0)).to_numpy(dtype=float)
    avg_up, avg_down = float(np.mean(up[1:length + 1])), float(np.mean(down[1:length + 1]))
    for i in range(length, len(close)):
        if i > length:
            avg_up = (avg_up * (length - 1) + up[i]) / length
            avg_down = (avg_down * (length - 1) + down[i]) / length
        out.iloc[i] = (50.0 if avg_up == 0 and avg_down == 0 else
                       100.0 if avg_down == 0 else 100 - 100 / (1 + avg_up / avg_down))
    return out


def add_indicators(frame: pd.DataFrame, adjusted: bool = True) -> pd.DataFrame:
    """Add indicators on one consistent basis; use AnalysisClose for plotting.

    Prefer provider Adj Close if every returned row has a valid value. A partial
    adjusted series is not mixed with raw prices. Set adjusted=False to select
    Close explicitly. The chosen basis is stored in DataFrame.attrs.
    """
    data = frame.copy()
    if data.empty or "Close" not in data:
        return data
    column = "Close"
    if adjusted and "Adj Close" in data:
        adjusted_close = pd.to_numeric(data["Adj Close"], errors="coerce")
        if adjusted_close.notna().all() and (adjusted_close > 0).all():
            column = "Adj Close"
    close = pd.to_numeric(data[column], errors="coerce")
    data["AnalysisClose"] = close
    data.attrs["indicator_price_column"] = column
    data.attrs["basis"] = (
        "Yahoo Adj Close 기준 · 분할·분배금 조정, 실제 계좌 수익률과 다를 수 있음"
        if column == "Adj Close" else
        "Yahoo Close 기준 · 배당 미반영, 기업행동에 따른 가격 변화가 지표에 영향을 줄 수 있음"
    )
    data["SMA20"] = close.rolling(20, min_periods=20).mean()
    data["SMA60"] = close.rolling(60, min_periods=60).mean()
    data["RSI14"] = _rsi_wilder(close)
    data["Volatility20"] = close.pct_change(fill_method=None).rolling(20, min_periods=20).std(ddof=1) * np.sqrt(252) * 100
    return data


def completed_daily_history(frame: pd.DataFrame) -> pd.DataFrame:
    """Conservatively exclude the current exchange-local calendar date.

    Exchange holidays and closing auctions are not inferred from a clock. Today's
    candle is excluded even after close; it becomes eligible on the next date.
    Naive indexes use UTC as a fallback and this is recorded in attrs.
    """
    if frame.empty:
        return frame.copy()
    index = pd.DatetimeIndex(frame.index)
    zone = index.tz or "UTC"
    today = pd.Timestamp.now(tz=zone).date()
    out = frame.loc[np.array([stamp.date() < today for stamp in index])].copy()
    out.attrs["completion_rule"] = "거래소 현지 날짜 기준 당일 일봉 제외 (장 마감 후에도 제외)"
    if index.tz is None:
        out.attrs["completion_rule"] += " · 시간대 미제공으로 UTC 날짜 사용"
    return out


def summary_from_history(frame: pd.DataFrame) -> dict:
    result = {
        "asof": None, "observations": 0, "close": None, "sma20": None, "sma60": None,
        "rsi14": None, "return_20d_pct": None, "annual_volatility_20d_pct": None,
        "facts": [], "error": None, "basis": "일봉 Close 기준 · 배당을 포함한 총수익률 아님",
        "completion_rule": "거래소 현지 날짜 기준 당일 일봉 제외 (장 마감 후에도 제외)",
    }
    if frame.empty or "Close" not in frame:
        result["error"] = "분석할 가격 데이터가 없습니다."
        return result
    completed = completed_daily_history(frame)
    completed = completed.loc[pd.to_numeric(completed["Close"], errors="coerce").notna()]
    data = add_indicators(completed)
    if data.empty:
        result["error"] = "완료된 일봉이 없습니다. 당일 일봉은 분석에서 제외합니다."
        return result
    row = data.iloc[-1]
    close = _positive(row["AnalysisClose"])
    result.update(asof=pd.Timestamp(data.index[-1]).date().isoformat(), observations=len(data), close=close,
                  sma20=_number(row.get("SMA20")), sma60=_number(row.get("SMA60")),
                  rsi14=_number(row.get("RSI14")), annual_volatility_20d_pct=_number(row.get("Volatility20")),
                  completion_rule=completed.attrs.get("completion_rule", result["completion_rule"]),
                  basis=data.attrs["basis"], price_column=data.attrs["indicator_price_column"])
    if len(data) >= 21:
        previous = _positive(data["AnalysisClose"].iloc[-21])
        if previous and close:
            result["return_20d_pct"] = (close / previous - 1) * 100
    facts = [f"분석 기준일은 {result['asof']}이며, 당일 일봉은 미완성 가능성 때문에 제외했습니다."]
    if close and result["sma20"]:
        gap = (close / result["sma20"] - 1) * 100
        facts.append(f"종가는 20거래일 이동평균 대비 {gap:+.2f}%입니다.")
    if result["sma20"] and result["sma60"]:
        relationship = "높습니다" if result["sma20"] > result["sma60"] else "낮습니다" if result["sma20"] < result["sma60"] else "같습니다"
        facts.append(f"20거래일 이동평균은 60거래일 이동평균보다 {relationship}.")
    rsi = result["rsi14"]
    if rsi is not None:
        condition = "최근 상승 폭이 하락 폭보다 크게 누적된 상태" if rsi >= 70 else "최근 하락 폭이 상승 폭보다 크게 누적된 상태" if rsi <= 30 else "통상적인 30~70 범위"
        facts.append(f"14거래일 RSI는 {rsi:.1f}로 {condition}입니다. 단독 매매 신호로 해석하지 않습니다.")
    if result["return_20d_pct"] is not None:
        facts.append(f"최근 20거래일 가격 변화율은 {result['return_20d_pct']:+.2f}%입니다. {result['basis']}.")
    if result["annual_volatility_20d_pct"] is not None:
        facts.append(f"최근 20개 일간 수익률의 연율화 변동성은 {result['annual_volatility_20d_pct']:.1f}%입니다 (연 252거래일 가정).")
    if len(data) < 60:
        facts.append("60거래일보다 짧은 데이터이므로 일부 이동평균은 계산하지 않았습니다.")
    facts.append("이 요약은 계산 규칙에 따른 관찰입니다. 미래 가격 예측이나 매수·매도 추천은 포함하지 않습니다.")
    result["facts"] = facts
    return result
