"""API-key-free structured market analysis for cloud deployments.

This is deliberately deterministic. It combines supplied quote/history/news/portfolio
signals into review directions; it is not a generative LLM and does not place orders.
"""
from __future__ import annotations

import math
import re
from typing import Any

_POSITIVE = (
    "상승", "강세", "호조", "개선", "증가", "성장", "회복", "돌파", "최고", "수주", "흑자", "확대",
    "beat", "beats", "growth", "rally", "surge", "rise", "rises", "gain", "gains", "record", "strong",
)
_NEGATIVE = (
    "하락", "약세", "부진", "감소", "둔화", "우려", "손실", "적자", "급락", "리스크", "규제", "충격",
    "fall", "falls", "drop", "drops", "slump", "weak", "loss", "risk", "cut", "concern", "warning",
)

_CHANNELS = {
    "금리·중앙은행": (
        "금리·할인율", "해외→국내",
        "해외 금리와 중앙은행 기대는 달러 흐름, 성장주 할인율, 외국인 자금 흐름을 통해 국내 증시에 전달될 수 있습니다.",
    ),
    "환율·달러": (
        "달러·원화", "해외→국내",
        "달러 방향은 원화 환율과 외국인 수급, 수입비용·수출기업 원화 환산 실적에 영향을 줄 수 있습니다.",
    ),
    "유가·에너지": (
        "유가·수입물가", "해외→국내",
        "국제유가는 에너지 수입 의존도가 높은 한국의 물가와 기업 비용, 무역수지에 영향을 줄 수 있습니다.",
    ),
    "중국": (
        "중국 경기·수요", "해외→국내",
        "중국 경기와 수요 변화는 한국 수출·소재·산업재와 아시아 위험선호를 통해 국내 시장에 연결될 수 있습니다.",
    ),
    "AI·반도체": (
        "글로벌 AI·반도체 수요", "상호",
        "글로벌 AI 투자와 반도체 수요는 한국 메모리·장비 공급망에 영향을 주고, 한국의 생산·수출 흐름도 글로벌 공급 상황의 참고 신호가 될 수 있습니다.",
    ),
    "관세·무역": (
        "무역·관세", "상호",
        "관세와 무역정책은 한국 수출기업의 수요·비용과 글로벌 공급망 재편을 통해 국내외 시장을 동시에 연결할 수 있습니다.",
    ),
    "한국 수출·산업": (
        "한국 수출·공급망", "국내→해외",
        "한국의 반도체·자동차 등 수출 흐름은 글로벌 제조업과 공급망 수요를 확인하는 참고 지표가 될 수 있습니다.",
    ),
}


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _sentiment(items: list[dict]) -> tuple[int, list[str]]:
    score = 0
    ids: list[str] = []
    for item in items[:6]:
        title = str(item.get("title") or "").casefold()
        pos = sum(1 for term in _POSITIVE if term in title)
        neg = sum(1 for term in _NEGATIVE if term in title)
        if pos > neg:
            score += 1
        elif neg > pos:
            score -= 1
        if item.get("id"):
            ids.append(str(item["id"]))
    return score, ids[:3]


