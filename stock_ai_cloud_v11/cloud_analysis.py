"""API-key-free structured market analysis for cloud deployments.

This is deterministic and scenario based. It combines supplied quote/history/news/
portfolio signals into review directions and maps high-frequency market topics to
potential beneficiary/risk sectors. It is not a generative LLM and does not place orders.
"""
from __future__ import annotations

import math
from typing import Any

_POSITIVE = (
    "상승", "강세", "호조", "개선", "증가", "성장", "회복", "돌파", "최고", "수주", "흑자", "확대",
    "beat", "beats", "growth", "rally", "surge", "rise", "rises", "gain", "gains", "record", "strong",
)
_NEGATIVE = (
    "하락", "약세", "부진", "감소", "둔화", "우려", "손실", "적자", "급락", "리스크", "규제", "충격",
    "fall", "falls", "drop", "drops", "slump", "weak", "loss", "risk", "concern", "warning",
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

# Topic-direction playbook. "up" and "down" mean scenario A/B, not market good/bad.
_SECTOR_RULES = {
    "금리·중앙은행": {
        "up_terms": ("금리 인하", "금리인하", "인하 기대", "완화", "비둘기파", "rate cut", "cuts rates", "dovish", "easing"),
        "down_terms": ("금리 인상", "금리인상", "긴축", "매파", "higher for longer", "rate hike", "hawkish", "tightening"),
        "up_label": "금리 인하·완화 기대",
        "up_benefit": ("IT·성장주", "리츠·부동산", "경기소비재"),
        "up_risk": ("은행 예대마진 민감주",),
        "down_label": "금리 인상·긴축 우려",
        "down_benefit": ("은행·보험",),
        "down_risk": ("IT·성장주", "리츠·부동산", "고부채 경기소비재"),
        "why": "금리 변화는 할인율과 자금조달비용을 통해 성장주·부동산·금융 업종의 상대 매력에 영향을 줄 수 있습니다.",
    },
    "환율·달러": {
        "up_terms": ("달러 강세", "원화 약세", "환율 상승", "dollar rises", "strong dollar", "won weak", "원화값 하락"),
        "down_terms": ("달러 약세", "원화 강세", "환율 하락", "dollar falls", "weak dollar", "won strong", "원화값 상승"),
        "up_label": "달러 강세·원화 약세",
        "up_benefit": ("반도체·자동차 등 수출주", "조선·기계 수출주"),
        "up_risk": ("항공", "원자재 수입 비중이 큰 내수·유통"),
        "down_label": "달러 약세·원화 강세",
        "down_benefit": ("항공", "유통·내수", "원자재 수입형 제조"),
        "down_risk": ("원화 환산 효과가 큰 수출주",),
        "why": "환율은 수출기업의 원화 환산 실적과 수입 원가, 외국인 수급 경로에 동시에 작용할 수 있습니다.",
    },
    "물가·인플레이션": {
        "up_terms": ("물가 둔화", "인플레이션 둔화", "cpi cool", "inflation cool", "disinflation", "물가 안정"),
        "down_terms": ("물가 상승", "인플레이션 가속", "cpi hot", "inflation rises", "sticky inflation", "물가 압력"),
        "up_label": "물가 둔화·안정",
        "up_benefit": ("IT·성장주", "경기소비재", "리츠·부동산"),
        "up_risk": ("인플레이션 헤지 성격 자산",),
        "down_label": "물가 재상승·고착",
        "down_benefit": ("에너지·원자재 일부", "가격전가력이 높은 방어주"),
        "down_risk": ("IT·성장주", "경기소비재", "리츠·부동산"),
        "why": "물가 경로는 향후 금리 기대와 소비여력, 기업 마진 전망에 영향을 줄 수 있습니다.",
    },
    "AI·반도체": {
        "up_terms": ("수요 증가", "수요 회복", "투자 확대", "수주", "증설", "호실적", "record", "strong demand", "AI demand", "capex", "beat", "growth"),
        "down_terms": ("수요 둔화", "공급과잉", "수출 제한", "규제", "감산", "부진", "weak demand", "export restriction", "ban", "slump", "miss"),
        "up_label": "AI·반도체 수요/투자 확대",
        "up_benefit": ("반도체", "반도체 장비", "데이터센터", "전력기기·전력인프라"),
        "up_risk": ("밸류에이션 부담이 큰 일부 고평가 성장주",),
        "down_label": "AI·반도체 수요 둔화/규제",
        "down_benefit": ("통신·필수소비재 등 방어주",),
        "down_risk": ("반도체", "반도체 장비", "데이터센터 관련주"),
        "why": "AI 투자와 메모리·GPU 수요는 반도체 공급망과 데이터센터 전력 인프라에 연쇄적으로 영향을 줄 수 있습니다.",
    },
    "증시·주가지수": {
        "up_terms": ("상승", "강세", "랠리", "사상 최고", "rally", "surge", "record high", "stocks rise", "gains"),
        "down_terms": ("하락", "약세", "급락", "조정", "selloff", "stocks fall", "slump", "drops"),
        "up_label": "위험선호·증시 강세",
        "up_benefit": ("IT·성장주", "증권", "경기소비재"),
        "up_risk": ("일부 방어주 상대수익률",),
        "down_label": "위험회피·증시 약세",
        "down_benefit": ("필수소비재", "통신", "유틸리티 등 방어주"),
        "down_risk": ("고베타 성장주", "증권", "경기민감주"),
        "why": "시장 위험선호 변화는 고베타 성장주와 방어주의 상대 성과에 영향을 줄 수 있습니다.",
    },
    "관세·무역": {
        "up_terms": ("관세 완화", "관세 철회", "협상 타결", "무역 합의", "tariff relief", "deal", "agreement", "easing tariffs"),
        "down_terms": ("관세 인상", "관세 부과", "무역전쟁", "수출 규제", "tariff hike", "new tariffs", "trade war", "export controls", "sanctions"),
        "up_label": "무역 긴장 완화",
        "up_benefit": ("반도체·자동차 등 수출주", "산업재", "물류"),
        "up_risk": ("무역갈등 수혜 대체재 일부",),
        "down_label": "관세·무역갈등 확대",
        "down_benefit": ("방산", "현지 대체생산·국산화 관련주"),
        "down_risk": ("수출주", "산업재", "글로벌 공급망 민감주"),
        "why": "관세와 수출규제는 최종 수요와 공급망 위치, 원가 구조를 바꿀 수 있습니다.",
    },
    "중국": {
        "up_terms": ("부양", "경기 회복", "소비 회복", "stimulus", "recovery", "growth accelerates", "support package"),
        "down_terms": ("경기 둔화", "침체", "부동산 위기", "소비 부진", "slowdown", "property crisis", "weak demand", "deflation"),
        "up_label": "중국 경기 부양·회복",
        "up_benefit": ("화학·소재", "산업재", "반도체", "중국 소비 노출주"),
        "up_risk": ("중국 경기 방어형 포지션",),
        "down_label": "중국 경기 둔화",
        "down_benefit": ("통신·필수소비재 등 방어주",),
        "down_risk": ("화학·소재", "산업재", "중국 소비 노출주"),
        "why": "중국 수요는 한국의 소재·산업재·반도체 수출과 아시아 위험선호에 영향을 줄 수 있습니다.",
    },
    "유가·에너지": {
        "up_terms": ("유가 상승", "유가 급등", "원유 상승", "oil rises", "oil surges", "higher oil", "supply cut"),
        "down_terms": ("유가 하락", "원유 하락", "oil falls", "oil drops", "lower oil", "supply increase"),
        "up_label": "유가 상승",
        "up_benefit": ("정유·에너지 생산", "에너지 장비"),
        "up_risk": ("항공", "운송", "화학·원가민감 제조"),
        "down_label": "유가 하락",
        "down_benefit": ("항공", "운송", "화학·원가민감 제조"),
        "down_risk": ("정유·에너지 생산",),
        "why": "유가 변화는 에너지 기업의 판매단가와 운송·제조업의 연료·원재료 비용을 반대 방향으로 움직일 수 있습니다.",
    },
    "채권·국채": {
        "up_terms": ("금리 하락", "국채금리 하락", "yield falls", "yields fall", "bond rally"),
        "down_terms": ("금리 상승", "국채금리 상승", "yield rises", "yields rise", "bond selloff"),
        "up_label": "국채금리 하락",
        "up_benefit": ("IT·성장주", "리츠·부동산", "장기채"),
        "up_risk": ("은행 예대마진 민감주",),
        "down_label": "국채금리 상승",
        "down_benefit": ("은행·보험 일부",),
        "down_risk": ("IT·성장주", "리츠·부동산", "장기채"),
        "why": "국채금리는 주식 할인율과 대출·조달금리의 기준 역할을 하므로 성장주와 금융·부동산에 파급될 수 있습니다.",
    },
    "기업실적": {
        "up_terms": ("호실적", "실적 개선", "어닝 서프라이즈", "beat", "beats", "record profit", "raises guidance", "strong earnings"),
        "down_terms": ("실적 부진", "어닝 쇼크", "적자", "miss", "misses", "cuts guidance", "weak earnings", "profit warning"),
        "up_label": "실적 상향·호조",
        "up_benefit": ("실적 개선이 집중된 해당 업종", "증권·시장 거래활동 관련주"),
        "up_risk": ("실적 기대가 과도하게 선반영된 업종",),
        "down_label": "실적 하향·부진",
        "down_benefit": ("필수소비재·통신 등 방어주",),
        "down_risk": ("실적 하향이 집중된 해당 업종",),
        "why": "실적 뉴스는 업종 전체보다 실제 발표 기업과 동종업계에 더 직접적인 영향을 줄 수 있어 원문 확인이 중요합니다.",
    },
    "지정학": {
        "up_terms": ("휴전", "협상", "긴장 완화", "ceasefire", "peace talks", "de-escalation"),
        "down_terms": ("공격", "전쟁", "충돌", "제재", "미사일", "war", "attack", "escalation", "sanctions", "missile"),
        "up_label": "지정학적 긴장 완화",
        "up_benefit": ("항공·여행", "경기민감주", "물류"),
        "up_risk": ("방산·에너지 위험프리미엄",),
        "down_label": "지정학적 긴장 고조",
        "down_benefit": ("방산", "에너지", "금 등 안전자산 관련"),
        "down_risk": ("항공·여행", "운송", "경기민감주"),
        "why": "지정학적 긴장은 에너지·운송비와 위험회피 심리를 통해 업종별 상대 성과를 바꿀 수 있습니다.",
    },
    "한국 수출·산업": {
        "up_terms": ("수출 증가", "수출 호조", "수출 회복", "export growth", "exports rise", "record exports"),
        "down_terms": ("수출 감소", "수출 둔화", "수출 부진", "exports fall", "weak exports", "export slowdown"),
        "up_label": "한국 수출 회복·증가",
        "up_benefit": ("반도체", "자동차", "조선·기계", "산업재"),
        "up_risk": ("수출 경쟁 심화에 노출된 일부 내수 대체 업종",),
        "down_label": "한국 수출 둔화",
        "down_benefit": ("통신·필수소비재 등 내수 방어주",),
        "down_risk": ("반도체", "자동차", "조선·기계", "산업재"),
        "why": "한국 수출은 제조업 가동률과 대형 수출기업 실적 기대에 직접 연결되는 경우가 많습니다.",
    },
    "자동차·배터리": {
        "up_terms": ("판매 증가", "수요 증가", "수주", "보조금 확대", "sales rise", "strong demand", "orders", "subsidy"),
        "down_terms": ("판매 감소", "수요 둔화", "리콜", "보조금 축소", "sales fall", "weak demand", "recall", "subsidy cut"),
        "up_label": "자동차·배터리 수요 개선",
        "up_benefit": ("자동차", "2차전지", "자동차부품"),
        "up_risk": ("가격경쟁이 심한 저마진 업체",),
        "down_label": "자동차·배터리 수요 둔화",
        "down_benefit": ("필수소비재·통신 등 방어주",),
        "down_risk": ("자동차", "2차전지", "자동차부품"),
        "why": "판매량·보조금·원재료 가격 변화는 완성차와 배터리 공급망의 가동률 및 마진에 영향을 줄 수 있습니다.",
    },
}


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _sector_values(value: Any) -> tuple[str, ...]:
    """Normalize sector rule values so a single string is never split into characters."""
    if value is None:
        return ()
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if isinstance(value, (list, tuple, set)):
        result = []
        for item in value:
            text = str(item or "").strip()
            if text:
                result.append(text)
        return tuple(result)
    text = str(value).strip()
    return (text,) if text else ()


def _sentiment(items: list[dict]) -> tuple[int, list[str]]:
    score = 0
    ids: list[str] = []
    for item in items[:8]:
        title = str(item.get("title") or "").casefold()
        pos = sum(1 for term in _POSITIVE if term in title)
        neg = sum(1 for term in _NEGATIVE if term in title)
        if pos > neg:
            score += 1
        elif neg > pos:
            score -= 1
        if item.get("id"):
            ids.append(str(item["id"]))
    return score, ids[:4]


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

    if score >= 1.25:
        direction = "상승 우세"
    elif score <= -1.25:
        direction = "하락 우세"
    else:
        direction = "혼조·중립"

    return {
        "symbol": symbol,
        "stance": stance,
        "direction": direction,
        "confidence": confidence,
        "score": round(score, 2),
        "summary": f"현재 자료를 합산한 참고 점수는 {score:+.2f}이며, {stance} 방향으로 추가 확인할 항목이 있습니다.",
        "reasons": reasons[:4],
        "counterpoints": counter[:3],
        "news_ids": news_ids,
    }


def _topic_record(bucket: dict, topic_name: str) -> dict:
    for row in (bucket.get("topics") or []):
        if row.get("topic") == topic_name:
            return row
    for row in (bucket.get("keywords") or []):
        if row.get("keyword") == topic_name:
            return {
                "topic": topic_name,
                "count": row.get("count") or 0,
                "coverage_pct": row.get("coverage_pct") or 0,
                "item_ids": row.get("item_ids") or [],
            }
    return {}


def _sector_impact_for_topic(bucket: dict, region: str, topic_name: str) -> dict | None:
    rule = _SECTOR_RULES.get(topic_name)
    topic = _topic_record(bucket, topic_name)
    if not rule or not topic:
        return None
    item_by_id = {x.get("id"): x for x in (bucket.get("items") or []) if isinstance(x, dict)}
    selected = [item_by_id[x] for x in (topic.get("item_ids") or []) if x in item_by_id]
    if not selected:
        selected = [x for x in (bucket.get("items") or []) if topic_name in str(x.get("topic") or "")][:8]

    up_score = 0
    down_score = 0
    evidence_ids: list[str] = []
    for item in selected[:8]:
        text = str(item.get("title") or "").casefold()
        up = sum(1 for term in rule["up_terms"] if term.casefold() in text)
        down = sum(1 for term in rule["down_terms"] if term.casefold() in text)
        if up > down:
            up_score += 1
        elif down > up:
            down_score += 1
        if (up or down) and item.get("id"):
            evidence_ids.append(str(item["id"]))

    directional = up_score + down_score
    if directional == 0:
        signal = "방향 불명확"
        beneficiaries: tuple[str, ...] = ()
        risks: tuple[str, ...] = ()
        confidence = "낮음"
        basis = "토픽 언급은 많지만 수혜 방향을 가를 만한 표현이 충분하지 않습니다."
    else:
        diff = abs(up_score - down_score)
        ratio = diff / directional
        if up_score > down_score:
            signal = rule["up_label"]
            beneficiaries = rule["up_benefit"]
            risks = rule["up_risk"]
        elif down_score > up_score:
            signal = rule["down_label"]
            beneficiaries = rule["down_benefit"]
            risks = rule["down_risk"]
        else:
            signal = "상반된 방향 혼재"
            beneficiaries = ()
            risks = ()
        confidence = "높음" if directional >= 6 and ratio >= .50 else "중간" if directional >= 3 and ratio >= .34 else "낮음"
        basis = f"대표 헤드라인 {min(len(selected), 8)}건 중 방향성 표현은 시나리오 A {up_score}건, 시나리오 B {down_score}건으로 집계됐습니다."

    return {
        "region": region,
        "topic": topic_name,
        "topic_count": int(topic.get("count") or 0),
        "coverage_pct": float(topic.get("coverage_pct") or 0),
        "signal": signal,
        "confidence": confidence,
        "beneficiary_sectors": list(_sector_values(beneficiaries)),
        "risk_sectors": list(_sector_values(risks)),
        "rationale": rule["why"],
        "basis": basis,
        "news_ids": evidence_ids[:4] or list(topic.get("item_ids") or [])[:4],
    }


def _sector_impacts(market: dict, limit_per_region: int = 5) -> list[dict]:
    rows: list[dict] = []
    for region_key, region_label in (("domestic", "국내"), ("overseas", "해외")):
        bucket = market.get(region_key) or {}
        names = [x.get("topic") for x in (bucket.get("topics") or [])]
        if not names:
            names = [x.get("keyword") for x in (bucket.get("keywords") or [])]
        added = 0
        for name in names:
            if not name or name not in _SECTOR_RULES:
                continue
            impact = _sector_impact_for_topic(bucket, region_label, name)
            if impact:
                rows.append(impact)
                added += 1
            if added >= limit_per_region:
                break
    rows.sort(key=lambda x: (-x["topic_count"], x["region"], x["topic"]))
    return rows


def _impact_lookup(impacts: list[dict], region: str) -> dict[str, dict]:
    return {x["topic"]: x for x in impacts if x.get("region") == region}


def _keyword_rows(bucket: dict, impacts: dict[str, dict], limit: int = 5) -> list[dict]:
    rows = []
    items_by_id = {x.get("id"): x for x in (bucket.get("items") or []) if isinstance(x, dict)}
    source_rows = bucket.get("topics") or bucket.get("keywords") or []
    for item in source_rows[:limit]:
        keyword = item.get("topic") or item.get("keyword") or "키워드"
        ids = [x for x in (item.get("item_ids") or []) if x in items_by_id]
        count = int(item.get("count") or 0)
        coverage = float(item.get("coverage_pct") or 0)
        why = f"분석 표본에서 {count}건({coverage:.1f}%) 언급된 핵심 토픽입니다."
        impact = impacts.get(keyword)
        if impact:
            why += f" 방향: {impact['signal']} · 확신도 {impact['confidence']}."
            if impact.get("beneficiary_sectors"):
                why += " 수혜 가능 섹터 후보: " + ", ".join(impact["beneficiary_sectors"][:4]) + "."
            if impact.get("risk_sectors"):
                why += " 부담 가능 섹터: " + ", ".join(impact["risk_sectors"][:3]) + "."
        why += " 헤드라인 기반 시나리오이며 실제 수익을 보장하지 않습니다."
        rows.append({
            "keyword": keyword,
            "why": why,
            "news_ids": (impact.get("news_ids") if impact else ids)[:4],
        })
    return rows


def _cross_impact(market: dict, sector_impacts: list[dict]) -> dict:
    domestic = {x.get("keyword") for x in (market.get("domestic") or {}).get("keywords", [])}
    overseas = {x.get("keyword") for x in (market.get("overseas") or {}).get("keywords", [])}
    all_keys = domestic | overseas
    best_sector = {}
    for row in sector_impacts:
        old = best_sector.get(row["topic"])
        if old is None or row["topic_count"] > old["topic_count"]:
            best_sector[row["topic"]] = row

    channels = []
    for keyword, (channel, direction, impact) in _CHANNELS.items():
        if keyword not in all_keys:
            continue
        source = (market.get("overseas") if keyword in overseas else market.get("domestic")) or {}
        matching = next((x for x in source.get("keywords", []) if x.get("keyword") == keyword), {})
        sector = best_sector.get(keyword)
        sector_text = ""
        if sector and sector.get("beneficiary_sectors"):
            sector_text = " 수혜 가능 섹터 후보: " + ", ".join(sector["beneficiary_sectors"][:3]) + "."
        if sector and sector.get("risk_sectors"):
            sector_text += " 부담 가능 섹터: " + ", ".join(sector["risk_sectors"][:2]) + "."
        channels.append({
            "channel": channel,
            "direction": direction,
            "impact": impact + sector_text,
            "news_ids": (sector.get("news_ids") if sector else matching.get("item_ids") or [])[:4],
        })

    overseas_text = next((x["impact"] for x in channels if x["direction"] in {"해외→국내", "상호"}), None)
    korea_text = next((x["impact"] for x in channels if x["direction"] in {"국내→해외", "상호"}), None)
    benefit_candidates = []
    for row in sector_impacts:
        if row.get("confidence") == "낮음":
            continue
        for sector in row.get("beneficiary_sectors") or []:
            if sector not in benefit_candidates:
                benefit_candidates.append(sector)
    if channels:
        net = "오늘 헤드라인에서 국내외 시장을 연결할 수 있는 경로로 " + ", ".join(x["channel"] for x in channels[:3]) + "가 관찰됩니다."
        if benefit_candidates:
            net += " 현재 토픽 방향을 기준으로 수혜 가능성이 상대적으로 거론될 수 있는 섹터 후보는 " + ", ".join(benefit_candidates[:5]) + "입니다."
        net += " 이는 약 100건 규모의 헤드라인 표본을 이용한 시나리오 분석이며 인과나 수익을 확정하지 않습니다."
    else:
        net = "현재 수집된 헤드라인만으로 국내외 시장 사이의 뚜렷한 연결 경로를 확인하기 어렵습니다."
    return {
        "overseas_to_korea": overseas_text or "현재 해외 헤드라인만으로 국내 시장에 대한 뚜렷한 전달 경로를 확인하기 어렵습니다.",
        "korea_to_overseas": korea_text or "현재 국내 헤드라인만으로 해외 시장에 대한 뚜렷한 전달 경로를 확인하기 어렵습니다.",
        "net_effect": net,
        "channels": channels[:6],
    }



# Canonical exposure groups used to connect market issue sectors with a selected
# stock/ETF. These are deliberately broad: they estimate exposure, not causal
# impact or expected return.
_FUND_SECTOR_GROUPS = {
    "technology": ("technology", "growth"),
    "communication_services": ("communication", "growth"),
    "consumer_cyclical": ("consumer_cyclical", "growth"),
    "consumer_defensive": ("consumer_defensive",),
    "financial_services": ("financials",),
    "healthcare": ("healthcare",),
    "industrials": ("industrials",),
    "energy": ("energy",),
    "utilities": ("utilities",),
    "realestate": ("real_estate",),
    "real_estate": ("real_estate",),
    "basic_materials": ("materials",),
}


def _add_weight(weights: dict[str, float], group: str, value: float) -> None:
    try:
        number = max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return
    if number > weights.get(group, 0.0):
        weights[group] = number


def _instrument_exposure(snapshot: dict) -> tuple[dict[str, float], list[str]]:
    """Return broad issue-exposure weights plus human-readable basis notes."""
    weights: dict[str, float] = {}
    basis: list[str] = []
    kind = str(snapshot.get("kind") or "stock").lower()
    name = str(snapshot.get("name") or "")
    symbol = str(snapshot.get("symbol") or "").upper()
    sector = str(snapshot.get("sector") or "")
    industry = str(snapshot.get("industry") or "")
    text = " ".join([name, symbol, sector, industry]).casefold()

    fund_sectors = snapshot.get("fund_sectors") or {}
    if isinstance(fund_sectors, dict) and fund_sectors:
        ranked = []
        for raw_key, raw_weight in fund_sectors.items():
            try:
                weight = max(0.0, min(1.0, float(raw_weight)))
            except (TypeError, ValueError):
                continue
            key = str(raw_key).lower().replace(" ", "_").replace("-", "_")
            for group in _FUND_SECTOR_GROUPS.get(key, ()):
                _add_weight(weights, group, weight)
            ranked.append((key, weight))
        ranked.sort(key=lambda x: x[1], reverse=True)
        if ranked:
            basis.append("ETF/지수 대체 ETF의 실제 섹터 비중을 이슈 노출도에 반영했습니다.")

    # Stocks and ETFs without sector weights use provider sector/industry text.
    if "technology" in text or "software" in text or "internet" in text or "정보기술" in text:
        _add_weight(weights, "technology", 1.0)
        _add_weight(weights, "growth", 0.85)
    if any(term in text for term in ("semiconductor", "반도체", "hynix", "nvidia", "005930", "000660", "nvda")):
        _add_weight(weights, "semiconductors", 1.0)
        _add_weight(weights, "technology", 1.0)
        _add_weight(weights, "exports", 0.75 if symbol.endswith((".KS", ".KQ")) else 0.45)
    if "communication" in text or "telecom" in text or "interactive media" in text:
        _add_weight(weights, "communication", 1.0)
        _add_weight(weights, "growth", 0.7)
    if "financial" in text or "bank" in text or "insurance" in text or "capital markets" in text:
        _add_weight(weights, "financials", 1.0)
    if "real estate" in text or "reit" in text:
        _add_weight(weights, "real_estate", 1.0)
    if "consumer cyclical" in text or "consumer discretionary" in text:
        _add_weight(weights, "consumer_cyclical", 1.0)
    if "consumer defensive" in text or "consumer staples" in text:
        _add_weight(weights, "consumer_defensive", 1.0)
    if "energy" in text or "oil" in text or "petroleum" in text:
        _add_weight(weights, "energy", 1.0)
    if "industrial" in text or "machinery" in text or "aerospace" in text or "defense" in text:
        _add_weight(weights, "industrials", 1.0)
    if "defense" in text or "aerospace & defense" in text:
        _add_weight(weights, "defense", 1.0)
    if "basic materials" in text or "chemicals" in text or "steel" in text or "materials" in text:
        _add_weight(weights, "materials", 1.0)
    if "utilities" in text:
        _add_weight(weights, "utilities", 1.0)
    if "healthcare" in text or "health care" in text:
        _add_weight(weights, "healthcare", 1.0)
    if any(term in text for term in ("auto manufacturers", "automobile", "automotive", "자동차")):
        _add_weight(weights, "autos", 1.0)
        _add_weight(weights, "consumer_cyclical", 0.85)
        if symbol.endswith((".KS", ".KQ")):
            _add_weight(weights, "exports", 0.8)
    if any(term in text for term in ("airline", "airlines", "transportation", "logistics", "shipping")):
        _add_weight(weights, "transport", 1.0)
        _add_weight(weights, "industrials", 0.65)

    # Well-known benchmark/name hints only fill gaps; they do not override provider data.
    if symbol in {"GOOG", "GOOGL"}:
        _add_weight(weights, "communication", 1.0)
        _add_weight(weights, "technology", 0.75)
        _add_weight(weights, "growth", 0.9)
    if symbol in {"QQQ"}:
        _add_weight(weights, "growth", max(weights.get("growth", 0.0), 0.85))
    if symbol in {"^GSPC", "VOO", "SPY"}:
        _add_weight(weights, "broad_market", 1.0)

    if sector or industry:
        basis.append("기업의 Yahoo Finance 섹터·산업 분류를 이슈 노출도에 반영했습니다.")
    if not weights:
        basis.append("섹터·산업 연결 정보가 부족해 이슈 노출도는 보수적으로 계산했습니다.")
    return weights, list(dict.fromkeys(basis))


def _label_groups(label: str) -> set[str]:
    text = str(label or "").casefold()
    # Conditional labels need company-specific valuation/earnings evidence. Do not
    # assume every growth stock or every company in the sector meets the condition.
    if any(term in text for term in (
        "밸류에이션 부담", "고평가 성장주", "실적 기대가 과도하게 선반영",
        "실적 개선이 집중된 해당 업종", "실적 하향이 집중된 해당 업종",
    )):
        return set()
    groups: set[str] = set()
    if any(term in text for term in ("it", "성장주", "데이터센터")):
        groups.update({"technology", "growth"})
    if "반도체" in text:
        groups.update({"semiconductors", "technology"})
    if "전력기기" in text or "전력인프라" in text:
        groups.update({"industrials", "utilities"})
    if any(term in text for term in ("은행", "보험", "증권", "금융")):
        groups.add("financials")
    if any(term in text for term in ("리츠", "부동산")):
        groups.add("real_estate")
    if "경기소비재" in text:
        groups.add("consumer_cyclical")
    if "필수소비재" in text or "방어주" in text:
        groups.add("consumer_defensive")
    if "통신" in text:
        groups.add("communication")
    if "유틸리티" in text:
        groups.add("utilities")
    if any(term in text for term in ("정유", "에너지")):
        groups.add("energy")
    if any(term in text for term in ("항공", "운송", "물류", "여행")):
        groups.add("transport")
    if any(term in text for term in ("화학", "소재", "원자재")):
        groups.add("materials")
    if any(term in text for term in ("산업재", "조선", "기계")):
        groups.add("industrials")
    if "방산" in text:
        groups.update({"defense", "industrials"})
    if any(term in text for term in ("자동차", "자동차부품", "2차전지")):
        groups.update({"autos", "consumer_cyclical"})
    if "수출" in text:
        groups.add("exports")
    if "장기채" in text or "채권" in text:
        groups.add("bonds")
    return groups


def _match_sector_labels(labels: Any, exposure: dict[str, float]) -> tuple[float, list[str]]:
    best = 0.0
    matched: list[str] = []
    for label in _sector_values(labels):
        groups = _label_groups(label)
        if not groups:
            continue
        score = max((exposure.get(group, 0.0) for group in groups), default=0.0)
        # Semiconductor-specific labels should not treat a generic tech ETF as
        # pure semiconductor exposure; allow a reduced secondary match.
        if "semiconductors" in groups and score == 0 and exposure.get("technology"):
            score = exposure.get("technology", 0.0) * 0.35
        if score > 0.12:
            best = max(best, score)
            matched.append(label)
    return best, list(dict.fromkeys(matched))


def _technical_pressure(snapshot: dict) -> tuple[float, list[str], list[str], int]:
    quote = snapshot.get("quote") or {}
    analysis = snapshot.get("analysis") or {}
    score = 0.0
    positive: list[str] = []
    caution: list[str] = []
    evidence = 0

    change = _num(quote.get("change_pct"))
    if change is not None:
        evidence += 1
        if change >= 2:
            score += 0.9; positive.append(f"전 거래일 대비 {change:+.2f}%로 단기 가격 흐름이 강합니다.")
        elif change >= 0.5:
            score += 0.4; positive.append(f"전 거래일 대비 {change:+.2f}% 상승했습니다.")
        elif change <= -2:
            score -= 0.9; caution.append(f"전 거래일 대비 {change:+.2f}%로 단기 가격 흐름이 약합니다.")
        elif change <= -0.5:
            score -= 0.4; caution.append(f"전 거래일 대비 {change:+.2f}% 하락했습니다.")

    r20 = _num(analysis.get("return_20d_pct"))
    if r20 is not None:
        evidence += 1
        if r20 >= 7:
            score += 0.9; positive.append(f"최근 20거래일 가격 변화율이 {r20:+.2f}%입니다.")
        elif r20 >= 3:
            score += 0.4; positive.append(f"최근 20거래일 가격 변화율이 {r20:+.2f}%로 양호합니다.")
        elif r20 <= -7:
            score -= 0.9; caution.append(f"최근 20거래일 가격 변화율이 {r20:+.2f}%입니다.")
        elif r20 <= -3:
            score -= 0.4; caution.append(f"최근 20거래일 가격 변화율이 {r20:+.2f}%로 약합니다.")

    sma20, sma60 = _num(analysis.get("sma20")), _num(analysis.get("sma60"))
    if sma20 is not None and sma60 is not None:
        evidence += 1
        if sma20 > sma60:
            score += 0.6; positive.append("20거래일 이동평균이 60거래일 이동평균보다 높습니다.")
        elif sma20 < sma60:
            score -= 0.6; caution.append("20거래일 이동평균이 60거래일 이동평균보다 낮습니다.")

    rsi = _num(analysis.get("rsi14"))
    if rsi is not None:
        evidence += 1
        if rsi >= 72:
            score -= 0.2; caution.append(f"RSI {rsi:.1f}로 단기 상승이 많이 누적된 구간입니다.")
        elif rsi <= 28:
            score += 0.1; caution.append(f"RSI {rsi:.1f}로 낙폭이 큰 구간이라 변동성이 커질 수 있습니다.")

    return max(-2.5, min(2.5, score)), positive, caution, evidence


def generate_issue_stock_review(snapshot: dict, market: dict) -> tuple[dict | None, str | None]:
    """Detailed selected-instrument review using market issues, price trend and stock news.

    The output is a research aid. Direction labels summarize the balance of the
    supplied evidence and are not a guarantee of future price movement.
    """
    if not isinstance(snapshot, dict) or not isinstance(market, dict):
        return None, "이슈 기반 분석 자료 형식이 올바르지 않습니다."

    exposure, exposure_basis = _instrument_exposure(snapshot)
    impacts = _sector_impacts(market, limit_per_region=6)
    issue_score = 0.0
    factors: list[dict] = []
    confidence_weight = {"높음": 1.0, "중간": 0.65, "낮음": 0.35}

    for impact in impacts:
        benefit_strength, benefit_labels = _match_sector_labels(impact.get("beneficiary_sectors"), exposure)
        risk_strength, risk_labels = _match_sector_labels(impact.get("risk_sectors"), exposure)
        net_strength = benefit_strength - risk_strength
        if abs(net_strength) < 0.12:
            continue
        conf = confidence_weight.get(str(impact.get("confidence") or "낮음"), 0.35)
        count = int(impact.get("topic_count") or 0)
        count_factor = min(1.15, 0.65 + min(count, 20) / 40.0)
        contribution = net_strength * conf * count_factor * 1.35
        issue_score += contribution
        factors.append({
            "region": impact.get("region"),
            "topic": impact.get("topic"),
            "signal": impact.get("signal"),
            "confidence": impact.get("confidence"),
            "topic_count": count,
            "effect": "호재 쪽" if contribution > 0 else "부담 쪽",
            "contribution": contribution,
            "matched_benefits": benefit_labels[:3],
            "matched_risks": risk_labels[:3],
            "news_ids": list(impact.get("news_ids") or [])[:4],
        })

    issue_score = max(-3.0, min(3.0, issue_score))
    factors.sort(key=lambda x: abs(x["contribution"]), reverse=True)

    technical_score, technical_positive, technical_caution, technical_evidence = _technical_pressure(snapshot)

    # Stock-specific news is an independent evidence axis. Only headline wording
    # is scored, so its contribution is deliberately smaller than issue/price axes.
    stock_news = (snapshot.get("news") or {}).get("items") or []
    news_positive_count = 0
    news_negative_count = 0
    news_neutral_count = 0
    news_ids: list[str] = []
    news_positive: list[str] = []
    news_caution: list[str] = []
    for item in stock_news[:12]:
        title = str(item.get("title") or "").strip()
        folded = title.casefold()
        pos = sum(1 for term in _POSITIVE if term in folded)
        neg = sum(1 for term in _NEGATIVE if term in folded)
        if pos > neg:
            news_positive_count += 1
            if len(news_positive) < 3 and title:
                news_positive.append(f"긍정 표현이 상대적으로 많은 헤드라인: {title}")
        elif neg > pos:
            news_negative_count += 1
            if len(news_caution) < 3 and title:
                news_caution.append(f"부정·경계 표현이 상대적으로 많은 헤드라인: {title}")
        else:
            news_neutral_count += 1
        if item.get("id"):
            news_ids.append(str(item["id"]))

    directional_news = news_positive_count + news_negative_count
    raw_news_net = news_positive_count - news_negative_count
    news_score = max(-1.2, min(1.2, raw_news_net * 0.28))
    if directional_news < 2:
        news_score *= 0.5
    if raw_news_net >= 2:
        news_direction = "긍정 헤드라인 우세"
    elif raw_news_net <= -2:
        news_direction = "부정 헤드라인 우세"
    else:
        news_direction = "뉴스 방향 혼재"

    combined = max(-6.0, min(6.0, issue_score + technical_score + news_score))
    if combined >= 1.6:
        direction = "상승 우세"
    elif combined <= -1.6:
        direction = "하락 우세"
    else:
        direction = "혼조·중립"

    position = snapshot.get("position") or {}
    signal_codes = {x.get("code") for x in (position.get("signals") or []) if isinstance(x, dict)}
    if "profit_review" in signal_codes and combined < 1.0:
        stance = "매도 검토"
    elif combined >= 2.3:
        stance = "매수 검토"
    elif combined <= -2.3:
        stance = "매도 검토"
    elif position:
        stance = "보유 검토"
    else:
        stance = "관망"

    evidence_count = len(factors) + technical_evidence + min(len(stock_news), 4)
    magnitude = abs(combined)
    confidence = "높음" if evidence_count >= 8 and magnitude >= 2.7 else "중간" if evidence_count >= 4 and magnitude >= 1.2 else "낮음"

    issue_reasons: list[str] = []
    issue_cautions: list[str] = []
    for item in factors[:6]:
        matched = item["matched_benefits"] if item["contribution"] > 0 else item["matched_risks"]
        label_text = ", ".join(matched) if matched else "선택 종목의 섹터 노출"
        sentence = (
            f"{item['region'] or '시장'} {item['topic'] or '토픽'} · {item['signal'] or '방향 불명확'} "
            f"({item['topic_count']}건): {label_text}와 연결되어 {item['effect']}으로 반영했습니다."
        )
        (issue_reasons if item["contribution"] > 0 else issue_cautions).append(sentence)

    if not factors:
        issue_cautions.append("오늘 핵심 토픽과 이 종목의 섹터·산업 사이에서 뚜렷한 직접 연결을 찾지 못했습니다.")
    if issue_score > 0 and technical_score < 0:
        issue_cautions.append("이슈 환경은 우호적이지만 최근 가격·기술 흐름은 반대 방향입니다.")
    elif issue_score < 0 and technical_score > 0:
        issue_cautions.append("이슈 환경은 부담 요인이 있지만 최근 가격·기술 흐름은 상대적으로 강합니다.")
    if news_score > 0 and combined < 0:
        news_caution.append("종목 뉴스 표현은 우호적이지만 다른 이슈·가격 지표가 이를 상쇄하고 있습니다.")
    elif news_score < 0 and combined > 0:
        news_caution.append("종목 뉴스에는 경계 표현이 있으나 이슈·가격 흐름은 상대적으로 강합니다.")

    position_return = _num(position.get("return_pct"))
    if position_return is not None:
        exposure_basis.append(f"입력한 평균 매수가 대비 평가수익률 {position_return:+.2f}%도 매매 검토 의견에 참고합니다.")

    summary = (
        f"오늘 이슈·섹터 {issue_score:+.2f}, 가격·기술 {technical_score:+.2f}, 종목 뉴스 {news_score:+.2f}를 합산한 "
        f"참고 점수는 {combined:+.2f}입니다. 현재 가격 방향 전망은 {direction}, 매매 판단은 {stance}입니다."
    )
    return {
        "symbol": snapshot.get("symbol"),
        "direction": direction,
        "stance": stance,
        "confidence": confidence,
        "combined_score": combined,
        "issue_score": issue_score,
        "technical_score": technical_score,
        "news_score": news_score,
        "news_direction": news_direction,
        "news_positive_count": news_positive_count,
        "news_negative_count": news_negative_count,
        "news_neutral_count": news_neutral_count,
        "summary": summary,
        "issue_reasons": issue_reasons[:5],
        "issue_cautions": issue_cautions[:5],
        "technical_positive": technical_positive[:5],
        "technical_caution": technical_caution[:5],
        "news_positive": news_positive[:3],
        "news_caution": news_caution[:4],
        "factors": factors[:8],
        "exposure_basis": exposure_basis[:5],
        "news_ids": news_ids[:6],
        "market_fetched_at": market.get("fetched_at"),
        "sample_size": int(market.get("sample_size") or len(market.get("items") or [])),
        "stock_news_count": len(stock_news),
    }, (
        "오늘 이슈·섹터 노출, 가격·기술지표, 종목별 뉴스 제목을 규칙 기반으로 결합한 참고 분석입니다. "
        "상승·하락 전망과 매매 검토는 미래 수익을 보장하거나 주문을 지시하지 않습니다."
    )

def generate_dashboard_brief(snapshot: dict) -> tuple[dict | None, str | None]:
    if not isinstance(snapshot, dict):
        return None, "분석 자료 형식이 올바르지 않습니다."
    market = snapshot.get("market") or {}
    sector_impacts = _sector_impacts(market)
    domestic_lookup = _impact_lookup(sector_impacts, "국내")
    overseas_lookup = _impact_lookup(sector_impacts, "해외")
    domestic_rows = _keyword_rows(market.get("domestic") or {}, domestic_lookup)
    overseas_rows = _keyword_rows(market.get("overseas") or {}, overseas_lookup)
    domestic_names = ", ".join(x["keyword"] for x in domestic_rows[:3]) or "뚜렷한 상위 토픽 없음"
    overseas_names = ", ".join(x["keyword"] for x in overseas_rows[:3]) or "뚜렷한 상위 토픽 없음"
    recommendations = [_stock_review(row) for row in (snapshot.get("stocks") or []) if isinstance(row, dict)]
    sample_size = int(market.get("sample_size") or len(market.get("items") or []))

    sector_candidates = []
    for row in sector_impacts:
        if row.get("confidence") == "낮음":
            continue
        for sector in row.get("beneficiary_sectors") or []:
            if sector not in sector_candidates:
                sector_candidates.append(sector)

    market_summary = (
        f"중복 제거 후 최근 헤드라인 {sample_size}건을 기준으로 국내에서는 {domestic_names}, 해외에서는 {overseas_names}가 핵심 토픽으로 집계됐습니다."
    )
    if sector_candidates:
        market_summary += " 토픽 방향을 시나리오로 적용했을 때 상대적으로 수혜 가능성을 점검할 섹터 후보는 " + ", ".join(sector_candidates[:6]) + "입니다."
    market_summary += " 헤드라인 빈도와 섹터 매핑은 참고용이며 실제 가격 방향이나 수익을 보장하지 않습니다."

    result = {
        "market_summary": market_summary,
        "domestic_summary": f"국내 헤드라인 {int((market.get('domestic') or {}).get('sample_size') or 0)}건에서 상위 토픽은 {domestic_names}입니다. 각 토픽의 방향과 수혜/부담 섹터 후보를 함께 확인합니다.",
        "overseas_summary": f"해외 헤드라인 {int((market.get('overseas') or {}).get('sample_size') or 0)}건에서 상위 토픽은 {overseas_names}입니다. 금리·달러·원자재·AI 공급망 등 국내 전달 경로를 함께 확인합니다.",
        "domestic_keywords": domestic_rows,
        "overseas_keywords": overseas_rows,
        "sector_impacts": sector_impacts,
        "cross_market_impact": _cross_impact(market, sector_impacts),
        "recommendations": recommendations,
    }
    warning = "API 키 없는 클라우드 기본 분석은 규칙 기반 시나리오 분석입니다. 생성형 LLM이 아니며, 수혜 섹터 표시는 뉴스 토픽 방향에 따른 후보군이지 매수 추천이나 수익 보장이 아닙니다."
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
