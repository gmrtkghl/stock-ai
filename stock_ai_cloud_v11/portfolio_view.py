"""보유 입력, 평가손익과 사용자 검토 기준의 Streamlit 화면."""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from portfolio import evaluate_position, save_portfolio, total_by_currency, validate_position


def _number(value):
    try:
        return value is not None and math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def money(value, currency, signed=False):
    if not _number(value):
        return "확인 불가"
    digits = 0 if currency == "KRW" else 2
    number = f"{float(value):+,.{digits}f}" if signed else f"{float(value):,.{digits}f}"
    return f"{number} 원" if currency == "KRW" else f"{number} {currency}"


def percentage(value):
    return f"{float(value):+.2f}%" if _number(value) else "확인 불가"


def time_label(value):
    if not value:
        return "시각 미제공"
    try:
        ts = pd.Timestamp(value)
        return ts.strftime("%Y-%m-%d") if ts.tzinfo is None else ts.tz_convert("Asia/Seoul").strftime("%m/%d %H:%M KST")
    except (TypeError, ValueError):
        return str(value)


def portfolio_chart_data(evaluated, name_fn):
    quantities = []
    values = {}
    for item in evaluated:
        symbol = item.get("symbol")
        name = name_fn(symbol) if symbol else "티커 미확인"
        quantity = item.get("quantity")
        if _number(quantity) and float(quantity) > 0:
            quantities.append({"종목": name, "보유수량": float(quantity)})
        value = item.get("value")
        currency = item.get("currency") or "통화 미확인"
        if _number(value) and float(value) > 0:
            values.setdefault(currency, []).append({"종목": name, "평가금액": float(value)})
    return quantities, values


def render_portfolio_charts(evaluated, name_fn):
    quantities, values = portfolio_chart_data(evaluated, name_fn)
    if not quantities and not values:
        return
    st.markdown("**내 포트폴리오 한눈에**")
    columns = st.columns(1 + min(2, len(values)))
    with columns[0].container(border=True):
        st.caption("종목별 보유수량")
        if quantities:
            rows = sorted(quantities, key=lambda x: x["보유수량"], reverse=True)
            fig = go.Figure(go.Bar(x=[r["보유수량"] for r in rows], y=[r["종목"] for r in rows], orientation="h"))
            fig.update_layout(height=max(250, 44 * len(rows)), margin=dict(l=10, r=20, t=5, b=10),
                              template="plotly_white", xaxis_title="보유수량(주)", yaxis_autorange="reversed",
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, width="stretch", key="portfolio_quantity_chart")
            st.caption("주 수량은 종목별 단순 보유 단위이며 경제적 가치를 비교하는 지표는 아닙니다.")
        else:
            st.caption("표시할 보유수량이 없습니다.")
    for index, (currency, rows) in enumerate(sorted(values.items())[:2], start=1):
        with columns[index].container(border=True):
            st.caption(f"{currency} 평가금액 비중")
            rows = sorted(rows, key=lambda x: x["평가금액"], reverse=True)
            fig = go.Figure(go.Pie(labels=[r["종목"] for r in rows], values=[r["평가금액"] for r in rows], hole=.48, textinfo="percent"))
            fig.update_layout(height=300, margin=dict(l=10, r=10, t=5, b=10), showlegend=True,
                              paper_bgcolor="rgba(0,0,0,0)", legend=dict(orientation="h"))
            st.plotly_chart(fig, width="stretch", key=f"portfolio_value_chart_{currency}")
            st.caption(f"최근 제공 시세 기준 {currency} 평가금액의 종목별 비중입니다. 다른 통화와 합산하지 않습니다.")
    if len(values) > 2:
        st.caption("통화 종류가 3개 이상인 경우 그래프는 평가금액이 있는 앞 2개 통화만 표시하며, 합계 표에는 모든 통화를 유지합니다.")


def show_review_signals(evaluated):
    signals = evaluated.get("signals") or []
    for signal in signals:
        content = f"**{signal['label']}** · {signal['detail']}"
        if signal.get("level") in {"warning", "error", "danger"}:
            st.warning(content)
        else:
            st.info(content)
    if not signals and evaluated.get("error"):
        st.caption(evaluated["error"])
    if evaluated.get("warning"):
        st.caption(evaluated["warning"])