def _stock_review(row: dict) -> dict:
    symbol = str(row.get("symbol") or "")
    quote = row.get("quote") or {}
    analysis = row.get("analysis") or {}
    position = row.get("position") or {}
    news = (row.get("news") or {}).get("items") or []
    score = 0.0
    reasons: list[str] = []
    counter: list[str] = []
    evidence = 0

    change = _num(quote.get("change_pct"))
    if change is not None:
        evidence += 1
        if change >= 2:
            score += 1.25; reasons.append(f"전 거래일 대비 {change:+.2f}%로 단기 가격 흐름이 강합니다.")
        elif change >= .5:
            score += .5; reasons.append(f"전 거래일 대비 {change:+.2f}% 상승했습니다.")
        elif change <= -2:
            score -= 1.25; reasons.append(f"전 거래일 대비 {change:+.2f}%로 단기 가격 흐름이 약합니다.")
        elif change <= -.5:
            score -= .5; reasons.append(f"전 거래일 대비 {change:+.2f}% 하락했습니다.")
        else:
            counter.append(f"전 거래일 등락은 {change:+.2f}%로 방향성이 크지 않습니다.")

    r20 = _num(analysis.get("return_20d_pct"))
    if r20 is not None:
        evidence += 1
        if r20 >= 7:
            score += 1; reasons.append(f"최근 20거래일 가격 변화율이 {r20:+.2f}%입니다.")
        elif r20 <= -7:
            score -= 1; reasons.append(f"최근 20거래일 가격 변화율이 {r20:+.2f}%입니다.")
        else:
            counter.append(f"최근 20거래일 변화율은 {r20:+.2f}%로 중간 범위입니다.")

    sma20, sma60 = _num(analysis.get("sma20")), _num(analysis.get("sma60"))
    if sma20 is not None and sma60 is not None:
        evidence += 1
        if sma20 > sma60:
            score += .75; reasons.append("20거래일 이동평균이 60거래일 이동평균보다 높습니다.")
        elif sma20 < sma60:
            score -= .75; reasons.append("20거래일 이동평균이 60거래일 이동평균보다 낮습니다.")

    rsi = _num(analysis.get("rsi14"))
    if rsi is not None:
        evidence += 1
        if rsi >= 72:
            score -= .25; counter.append(f"RSI가 {rsi:.1f}로 최근 상승이 많이 누적된 구간입니다.")
        elif rsi <= 28:
            counter.append(f"RSI가 {rsi:.1f}로 최근 하락이 많이 누적돼 변동성이 커질 수 있습니다.")

    news_score, news_ids = _sentiment(news)
    if news:
        evidence += 1
        if news_score >= 2:
            score += .75; reasons.append("최근 관련 헤드라인에서 긍정 표현이 상대적으로 더 많이 관찰됩니다.")
        elif news_score <= -2:
            score -= .75; reasons.append("최근 관련 헤드라인에서 부정·경계 표현이 상대적으로 더 많이 관찰됩니다.")
        else:
            counter.append("최근 관련 헤드라인의 방향이 혼재되어 있습니다.")

    signals = position.get("signals") or []
    signal_codes = {x.get("code") for x in signals if isinstance(x, dict)}
    ret = _num(position.get("return_pct"))
    if ret is not None:
        evidence += 1
        reasons.append(f"입력한 평균 매수가 대비 평가수익률은 {ret:+.2f}%입니다.")
    if "profit_review" in signal_codes:
        counter.append("사용자가 설정한 이익 실현·비중 조절 검토 기준에 도달했습니다.")
    if "loss_review" in signal_codes:
        score -= .5; counter.append("사용자가 설정한 손실 점검 기준에 도달했습니다.")
    if "buy_review" in signal_codes:
        counter.append("추가매수 검토 기준에도 도달했으므로 가격 하락 원인을 함께 확인해야 합니다.")

    if "profit_review" in signal_codes and score < 2:
        stance = "매도 검토"
    elif score >= 2.0:
        stance = "매수 검토"
    elif score <= -2.0:
        stance = "매도 검토"
    elif position:
        stance = "보유 검토"
    else:
        stance = "관망"

    magnitude = abs(score)
    confidence = "높음" if evidence >= 4 and magnitude >= 2.75 else "중간" if evidence >= 3 and magnitude >= 1.25 else "낮음"
    if not reasons:
        reasons = ["가격·기술지표·뉴스에서 한 방향의 근거가 충분히 모이지 않았습니다."]
    if not counter:
        counter = ["헤드라인과 가격의 동시 움직임만으로 원인을 확정할 수 없습니다."]

    return {
        "symbol": symbol,
        "stance": stance,
        "confidence": confidence,
        "summary": f"현재 자료를 합산한 참고 점수는 {score:+.2f}이며, {stance} 방향으로 추가 확인할 항목이 있습니다.",
        "reasons": reasons[:4],
        "counterpoints": counter[:3],
        "news_ids": news_ids,
    }


def _keyword_rows(bucket: dict, limit: int = 4) -> list[dict]:
    rows = []
    items_by_id = {x.get("id"): x for x in (bucket.get("items") or []) if isinstance(x, dict)}
    for item in (bucket.get("keywords") or [])[:limit]:
        ids = [x for x in (item.get("item_ids") or []) if x in items_by_id]
        rows.append({
            "keyword": item.get("keyword") or "키워드",
            "why": f"최근 헤드라인에서 {int(item.get('count') or 0)}건 언급된 주제입니다. 빈도는 중요도나 호재·악재를 뜻하지 않습니다.",
            "news_ids": ids[:3],
        })
    return rows


