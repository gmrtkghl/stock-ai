"""Local holdings, valuation, and configurable reference thresholds.

This module never places orders or calls a network service. Prices must be passed
in from the quote layer. Defaults are editable examples, not recommendations.
"""
from __future__ import annotations

import json
import math
import os
import re
import tempfile
import threading
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any

from market_data import OPTIONAL_INSTRUMENTS, WATCHLIST, normalize_symbol


SCHEMA_VERSION = 1
MAX_POSITIONS = 24
_KNOWN_KINDS = {item["symbol"]: item["kind"] for item in WATCHLIST + OPTIONAL_INSTRUMENTS}
_SAVE_LOCK = threading.Lock()


def _decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError(f"{label}은 유효한 숫자로 입력해 주세요.")
    try:
        number = Decimal(str(value).strip())
        converted = float(number)
    except (InvalidOperation, ValueError, OverflowError):
        raise ValueError(f"{label}은 유효한 숫자로 입력해 주세요.") from None
    if not number.is_finite() or not math.isfinite(converted):
        raise ValueError(f"{label}은 유한한 숫자여야 합니다.")
    if number != 0 and converted == 0:
        raise ValueError(f"{label}의 절댓값이 너무 작습니다.")
    return number


def _float(number: Decimal, label: str) -> float:
    try:
        value = float(number)
    except (ValueError, OverflowError):
        raise ValueError(f"{label}이 계산 가능한 범위를 벗어났습니다.") from None
    if not math.isfinite(value) or (number != 0 and value == 0):
        raise ValueError(f"{label}이 계산 가능한 범위를 벗어났습니다.")
    return value


def _currency(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z]{3,8}", value.strip()):
        raise ValueError("통화 코드를 확인해 주세요. 예: KRW, USD")
    stripped = value.strip()
    # GBp and ZAc denote minor units; silently uppercasing them changes the unit.
    return stripped if stripped in {"GBp", "ZAc"} else stripped.upper()


