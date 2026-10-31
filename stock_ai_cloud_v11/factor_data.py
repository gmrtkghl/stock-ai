"""Fundamental, analyst-revision and Korean investor-flow data for screening.

The module never fabricates missing values. Yahoo Finance/yfinance supplies company
fundamentals and analyst estimates when available. For Korean equities, pykrx is an
optional no-key source for recent investor net-purchase values.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import math
import threading
from typing import Any

import pandas as pd
import yfinance as yf

try:
    from pykrx import stock as krx_stock
except Exception:
    krx_stock = None

_LOCK = threading.BoundedSemaphore(4)


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _pct(value: Any) -> float | None:
    number = _num(value)
    if number is None:
        return None
    # Yahoo ratios are normally fractions. Preserve already-percentage-looking data.
    return number * 100.0 if abs(number) <= 2.0 else number


def _safe_growth(current: Any, previous: Any) -> float | None:
    cur = _num(current)
    prev = _num(previous)
    if cur is None or prev is None or abs(prev) < 1e-12:
        return None
    return (cur - prev) / abs(prev) * 100.0


def _row(frame: Any, names: tuple[str, ...]) -> pd.Series | None:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return None
    normalized = {str(idx).casefold().replace(" ", "").replace("_", ""): idx for idx in frame.index}
    for name in names:
        key = name.casefold().replace(" ", "").replace("_", "")
        if key in normalized:
            result = frame.loc[normalized[key]]
            return result if isinstance(result, pd.Series) else None
    return None


def _ordered_values(series: pd.Series | None) -> list[tuple[Any, float]]:
    if series is None:
        return []
    items = []
    for key, raw in series.items():
        value = _num(raw)
        if value is None:
            continue
        try:
            stamp = pd.Timestamp(key)
        except Exception:
            stamp = key
        items.append((stamp, value))
    try:
        items.sort(key=lambda x: x[0], reverse=True)
    except Exception:
        pass
    return items


def _income_growth(ticker: yf.Ticker) -> tuple[float | None, float | None, str | None]:
    """Prefer latest quarter YoY; fall back to latest annual YoY."""
    frames: list[tuple[str, Any]] = []
    for label, freq in (("최근 분기 전년동기", "quarterly"), ("최근 연간 전년", "yearly")):
        try:
            frames.append((label, ticker.get_income_stmt(freq=freq)))
        except Exception:
            try:
                frames.append((label, ticker.quarterly_income_stmt if freq == "quarterly" else ticker.income_stmt))
            except Exception:
                pass

    for label, frame in frames:
        revenue = _ordered_values(_row(frame, ("Total Revenue", "TotalRevenue", "Operating Revenue")))
        operating = _ordered_values(_row(frame, ("Operating Income", "OperatingIncome")))
        if label.startswith("최근 분기"):
            if len(revenue) >= 5 and len(operating) >= 5:
                return _safe_growth(revenue[0][1], revenue[4][1]), _safe_growth(operating[0][1], operating[4][1]), label
        elif len(revenue) >= 2 and len(operating) >= 2:
            return _safe_growth(revenue[0][1], revenue[1][1]), _safe_growth(operating[0][1], operating[1][1]), label
    return None, None, None


def _frame_row(frame: Any, preferred: tuple[str, ...]) -> pd.Series | None:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return None
    for idx in preferred:
        if idx in frame.index:
            row = frame.loc[idx]
            return row if isinstance(row, pd.Series) else None
    return frame.iloc[0] if len(frame.index) else None


def _eps_revision(ticker: yf.Ticker) -> dict:
    result = {
        "eps_current": None,
        "eps_30d_ago": None,
        "eps_90d_ago": None,
        "eps_revision_30d_pct": None,
        "eps_revision_90d_pct": None,
        "eps_revision_net_30d": None,
        "analyst_count": None,
        "eps_basis": None,
    }
    try:
        trend = ticker.get_eps_trend()
        row = _frame_row(trend, ("0y", "+1y", "0q", "+1q"))
        if row is not None:
            current = _num(row.get("current"))
            d30 = _num(row.get("30daysAgo"))
            d90 = _num(row.get("90daysAgo"))
            result.update(
                eps_current=current,
                eps_30d_ago=d30,
                eps_90d_ago=d90,
                eps_revision_30d_pct=_safe_growth(current, d30),
                eps_revision_90d_pct=_safe_growth(current, d90),
                eps_basis="애널리스트 EPS 컨센서스 추세",
            )
    except Exception:
        pass

    try:
        revisions = ticker.get_eps_revisions()
        row = _frame_row(revisions, ("0y", "+1y", "0q", "+1q"))
        if row is not None:
            up = _num(row.get("upLast30days"))
            down = _num(row.get("downLast30days"))
            if up is not None or down is not None:
                result["eps_revision_net_30d"] = int((up or 0) - (down or 0))
    except Exception:
        pass

    try:
        estimates = ticker.get_earnings_estimate()
        row = _frame_row(estimates, ("0y", "+1y", "0q", "+1q"))
        if row is not None:
            count = _num(row.get("numberOfAnalysts"))
            if count is not None:
                result["analyst_count"] = int(count)
    except Exception:
        pass
    return result


def _korean_investor_flow(symbol: str) -> dict:
    result = {
        "flow_available": False,
        "flow_days": 0,
        "foreign_net_value_20d": None,
        "institution_net_value_20d": None,
        "foreign_institution_both_positive": None,
        "flow_source": None,
        "flow_error": None,
    }
    if not symbol.endswith((".KS", ".KQ")):
        return result
    if krx_stock is None:
        result["flow_error"] = "pykrx를 불러오지 못해 외국인·기관 수급을 확인하지 못했습니다."
        return result

    code = symbol.split(".")[0]
    end = datetime.now().date()
    start = end - timedelta(days=55)
    try:
        frame = krx_stock.get_market_trading_value_by_date(
            start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), code
        )
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            result["flow_error"] = "KRX 투자자 수급 자료가 비어 있습니다."
            return result
        frame = frame.tail(20)
        inst_col = next((c for c in ("기관합계", "기관") if c in frame.columns), None)
        foreign_col = next((c for c in ("외국인합계", "외국인") if c in frame.columns), None)
        if inst_col is None or foreign_col is None:
            result["flow_error"] = "KRX 수급 열 형식을 확인하지 못했습니다."
            return result
        inst = pd.to_numeric(frame[inst_col], errors="coerce").fillna(0).sum()
        foreign = pd.to_numeric(frame[foreign_col], errors="coerce").fillna(0).sum()
        result.update(
            flow_available=True,
            flow_days=int(len(frame)),
            foreign_net_value_20d=float(foreign),
            institution_net_value_20d=float(inst),
            foreign_institution_both_positive=bool(foreign > 0 and inst > 0),
            flow_source="KRX / pykrx",
        )
    except Exception as exc:
        result["flow_error"] = f"KRX 수급 조회 실패 ({type(exc).__name__})"
    return result


def fetch_factor_snapshot(symbol: str) -> dict:
    """Fetch financial/analyst factors for one symbol without inventing missing data."""
    symbol = str(symbol or "").strip().upper()
    result = {
        "symbol": symbol,
        "applicable": False,
        "quote_type": None,
        "market_group": "KR" if symbol.endswith((".KS", ".KQ")) else "US_OR_OTHER",
        "revenue_growth_pct": None,
        "operating_income_growth_pct": None,
        "growth_period": None,
        "roe_pct": None,
        "dividend_yield_pct": None,
        "pbr": None,
        "market_cap": None,
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "error": None,
    }
    acquired = _LOCK.acquire(timeout=12)
    if not acquired:
        result["error"] = "재무 데이터 조회가 밀려 이번 분석에서는 제외했습니다."
        return result
    try:
        ticker = yf.Ticker(symbol)
        info = {}
        try:
            raw = ticker.get_info()
            info = dict(raw) if isinstance(raw, dict) else {}
        except Exception:
            pass
        quote_type = str(info.get("quoteType") or "").upper()
        result["quote_type"] = quote_type or None
        if quote_type and quote_type not in {"EQUITY", "STOCK"}:
            result["error"] = "ETF·지수에는 개별기업 재무 필터를 적용하지 않습니다."
            return result

        result["applicable"] = True
        result["roe_pct"] = _pct(info.get("returnOnEquity"))
        result["dividend_yield_pct"] = _pct(info.get("dividendYield"))
        result["pbr"] = _num(info.get("priceToBook"))
        result["market_cap"] = _num(info.get("marketCap"))
        revenue_growth, op_growth, basis = _income_growth(ticker)
        result["revenue_growth_pct"] = revenue_growth
        result["operating_income_growth_pct"] = op_growth
        result["growth_period"] = basis
        result.update(_eps_revision(ticker))
        result.update(_korean_investor_flow(symbol))

        available = [
            result.get("revenue_growth_pct"), result.get("operating_income_growth_pct"),
            result.get("roe_pct"), result.get("pbr"), result.get("dividend_yield_pct"),
            result.get("eps_revision_30d_pct"), result.get("eps_revision_90d_pct"),
        ]
        if not any(x is not None for x in available):
            result["error"] = "제공자가 재무·애널리스트 지표를 충분히 제공하지 않았습니다."
    except Exception as exc:
        result["error"] = f"재무·애널리스트 데이터를 불러오지 못했습니다 ({type(exc).__name__})."
    finally:
        _LOCK.release()
    return result


def volume_spike_from_history(history: Any) -> dict:
    result = {"volume_ratio_pct": None, "latest_volume": None, "avg_prev_5d_volume": None, "volume_pass_200": None}
    if not isinstance(history, pd.DataFrame) or history.empty or "Volume" not in history.columns:
        return result
    volume = pd.to_numeric(history["Volume"], errors="coerce")
    volume = volume.loc[volume.notna() & (volume > 0)]
    if len(volume) < 6:
        return result
    latest = float(volume.iloc[-1])
    base = float(volume.iloc[-6:-1].mean())
    if base <= 0:
        return result
    ratio = latest / base * 100.0
    result.update(volume_ratio_pct=ratio, latest_volume=latest, avg_prev_5d_volume=base, volume_pass_200=bool(ratio >= 200.0))
    return result


def build_factor_screen(
    factor: dict,
    *,
    roe_reference_pct: float = 10.0,
    roe_reference_label: str = "기본 기준 10%",
    market_cap_reference: float | None = None,
    volume_signal: dict | None = None,
) -> dict:
    """Score growth/quality/volume-flow categories. Missing data is neutral, not negative."""
    volume_signal = volume_signal or {}
    if not factor.get("applicable"):
        return {
            "applicable": False,
            "score": 0.0,
            "evidence_count": 0,
            "growth_pass": False,
            "quality_pass": False,
            "flow_pass": False,
            "labels": [],
            "positive": [],
            "caution": [],
            "missing": [factor.get("error") or "개별기업 재무 필터 비대상"],
            "roe_reference_pct": roe_reference_pct,
            "roe_reference_label": roe_reference_label,
            "metrics": {**factor, **volume_signal},
        }

    rev = _num(factor.get("revenue_growth_pct"))
    op = _num(factor.get("operating_income_growth_pct"))
    roe = _num(factor.get("roe_pct"))
    div = _num(factor.get("dividend_yield_pct"))
    pbr = _num(factor.get("pbr"))
    eps30 = _num(factor.get("eps_revision_30d_pct"))
    eps90 = _num(factor.get("eps_revision_90d_pct"))
    eps_net = _num(factor.get("eps_revision_net_30d"))
    cap = _num(factor.get("market_cap"))
    vol_ratio = _num(volume_signal.get("volume_ratio_pct"))
    both_flow = factor.get("foreign_institution_both_positive")

    positive: list[str] = []
    caution: list[str] = []
    missing: list[str] = []
    evidence = 0
    score = 0.0

    def check(value: float | None, passed: bool, pos_text: str, neg_text: str, weight: float, *, penalize=False):
        nonlocal evidence, score
        if value is None:
            return None
        evidence += 1
        if passed:
            score += weight
            positive.append(pos_text)
            return True
        if penalize:
            score -= weight * 0.55
            caution.append(neg_text)
        return False

    rev_ok = check(rev, rev is not None and rev > 0, f"매출 증가율 {rev:+.1f}%로 증가했습니다.", f"매출 증가율 {rev:+.1f}%로 감소했습니다.", 0.45, penalize=True) if rev is not None else None
    op_ok = check(op, op is not None and op > 0, f"영업이익 증가율 {op:+.1f}%로 증가했습니다.", f"영업이익 증가율 {op:+.1f}%로 감소했습니다.", 0.55, penalize=True) if op is not None else None
    roe_ok = check(roe, roe is not None and roe >= roe_reference_pct, f"ROE {roe:.1f}%로 {roe_reference_label}({roe_reference_pct:.1f}%) 이상입니다.", f"ROE {roe:.1f}%로 {roe_reference_label}({roe_reference_pct:.1f}%)보다 낮습니다.", 0.40, penalize=True) if roe is not None else None

    eps_up = None
    if eps30 is not None or eps90 is not None or eps_net is not None:
        evidence += 1
        eps_up = bool((eps30 is not None and eps30 > 0) or (eps90 is not None and eps90 > 0) or (eps_net is not None and eps_net > 0))
        if eps_up:
            score += 0.60
            parts = []
            if eps30 is not None: parts.append(f"30일 {eps30:+.1f}%")
            if eps90 is not None: parts.append(f"90일 {eps90:+.1f}%")
            if eps_net is not None: parts.append(f"30일 상향-하향 {int(eps_net):+d}건")
            positive.append("EPS 추정치가 최근 1~3개월 기준 상향 방향입니다" + (" (" + ", ".join(parts) + ")" if parts else "") + ".")
        else:
            score -= 0.35
            caution.append("최근 1~3개월 EPS 추정치에서 뚜렷한 상향 조정을 확인하지 못했습니다.")

    growth_checks = [x for x in (rev_ok, op_ok, roe_ok, eps_up) if x is not None]
    growth_pass = len(growth_checks) >= 3 and all(growth_checks)

    div_ok = check(div, div is not None and div >= 0.1, f"배당수익률 {div:.2f}%로 0.1% 이상입니다.", f"배당수익률 {div:.2f}%로 0.1% 기준에 못 미칩니다.", 0.20) if div is not None else None
    pbr_ok = check(pbr, pbr is not None and 0 < pbr <= 1.5, f"PBR {pbr:.2f}배로 1.5배 이하입니다.", f"PBR {pbr:.2f}배로 1.5배를 초과합니다.", 0.25) if pbr is not None else None
    quality_checks = [x for x in (roe_ok, div_ok, pbr_ok) if x is not None]
    quality_pass = len(quality_checks) == 3 and all(quality_checks)
    if quality_pass:
        score += 0.25

    small_mid = None
    if cap is not None and market_cap_reference is not None and market_cap_reference > 0:
        evidence += 1
        small_mid = bool(cap <= market_cap_reference)
        if small_mid:
            score += 0.15
            positive.append("시가총액이 같은 시장 후보군 중앙값 이하로 중소형 후보군에 해당합니다.")

    volume_ok = None
    if vol_ratio is not None:
        evidence += 1
        volume_ok = bool(vol_ratio >= 200.0)
        if volume_ok:
            score += 0.35
            positive.append(f"최근 완료 거래일 거래량이 직전 5거래일 평균의 {vol_ratio:.0f}%로 200% 기준을 넘었습니다.")
        elif vol_ratio < 100:
            caution.append(f"거래량은 직전 5거래일 평균의 {vol_ratio:.0f}% 수준입니다.")

    flow_ok = None
    if factor.get("market_group") == "KR":
        if both_flow is None:
            missing.append(factor.get("flow_error") or "최근 외국인·기관 수급 데이터 미확인")
        else:
            evidence += 1
            flow_ok = bool(both_flow)
            if flow_ok:
                score += 0.50
                positive.append("최근 약 20거래일 외국인과 기관의 누적 순매수가 모두 플러스입니다.")
            else:
                caution.append("최근 약 20거래일 외국인·기관의 동반 순매수 조건을 충족하지 못했습니다.")
    else:
        missing.append("외국인·기관 동반 순매수 기준은 한국 상장주에만 적용합니다.")

    flow_pass = bool(volume_ok and (flow_ok if factor.get("market_group") == "KR" else True))
    labels = []
    if growth_pass: labels.append("성장주 기준 통과")
    if quality_pass: labels.append("퀄리티 기준 통과")
    if flow_pass: labels.append("거래량·수급 주목")
    if small_mid and volume_ok: labels.append("중소형·거래량 주목")

    for key, text in (
        (rev, "매출 증가율"), (op, "영업이익 증가율"), (roe, "ROE"),
        (div, "배당수익률"), (pbr, "PBR"),
    ):
        if key is None:
            missing.append(f"{text} 데이터 미확인")
    if eps30 is None and eps90 is None and eps_net is None:
        missing.append("EPS 추정치 상향·하향 데이터 미확인")
    if vol_ratio is None:
        missing.append("거래량 비교 데이터 미확인")

    return {
        "applicable": True,
        "score": max(-1.5, min(3.2, score)),
        "evidence_count": evidence,
        "growth_pass": growth_pass,
        "quality_pass": quality_pass,
        "flow_pass": flow_pass,
        "small_mid": small_mid,
        "labels": labels,
        "positive": positive[:8],
        "caution": caution[:8],
        "missing": list(dict.fromkeys(x for x in missing if x))[:8],
        "roe_reference_pct": roe_reference_pct,
        "roe_reference_label": roe_reference_label,
        "market_cap_reference": market_cap_reference,
        "metrics": {**factor, **volume_signal},
    }