def _cross_impact(market: dict) -> dict:
    domestic = {x.get("keyword") for x in (market.get("domestic") or {}).get("keywords", [])}
    overseas = {x.get("keyword") for x in (market.get("overseas") or {}).get("keywords", [])}
    all_keys = domestic | overseas
    channels = []
    for keyword, (channel, direction, impact) in _CHANNELS.items():
        if keyword not in all_keys:
            continue
        source = (market.get("overseas") if keyword in overseas else market.get("domestic")) or {}
        matching = next((x for x in source.get("keywords", []) if x.get("keyword") == keyword), {})
        channels.append({
            "channel": channel, "direction": direction, "impact": impact,
            "news_ids": (matching.get("item_ids") or [])[:3],
        })
    overseas_text = next((x["impact"] for x in channels if x["direction"] in {"해외→국내", "상호"}), None)
    korea_text = next((x["impact"] for x in channels if x["direction"] in {"국내→해외", "상호"}), None)
    if channels:
        net = "오늘 헤드라인에서 국내외 시장을 연결할 수 있는 경로로 " + ", ".join(x["channel"] for x in channels[:3]) + "가 관찰됩니다. 이는 영향 가능성을 정리한 것이며 인과관계를 확정한 것은 아닙니다."
    else:
        net = "현재 수집된 헤드라인만으로 국내외 시장 사이의 뚜렷한 연결 경로를 확인하기 어렵습니다."
    return {
        "overseas_to_korea": overseas_text or "현재 해외 헤드라인만으로 국내 시장에 대한 뚜렷한 전달 경로를 확인하기 어렵습니다.",
        "korea_to_overseas": korea_text or "현재 국내 헤드라인만으로 해외 시장에 대한 뚜렷한 전달 경로를 확인하기 어렵습니다.",
        "net_effect": net,
        "channels": channels[:5],
    }


def generate_dashboard_brief(snapshot: dict) -> tuple[dict | None, str | None]:
    if not isinstance(snapshot, dict):
        return None, "분석 자료 형식이 올바르지 않습니다."
    market = snapshot.get("market") or {}
    domestic_rows = _keyword_rows(market.get("domestic") or {})
    overseas_rows = _keyword_rows(market.get("overseas") or {})
    domestic_names = ", ".join(x["keyword"] for x in domestic_rows[:3]) or "뚜렷한 상위 키워드 없음"
    overseas_names = ", ".join(x["keyword"] for x in overseas_rows[:3]) or "뚜렷한 상위 키워드 없음"
    recommendations = [_stock_review(row) for row in (snapshot.get("stocks") or []) if isinstance(row, dict)]
    result = {
        "market_summary": f"국내에서는 {domestic_names}, 해외에서는 {overseas_names}가 최근 헤드라인에서 많이 언급됐습니다. 키워드 빈도와 가격 움직임은 참고 자료이며 인과나 미래 방향을 확정하지 않습니다.",
        "domestic_summary": f"국내 헤드라인의 상위 키워드는 {domestic_names}입니다. 원문과 실제 지표를 함께 확인해 해석해야 합니다.",
        "overseas_summary": f"해외 헤드라인의 상위 키워드는 {overseas_names}입니다. 금리·달러·위험선호 등 국내로 전달될 수 있는 경로가 있는지 별도로 확인합니다.",
        "domestic_keywords": domestic_rows,
        "overseas_keywords": overseas_rows,
        "cross_market_impact": _cross_impact(market),
        "recommendations": recommendations,
    }
    warning = "API 키 없는 클라우드 기본 분석은 규칙 기반 자동 분석입니다. 생성형 LLM의 해석이 아니며, 실제 매매 결정은 원자료와 개인 계획을 함께 확인하세요."
    return result, warning


def explain_snapshot(snapshot: dict, question: str = "") -> tuple[str, str | None]:
    if not isinstance(snapshot, dict):
        return "", "분석 자료 형식이 올바르지 않습니다."
    row = {
        "symbol": snapshot.get("symbol"), "quote": snapshot.get("quote"),
        "analysis": snapshot.get("analysis"), "position": snapshot.get("position"),
        "news": snapshot.get("news"),
    }
    review = _stock_review(row)
    lines = [
        f"### {review['stance']} · 확신도 {review['confidence']}",
        review["summary"],
        "",
        "**근거**",
    ]
    lines.extend(f"- {x}" for x in review["reasons"])
    lines.extend(["", "**반대 가능성·확인할 점**"])
    lines.extend(f"- {x}" for x in review["counterpoints"])
    news = (snapshot.get("news") or {}).get("items") or []
    if news:
        lines.extend(["", "**관련 헤드라인**"])
        for item in news[:4]:
            lines.append(f"- [{item.get('id') or '뉴스'}] {item.get('title') or ''}")
    if question.strip():
        lines.extend(["", f"질문: {question.strip()}", "현재 기본 분석 엔진은 위 데이터 범위의 정형 분석만 제공하며 자유로운 생성형 답변은 제공하지 않습니다."])
    return "\n".join(lines), "API 키 없는 클라우드 기본 분석은 생성형 AI가 아닌 규칙 기반 자동 분석입니다."