def _asof(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            date.fromisoformat(text)
        elif "T" in text or " " in text:
            datetime.fromisoformat(text.replace("Z", "+00:00"))
        else:
            return None
    except ValueError:
        return None
    return text


def validate_position(position: dict) -> dict:
    """Normalize one holding or raise ValueError without changing the input."""
    if not isinstance(position, dict):
        raise ValueError("보유 종목은 객체 형식이어야 합니다.")
    if not isinstance(position.get("symbol"), str):
        raise ValueError("종목 티커는 문자열로 입력해 주세요.")
    symbol = normalize_symbol(position.get("symbol", ""))
    kind = str(position.get("kind", "")).strip().lower()
    if symbol.startswith("^") or kind == "index" or _KNOWN_KINDS.get(symbol) == "index":
        raise ValueError("지수 자체는 보유 종목으로 등록할 수 없습니다. 실제 보유한 ETF의 티커를 사용해 주세요.")
    avg_cost = _decimal(position.get("avg_cost"), "평균 매수가")
    quantity = _decimal(position.get("quantity"), "보유 수량")
    if avg_cost <= 0 or quantity <= 0:
        raise ValueError("평균 매수가와 보유 수량은 0보다 커야 합니다. 소수점 수량도 입력할 수 있습니다.")
    profit = _decimal(position.get("profit_target_pct", 15.0), "이익 검토 기준")
    loss = _decimal(position.get("loss_review_pct", -7.0), "손실 검토 기준")
    buy = _decimal(position.get("buy_review_pct", -10.0), "추가매수 검토 기준")
    if not (0 < profit <= 1000):
        raise ValueError("이익 검토 기준은 0% 초과, 1,000% 이하여야 합니다.")
    if not (-100 < loss < 0) or not (-100 < buy < 0):
        raise ValueError("손실·추가매수 검토 기준은 -100% 초과, 0% 미만이어야 합니다.")
    enabled = position.get("enable_buy_review", False)
    if not isinstance(enabled, bool):
        raise ValueError("추가매수 검토 사용 여부는 참 또는 거짓이어야 합니다.")
    return {
        "symbol": symbol, "avg_cost": _float(avg_cost, "평균 매수가"),
        "quantity": _float(quantity, "보유 수량"), "currency": _currency(position.get("currency")),
        "profit_target_pct": _float(profit, "이익 검토 기준"),
        "loss_review_pct": _float(loss, "손실 검토 기준"),
        "buy_review_pct": _float(buy, "추가매수 검토 기준"), "enable_buy_review": enabled,
    }


def _positions(positions: Any) -> dict[str, dict]:
    if not isinstance(positions, dict):
        raise ValueError("positions는 티커를 키로 사용하는 객체여야 합니다.")
    if len(positions) > MAX_POSITIONS:
        raise ValueError(f"보유 종목은 최대 {MAX_POSITIONS}개까지 저장할 수 있습니다.")
    normalized = {}
    for key, item in positions.items():
        if not isinstance(key, str):
            raise ValueError("보유 종목의 저장 키는 티커 문자열이어야 합니다.")
        symbol = normalize_symbol(key)
        row = validate_position(item)
        if row["symbol"] != symbol:
            raise ValueError(f"저장 키 {symbol}와 종목 티커가 일치하지 않습니다.")
        if symbol in normalized:
            raise ValueError(f"{symbol}이 중복되어 있습니다.")
        normalized[symbol] = row
    return normalized


def _document(raw: bytes) -> tuple[dict, dict[str, dict]]:
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("보유 종목 파일의 JSON 형식이 올바르지 않습니다.") from None
    if not isinstance(payload, dict) or type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
        raise ValueError("지원하지 않는 보유 종목 파일 형식입니다 (schema_version=1 필요).")
    return payload, _positions(payload.get("positions"))


def load_portfolio(path: Path) -> tuple[dict[str, dict], str | None]:
    """Read without writing. Invalid files produce no partial replacement data."""
    path = Path(path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {}, None
    except OSError:
        return {}, "보유 종목 파일을 읽을 수 없습니다. 파일 위치와 읽기 권한을 확인해 주세요. 원본은 변경하지 않았습니다."
    try:
        _, positions = _document(raw)
        return positions, None
    except (ValueError, TypeError) as exc:
        return {}, f"{exc} 원본은 변경하지 않았습니다. 파일을 백업한 뒤 형식을 확인해 주세요."


def save_portfolio(path: Path, positions: dict[str, dict]) -> str | None:
    """Validate before an atomic write; refuse to overwrite malformed old files.

    Unknown top-level fields and existing per-position metadata are preserved.
    A concurrent external change detected before replacement aborts the write.
    """
    path = Path(path)
    try:
        normalized = _positions(positions)
    except (ValueError, TypeError) as exc:
        return f"저장하지 않았습니다: {exc}"
    temporary = None
    with _SAVE_LOCK:
        try:
            try:
                before = path.read_bytes()
            except FileNotFoundError:
                before = None
            if before is not None:
                payload, _ = _document(before)
                old_positions = {normalize_symbol(key): value for key, value in payload["positions"].items()}
            else:
                payload, old_positions = {}, {}
            payload["schema_version"] = SCHEMA_VERSION
            payload["positions"] = {symbol: {**old_positions.get(symbol, {}), **row}
                                    for symbol, row in normalized.items()}
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            try:
                latest = path.read_bytes()
            except FileNotFoundError:
                latest = None
            if latest != before:
                return "다른 창이나 프로그램에서 보유 종목 파일을 변경했습니다. 다시 불러온 뒤 저장해 주세요. 기존 파일은 유지했습니다."
            os.replace(temporary, path)
            temporary = None
            return None
        except (ValueError, TypeError) as exc:
            return f"저장하지 않았습니다: {exc} 기존 파일을 백업한 뒤 형식을 확인해 주세요."
        except OSError:
            return "보유 종목 파일을 저장할 수 없습니다. 폴더 쓰기 권한·남은 용량·파일 잠금을 확인해 주세요. 기존 파일은 유지했습니다."
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass


def evaluate_signals(return_pct: Any, position: dict, quote: dict | None = None) -> list[dict]:
    """Return reference conditions only when a valid dated quote is supplied."""
    if not isinstance(quote, dict) or quote.get("error") or not _asof(quote.get("asof")):
        return []
    try:
        position = validate_position(position)
        performance = _decimal(return_pct, "수익률")
        if _decimal(quote.get("price"), "가격") <= 0:
            return []
        if _currency(quote.get("currency")) != position["currency"]:
            return []
        quote_symbol = quote.get("symbol")
        if quote_symbol is not None and normalize_symbol(quote_symbol) != position["symbol"]:
            return []
    except (ValueError, TypeError):
        return []
    signals = []
    common = "설정한 참고 조건의 충족 여부이며 자동 주문은 실행하지 않습니다."
    if performance >= Decimal(str(position["profit_target_pct"])):
        signals.append({"level": "info", "code": "profit_review", "label": "이익 실현·비중 조절 검토",
                        "detail": f"수익률이 설정한 +{position['profit_target_pct']:g}% 이상입니다. 투자 계획과 보유 비중을 확인해 주세요. {common}"})
    if performance <= Decimal(str(position["loss_review_pct"])):
        signals.append({"level": "warning", "code": "loss_review", "label": "손실 원인·비중 축소 검토",
                        "detail": f"수익률이 설정한 {position['loss_review_pct']:g}% 이하입니다. 손실 원인과 투자 근거를 다시 확인해 주세요. {common}"})
    if position["enable_buy_review"] and performance <= Decimal(str(position["buy_review_pct"])):
        signals.append({"level": "warning", "code": "buy_review", "label": "추가매수 검토 조건 도달",
                        "detail": f"수익률이 설정한 {position['buy_review_pct']:g}% 이하입니다. 가격 하락만으로 매수하지 말고 투자 근거·새 정보·가용 자금을 먼저 확인해 주세요. {common}"})
    return signals


def evaluate_position(position: dict, quote: dict | None) -> dict:
    """Value raw-price holdings, retaining inputs when quote data is missing.

    Unknown quote date: numerical valuation is allowed but signals are withheld.
    The result describes the supplied quote's date, not necessarily the present.
    Fees, taxes, cash dividends and FX conversion are not included.
    """
    original = position if isinstance(position, dict) else {}
    result = {"symbol": original.get("symbol"), "currency": original.get("currency"),
              "avg_cost": original.get("avg_cost"), "quantity": original.get("quantity"),
              "cost_basis": None, "value": None, "pnl": None, "return_pct": None,
              "price": None, "price_asof": None, "error": None, "warning": None,
              "signals": [], "valuation_basis": "제공된 일반 시세 × 보유 수량 · 수수료·세금·배당·환율 미반영"}
    try:
        row = validate_position(position)
        result.update(row)
        with localcontext() as context:
            context.prec = 40
            avg_cost = Decimal(str(row["avg_cost"]))
            quantity = Decimal(str(row["quantity"]))
            basis = avg_cost * quantity
            result["cost_basis"] = _float(basis, "매입 원금")
            if not isinstance(quote, dict) or quote.get("error"):
                result["error"] = "시세를 확인할 수 없어 평가 금액과 손익을 계산하지 않았습니다."
                return result
            if quote.get("symbol") is not None and normalize_symbol(quote["symbol"]) != row["symbol"]:
                result["error"] = "보유 종목과 시세의 티커가 달라 손익을 계산하지 않았습니다."
                return result
            if _currency(quote.get("currency")) != row["currency"]:
                result["error"] = "매수가와 시세의 통화가 달라 손익을 계산하지 않았습니다. 같은 통화·단위로 입력해 주세요."
                return result
            price = _decimal(quote.get("price"), "시세")
            if price <= 0:
                raise ValueError("시세가 없거나 0 이하이므로 손익을 계산하지 않았습니다.")
            value = price * quantity
            pnl = value - basis
            performance = (price / avg_cost - 1) * 100
            # Compute and validate all numbers before mutating the result.
            values = {"price": _float(price, "시세"), "value": _float(value, "평가 금액"),
                      "pnl": _float(pnl, "평가 손익"), "return_pct": _float(performance, "수익률")}
            result.update(values)
            result["price_asof"] = _asof(quote.get("asof"))
            if result["price_asof"] is None:
                result["warning"] = "시세 기준 시각을 확인할 수 없습니다. 계산값은 참고용이며 기준 신호는 표시하지 않습니다."
            else:
                result["signals"] = evaluate_signals(performance, row, quote)
    except (ValueError, TypeError, InvalidOperation) as exc:
        result["error"] = str(exc)
    return result


def total_by_currency(evaluated) -> list[dict]:
    """Group without converting currencies; incomplete portfolios have no total P&L."""
    rows = evaluated.values() if isinstance(evaluated, dict) else evaluated
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row.get("currency") or "통화 미확인", []).append(row)
    totals = []
    for currency, items in groups.items():
        total = {"currency": currency, "cost_basis": None, "value": None, "pnl": None,
                 "return_pct": None, "priced_count": 0, "total_count": len(items),
                 "missing_symbols": [], "complete": False, "priced_cost_basis": None,
                 "priced_value": None, "priced_pnl": None, "priced_return_pct": None,
                 "timestamp_complete": all(bool(item.get("price_asof")) for item in items), "error": None}
        try:
            with localcontext() as context:
                context.prec = 40
                bases, priced_bases, values, pnls = [], [], [], []
                all_bases_known = True
                for item in items:
                    try:
                        basis = _decimal(item.get("cost_basis"), "매입 원금")
                        if basis <= 0:
                            raise ValueError("매입 원금은 양수여야 합니다.")
                        bases.append(basis)
                    except ValueError:
                        basis = None
                        all_bases_known = False
                    if item.get("error") or basis is None or item.get("value") is None or item.get("pnl") is None:
                        total["missing_symbols"].append(item.get("symbol") or "티커 미확인")
                        continue
                    try:
                        value = _decimal(item["value"], "평가 금액")
                        pnl = _decimal(item["pnl"], "평가 손익")
                        if value <= 0:
                            raise ValueError("평가 금액은 양수여야 합니다.")
                    except ValueError:
                        total["missing_symbols"].append(item.get("symbol") or "티커 미확인")
                        continue
                    priced_bases.append(basis)
                    values.append(value)
                    pnls.append(pnl)
                if all_bases_known:
                    total["cost_basis"] = _float(sum(bases, Decimal(0)), "매입 원금 합계")
                total["priced_count"] = len(values)
                if values:
                    priced_basis = sum(priced_bases, Decimal(0))
                    priced_value = sum(values, Decimal(0))
                    priced_pnl = sum(pnls, Decimal(0))
                    total.update(priced_cost_basis=_float(priced_basis, "조회된 원금 소계"),
                                 priced_value=_float(priced_value, "조회된 평가 금액 소계"),
                                 priced_pnl=_float(priced_pnl, "조회된 손익 소계"),
                                 priced_return_pct=_float(priced_pnl / priced_basis * 100, "조회된 수익률"))
                total["complete"] = bool(items) and len(values) == len(items) and all_bases_known
                if total["complete"]:
                    total.update(value=total["priced_value"], pnl=total["priced_pnl"],
                                 return_pct=total["priced_return_pct"])
        except (ValueError, InvalidOperation) as exc:
            total.update(complete=False, value=None, pnl=None, return_pct=None, error=str(exc))
        totals.append(total)
    return totals