def render_portfolio_summary(positions, quotes, name_fn):
    """Called inside the price fragment so valuations refresh with quote cards."""
    if not positions:
        st.info("‘보유·수익률’에서 평균 매수가와 보유수량을 입력하면 내 수익률이 함께 갱신됩니다.")
        return
    st.subheader("내 보유 평가")
    evaluated = [evaluate_position(p, quotes.get(symbol, {})) for symbol, p in positions.items()]
    st.session_state.portfolio_evaluated = {row["symbol"]: row for row in evaluated}
    for total in total_by_currency(evaluated):
        currency = total["currency"]
        with st.container(border=True):
            st.caption(f"{currency} 보유 합계 · 시세 확인 {total['priced_count']}/{total['total_count']}종목")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("매수금액", money(total["cost_basis"], currency))
            c2.metric("평가금액", money(total["value"], currency))
            c3.metric("평가손익", money(total["pnl"], currency, signed=True))
            c4.metric("평가수익률", percentage(total["return_pct"]))
            if not total["complete"]:
                st.caption("일부 시세를 확인하지 못해 전체 평가금액·손익·수익률을 확정하지 않았습니다: " + ", ".join(total["missing_symbols"]))
            if not total.get("timestamp_complete", True):
                st.caption("일부 종목의 시세 기준 시각을 확인하지 못했습니다. 각 종목의 기준 시각을 함께 확인하세요.")
    render_portfolio_charts(evaluated, name_fn)
    rows = []
    for item in evaluated:
        rows.append({
            "종목": name_fn(item["symbol"]), "수량": item["quantity"],
            "평균 매수가": money(item["avg_cost"], item["currency"]),
            "최근 제공 시세": money(item.get("price"), item["currency"]),
            "평가손익": money(item.get("pnl"), item["currency"], signed=True),
            "평가수익률": percentage(item.get("return_pct")),
            "시세 기준": time_label(item.get("price_asof")),
            "내 기준": " / ".join(s["label"] for s in item.get("signals", [])) or ("확인 필요" if item.get("error") or item.get("warning") else "조건 미도달"),
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    flagged = [item for item in evaluated if item.get("signals")]
    if flagged:
        st.markdown("**내 기준에 도달한 종목**")
        for item in flagged:
            st.caption(f"{name_fn(item['symbol'])} · {percentage(item['return_pct'])} · {time_label(item.get('price_asof'))} 기준")
            show_review_signals(item)
    st.caption("평가손익은 입력한 평단과 최근 제공 시세로 계산합니다. 수수료·세금·배당·환율은 제외하며 통화별로 합산합니다. 기준 도달 표시는 해당 시세 시점의 관찰이며, 앱이 열린 동안 시세 갱신과 함께 확인합니다.")


def render_position_editor(symbol, kind, currency, quote, path: Path, save_callback=None):
    positions = st.session_state.positions
    saved = positions.get(symbol)
    if kind == "index" or symbol.startswith("^"):
        st.info("S&P 500 같은 지수 자체에는 보유수량을 입력하지 않습니다. 실제 보유한 ETF 티커(예: VOO, SPY)를 선택해 주세요.")
        return
    st.subheader("내 매수가와 보유수량")
    st.write("여러 번 매수했다면 현재 보유분의 평균 매수가를 입력하세요. 추가 매수·매도 후에는 평단과 현재 수량을 직접 수정합니다.")
    currency = currency or (saved or {}).get("currency") or ""
    if saved and saved.get("currency") != currency and currency:
        st.warning("저장된 매수 통화와 조회된 시세 통화가 다릅니다. 입력값을 확인한 뒤 수정해 주세요.")
    locked = bool(st.session_state.get("portfolio_load_error"))
    if locked:
        st.error(st.session_state.portfolio_load_error)
        st.caption("기존 보유 파일을 덮어쓰지 않도록 저장을 중지했습니다. portfolio.json을 백업하고 내용을 확인한 뒤 앱을 다시 실행해 주세요.")
    version = st.session_state.get(f"position_form_version_{symbol}", 0)
    with st.form(f"position_form_{symbol}_{version}"):
        c1, c2, c3 = st.columns([2, 2, 1])
        avg_cost = c1.number_input("평균 매수가 (1주당)", min_value=0.0,
                                   value=float((saved or {}).get("avg_cost", 0.0)), step=1.0, format="%.4f")
        quantity = c2.number_input("보유수량 (주)", min_value=0.0,
                                  value=float((saved or {}).get("quantity", 0.0)), step=1.0, format="%.6f")
        entered_currency = c3.text_input("매수 통화", value=currency, max_chars=6,
                                         disabled=bool(currency), help="국내 주식은 KRW, 미국 주식은 USD. 가격과 같은 통화로 입력합니다.")
        st.markdown("**내 수익률 검토 기준**")
        st.caption("초기 숫자는 기능을 설명하기 위한 예시입니다. 종목과 투자 계획에 맞게 직접 정하세요.")
        profit_col, loss_col = st.columns(2)
        profit = profit_col.number_input("이익 실현 검토 수익률 (%)", min_value=0.1, max_value=1000.0,
                                         value=float((saved or {}).get("profit_target_pct", 15.0)), step=0.5, format="%.2f")
        loss = loss_col.number_input("손실 점검 수익률 (%)", min_value=-99.99, max_value=-0.01,
                                     value=float((saved or {}).get("loss_review_pct", -7.0)), step=0.5, format="%.2f")
        buy_enabled = st.checkbox("추가매수 검토 기준도 사용", value=bool((saved or {}).get("enable_buy_review", False)))
        buy = st.number_input("추가매수 검토 수익률 (%)", min_value=-99.99, max_value=-0.01,
                              value=float((saved or {}).get("buy_review_pct", -10.0)), step=0.5, format="%.2f")
        st.caption("하락 기준은 내 평균 매수가 대비 수익률입니다. 추가매수 검토를 켜면 투자 근거·뉴스·여유 자금을 다시 점검할 조건으로 표시합니다. 손실 점검 조건과 동시에 표시될 수 있습니다.")
        submitted = st.form_submit_button("보유 정보와 기준 저장", type="primary", disabled=locked)
    if submitted:
        try:
            position = validate_position({"symbol": symbol, "avg_cost": avg_cost, "quantity": quantity,
                                          "currency": entered_currency, "profit_target_pct": profit,
                                          "loss_review_pct": loss, "buy_review_pct": buy,
                                          "enable_buy_review": buy_enabled, "kind": kind})
            updated = {**positions, symbol: position}
            error = save_callback(updated) if save_callback else save_portfolio(path, updated)
            if error:
                st.error(error)
            else:
                st.session_state.positions = updated
                st.session_state.position_notice = f"{symbol}의 보유 정보와 기준을 저장했습니다."
                st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    if saved:
        evaluated = evaluate_position(saved, quote)
        st.markdown("**이 종목의 현재 평가**")
        c1, c2, c3 = st.columns(3)
        c1.metric("매수금액", money(evaluated["cost_basis"], saved["currency"]))
        c2.metric("평가손익", money(evaluated.get("pnl"), saved["currency"], signed=True))
        c3.metric("평가수익률", percentage(evaluated.get("return_pct")))
        show_review_signals(evaluated)
        st.caption(f"시세 기준: {time_label(evaluated.get('price_asof'))}. 원화 환산과 수수료·세금은 포함하지 않습니다.")
        if st.button("이 종목 보유 기록 삭제", disabled=locked, key=f"delete_position_{symbol}"):
            updated = {s: p for s, p in positions.items() if s != symbol}
            error = save_callback(updated) if save_callback else save_portfolio(path, updated)
            if error:
                st.error(error)
            else:
                st.session_state.positions = updated
                st.session_state[f"position_form_version_{symbol}"] = version + 1
                st.session_state.position_notice = f"{symbol}의 보유 기록을 삭제했습니다."
                st.rerun()
    with st.expander("평가손익 계산 방식"):
        st.write("매수금액 = 평균 매수가 × 현재 보유수량")
        st.write("평가금액 = 최근 제공 시세 × 현재 보유수량")
        st.write("평가손익 = 평가금액 − 매수금액")
        st.write("평가수익률(%) = (최근 제공 시세 ÷ 평균 매수가 − 1) × 100")
        st.caption("분할·병합이 발생했으면 보유수량과 평균 매수가도 증권사 표시 기준에 맞춰 갱신하세요. 매도 후 실현손익을 누적하는 거래장부 기능은 포함하지 않습니다.")
