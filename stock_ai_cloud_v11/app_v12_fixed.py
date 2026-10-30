"""개인용 주식 리서치 노트. 실행: python -m streamlit run app.py"""
from __future__ import annotations

import hmac
import html
import json
import math
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import market_data as md
import data_profiles as dprof
import market_brief as mb
import news_data as nd
import portfolio as pf
import cloud_analysis as cai
import cloud_storage as cstore
from local_ai import explain_snapshot, generate_dashboard_brief, list_local_models
from portfolio_view import render_portfolio_summary, render_position_editor

ROOT = Path(__file__).resolve().parent
CLOUD_MODE = os.environ.get("STOCK_AI_CLOUD") == "1"
DESKTOP_MODE = bool(os.environ.get("STOCK_AI_DATA_DIR")) and not CLOUD_MODE
MOBILE_MODE = os.environ.get("STOCK_AI_MOBILE") == "1"
MOBILE_UI = MOBILE_MODE or CLOUD_MODE
MOBILE_PIN = str(os.environ.get("STOCK_AI_MOBILE_PIN") or "")
DATA_ROOT = Path(os.environ.get("STOCK_AI_DATA_DIR") or ROOT).expanduser().resolve()
KST = ZoneInfo("Asia/Seoul")
ACCENT = "#22736A"
SECTOR_KO = {
    "technology": "정보기술", "communication_services": "커뮤니케이션 서비스",
    "consumer_cyclical": "경기소비재", "consumer_defensive": "필수소비재",
    "financial_services": "금융", "healthcare": "헬스케어", "industrials": "산업재",
    "energy": "에너지", "utilities": "유틸리티", "realestate": "부동산",
    "real_estate": "부동산", "basic_materials": "기초소재",
}

st.set_page_config(page_title="주식 리서치 노트", page_icon="📈", layout="wide", initial_sidebar_state="collapsed" if MOBILE_UI else "expanded")


@st.cache_resource(show_spinner=False)
def prepare_data_directory(directory, desktop):
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    if desktop:
        cache = path / "cache" / "yfinance"
        cache.mkdir(parents=True, exist_ok=True)
        md.yf.set_tz_cache_location(str(cache))
    return path


try:
    prepare_data_directory(str(DATA_ROOT), DESKTOP_MODE)
except OSError:
    st.error("내 데이터 저장 폴더를 열 수 없습니다. 폴더의 쓰기 권한과 여유 공간을 확인한 뒤 다시 실행해 주세요.")
    st.stop()

st.markdown("""
<style>
.stApp {background:#F7F9F6; color:#203A35;}
.block-container {padding-top:2.1rem; padding-bottom:3rem; max-width:1480px;}
h1,h2,h3 {letter-spacing:-.035em;}
[data-testid="stSidebar"] {
  background:#F1F5F2 !important;
  color:#203A35 !important;
}
[data-testid="stSidebar"] > div:first-child {
  background:#F1F5F2 !important;
}
/* 사이드바: iPhone에서도 충분한 명암 대비를 유지한다. */
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3,
[data-testid="stSidebar"] h4,
[data-testid="stSidebar"] h5,
[data-testid="stSidebar"] h6,
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
[data-testid="stSidebar"] [role="radiogroup"] p,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stCaption p {
  color:#203A35 !important;
  opacity:1 !important;
  text-shadow:none !important;
}
[data-testid="stSidebar"] .stCaption p,
[data-testid="stSidebar"] small {
  color:#536A63 !important;
}
[data-testid="stSidebar"] input,
[data-testid="stSidebar"] textarea {
  color:#203A35 !important;
  background:#FFFFFF !important;
  caret-color:#203A35 !important;
}
[data-testid="stSidebar"] input::placeholder,
[data-testid="stSidebar"] textarea::placeholder {
  color:#7A8D87 !important;
  opacity:1 !important;
}
[data-testid="stSidebar"] [data-baseweb="select"] > div {
  background:#FFFFFF !important;
  color:#203A35 !important;
}
[data-testid="stSidebar"] [data-baseweb="select"] span {
  color:#203A35 !important;
}
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"],
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] * {
  color:#FFFFFF !important;
}
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"],
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] * {
  color:#203A35 !important;
}
[data-testid="stSidebar"] [data-baseweb="tag"],
[data-testid="stSidebar"] [data-baseweb="tag"] * {
  color:#FFFFFF !important;
}
[data-testid="stMetricValue"] {font-size:1.65rem;}
[data-testid="stVerticalBlockBorderWrapper"]>div {border-radius:16px;}
.eyebrow {font-size:.76rem;letter-spacing:.14em;color:#4C8175;font-weight:700;}
.intro {color:#61766F;margin-top:-.6rem;margin-bottom:1.4rem;}
/* 메인 화면의 오늘 이슈 새로고침 버튼은 항상 높은 대비로 표시한다. */
.st-key-issue_refresh button {
  background:#11131F !important;
  border-color:#11131F !important;
  color:#FFFFFF !important;
}
.st-key-issue_refresh button *,
.st-key-issue_refresh button p,
.st-key-issue_refresh button span {
  color:#FFFFFF !important;
  opacity:1 !important;
}
.st-key-issue_refresh button:hover {
  background:#202538 !important;
  border-color:#202538 !important;
}
.st-key-issue_refresh button:focus,
.st-key-issue_refresh button:active {
  color:#FFFFFF !important;
}

/* 오늘 토픽 수혜·부담 섹터 카드: 모바일에서도 높은 대비 유지 */
.sector-impact-badges {
  display:flex;
  flex-wrap:wrap;
  gap:.45rem;
  margin:.25rem 0 .7rem 0;
}
.sector-impact-badge {
  display:inline-block;
  border-radius:999px;
  padding:.34rem .68rem;
  font-size:.9rem;
  font-weight:800;
  line-height:1.25;
  letter-spacing:-.01em;
}
.sector-impact-badge.signal {
  background:#173F38 !important;
  color:#FFFFFF !important;
  border:1px solid #173F38 !important;
}
.sector-impact-badge.confidence {
  background:#EDF2F0 !important;
  color:#203A35 !important;
  border:1px solid #A7B8B2 !important;
}
.sector-impact-box {
  border-radius:12px;
  padding:.72rem .82rem;
  margin:.42rem 0;
  font-size:.95rem;
  font-weight:750;
  line-height:1.45;
}
.sector-impact-box.benefit {
  background:#DFF3E7 !important;
  color:#123D2D !important;
  border:1px solid #78B58F !important;
}
.sector-impact-box.risk {
  background:#FFF0DC !important;
  color:#5A3210 !important;
  border:1px solid #D9A15E !important;
}
.sector-impact-box.neutral {
  background:#EDF1F2 !important;
  color:#26373B !important;
  border:1px solid #AAB6B9 !important;
}
.sector-impact-box strong {
  color:inherit !important;
  font-weight:850 !important;
}
.sector-impact-box,
.sector-impact-box li {
  word-break:keep-all !important;
  overflow-wrap:break-word !important;
}
.sector-impact-box ul {
  margin:.42rem 0 0 1.15rem !important;
  padding:0 !important;
}
.sector-impact-box li {
  margin:.28rem 0 !important;
  line-height:1.5 !important;
  font-weight:700 !important;
}
.sector-impact-help {
  margin:.2rem 0 .65rem 0;
  color:#536A63;
  font-size:.86rem;
  line-height:1.5;
  word-break:keep-all;
}

/* 종목 종합분석 상단 판단 카드 */
.research-hero {
  display:grid;
  grid-template-columns:repeat(3,minmax(0,1fr));
  gap:.7rem;
  margin:.5rem 0 1rem 0;
}
.research-hero-card {
  border-radius:16px;
  padding:1rem 1.05rem;
  border:1px solid #C9D6D1;
  min-width:0;
}
.research-hero-card .label {
  font-size:.78rem;
  font-weight:800;
  letter-spacing:.03em;
  margin-bottom:.35rem;
}
.research-hero-card .value {
  font-size:1.42rem;
  line-height:1.2;
  font-weight:900;
  word-break:keep-all;
}
.research-hero-card.buy {background:#DDF3E5;color:#123D2D;border-color:#78B58F;}
.research-hero-card.sell {background:#FBE3E0;color:#6A211A;border-color:#D89A91;}
.research-hero-card.hold {background:#E7EEF8;color:#183C64;border-color:#9CB4D1;}
.research-hero-card.wait {background:#EDF1F2;color:#26373B;border-color:#AAB6B9;}
.research-hero-card.up {background:#E0F2E8;color:#123D2D;border-color:#7EB697;}
.research-hero-card.down {background:#FBE3E0;color:#6A211A;border-color:#D89A91;}
.research-hero-card.flat {background:#FFF2DE;color:#5A3210;border-color:#D9A15E;}
.research-hero-card.confidence {background:#F4F7F5;color:#203A35;border-color:#B7C5C0;}
.research-note {
  border-radius:12px;
  background:#F0F5F2;
  color:#314A43;
  padding:.78rem .9rem;
  margin:.35rem 0 .9rem 0;
  line-height:1.55;
}
@media (max-width:768px) {
  .research-hero {grid-template-columns:1fr !important;gap:.5rem !important;}
  .research-hero-card {padding:.85rem .9rem !important;}
  .research-hero-card .value {font-size:1.28rem !important;}
}

@media (max-width: 768px) {
  html, body {margin:0 !important; padding:0 !important; max-width:100vw !important; overflow-x:hidden !important;}
  .stApp {margin:0 !important; padding:0 !important; width:100vw !important; max-width:100vw !important; overflow-x:hidden !important;}

  /* iPhone: 사이드바가 본문 폭을 밀지 않고 화면 위에 겹쳐 열리게 한다. */
  [data-testid="stSidebar"] {
    position:fixed !important;
    left:0 !important;
    top:0 !important;
    bottom:0 !important;
    height:100dvh !important;
    min-width:min(88vw, 340px) !important;
    max-width:min(88vw, 340px) !important;
    z-index:1000000 !important;
  }
  [data-testid="stSidebar"][aria-expanded="false"] {
    width:0 !important;
    min-width:0 !important;
    max-width:0 !important;
    margin:0 !important;
    padding:0 !important;
    overflow:hidden !important;
    visibility:hidden !important;
    pointer-events:none !important;
    transform:translateX(-110%) !important;
  }
  [data-testid="stSidebar"][aria-expanded="false"] > div:first-child {
    width:0 !important;
    min-width:0 !important;
    max-width:0 !important;
    overflow:hidden !important;
  }
  [data-testid="stSidebar"][aria-expanded="true"] {
    visibility:visible !important;
    pointer-events:auto !important;
    overflow:auto !important;
    transform:none !important;
  }

  /* Streamlit 버전에 따라 main/header에 남는 sidebar offset을 모두 제거한다. */
  [data-testid="stAppViewContainer"],
  [data-testid="stAppViewBlockContainer"],
  [data-testid="stMain"],
  .main,
  section.main {
    margin-left:0 !important;
    left:0 !important;
    width:100% !important;
    max-width:100vw !important;
  }
  [data-testid="stHeader"] {
    left:0 !important;
    margin-left:0 !important;
    width:100% !important;
    max-width:100vw !important;
  }
  .block-container {
    width:100% !important;
    max-width:100% !important;
    margin-left:0 !important;
    margin-right:0 !important;
    padding-top:1rem !important;
    padding-left:.9rem !important;
    padding-right:.9rem !important;
    padding-bottom:4.5rem !important;
    box-sizing:border-box !important;
  }

  [data-testid="stHorizontalBlock"] {flex-direction:column !important; gap:.55rem !important;}
  [data-testid="stHorizontalBlock"] > div {width:100% !important; min-width:0 !important; flex:1 1 100% !important;}
  [data-testid="stMetricValue"] {font-size:1.35rem !important;}
  h1 {font-size:1.8rem !important;}
  h2 {font-size:1.45rem !important;}
  h3 {font-size:1.2rem !important;}
  .stButton button, .stLinkButton a {min-height:2.8rem; width:100%;}
  [data-testid="stDataFrame"] {max-width:100%; overflow-x:auto;}
  [data-testid="stPlotlyChart"] {width:100% !important; max-width:100% !important; overflow:hidden !important;}
  .sector-impact-badge {font-size:.95rem !important; padding:.4rem .72rem !important;}
  .sector-impact-box {font-size:1rem !important; line-height:1.5 !important; padding:.78rem .86rem !important;}
}
</style>
""", unsafe_allow_html=True)


def require_mobile_pin():
    if not MOBILE_MODE:
        return
    if not MOBILE_PIN:
        st.error("모바일 접속 PIN이 준비되지 않았습니다. PC에서 MOBILE_START.cmd로 다시 시작해 주세요.")
        st.stop()
    if st.session_state.get("_mobile_authorized"):
        return
    st.markdown('<div class="eyebrow">IPHONE ACCESS</div>', unsafe_allow_html=True)
    st.title("📱 주식 리서치 노트")
    st.caption("같은 Wi-Fi의 iPhone에서 접속했습니다. PC의 모바일 시작 창에 표시된 6자리 PIN을 입력하세요.")
    with st.form("mobile_pin_form"):
        entered = st.text_input("접속 PIN", type="password", max_chars=6, placeholder="6자리 PIN")
        submitted = st.form_submit_button("접속하기", type="primary", width="stretch")
    if submitted:
        if hmac.compare_digest(entered.strip(), MOBILE_PIN):
            st.session_state._mobile_authorized = True
            st.rerun()
        else:
            st.error("PIN이 맞지 않습니다. PC의 MOBILE_START.cmd 창에 표시된 번호를 확인해 주세요.")
    st.info("이 접속은 같은 Wi-Fi 안에서만 사용하세요. 공용 Wi-Fi에서는 모바일 접속 모드를 사용하지 않는 것을 권장합니다.")
    st.stop()


require_mobile_pin()


def _cloud_secret(name, default=""):
    if not CLOUD_MODE:
        return default
    try:
        return str(st.secrets.get(name, default) or default)
    except Exception:
        return default


def require_cloud_pin():
    if not CLOUD_MODE:
        return
    configured = _cloud_secret("APP_PIN")
    if not configured or st.session_state.get("_cloud_authorized"):
        return
    st.markdown('<div class="eyebrow">CLOUD ACCESS</div>', unsafe_allow_html=True)
    st.title("📱 주식 리서치 노트")
    st.caption("개인 클라우드 앱의 접속 PIN을 입력하세요.")
    with st.form("cloud_pin_form"):
        entered = st.text_input("접속 PIN", type="password", max_chars=32)
        submitted = st.form_submit_button("접속하기", type="primary", width="stretch")
    if submitted:
        if hmac.compare_digest(entered.strip(), configured):
            st.session_state._cloud_authorized = True
            st.rerun()
        else:
            st.error("PIN이 맞지 않습니다.")
    st.stop()


require_cloud_pin()


_PROFILE_STATE_KEYS = {
    "watch_symbols", "watch_meta", "positions", "portfolio_load_error", "available_symbols",
    "pending_symbol", "position_notice", "instrument_search", "selected_search_symbol",
    "portfolio_selection", "price_selection", "sector_selection", "stock_news_selection",
    "stock_ai_selection", "ai_result", "dashboard_ai_result", "market_impact_result",
    "research_ai_result", "sector_issue_review", "sector_issue_review",
}


def clear_profile_session(include_profile=False):
    """Clear only data-dependent session values when switching data profiles."""
    for key in list(st.session_state.keys()):
        if key in _PROFILE_STATE_KEYS or key.startswith("position_form_version_"):
            st.session_state.pop(key, None)
    if include_profile:
        st.session_state.pop("_data_profile_id", None)
        st.session_state.pop("_data_profile_name", None)
        st.session_state.pop("_profile_picker", None)


def choose_data_profile():
    if CLOUD_MODE:
        row = {"id": "cloud_iphone", "name": "iPhone 브라우저 데이터", "builtin": True}
        st.session_state._data_profile_id = row["id"]
        st.session_state._data_profile_name = row["name"]
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        return row, DATA_ROOT
    profiles = dprof.list_profiles(DATA_ROOT)
    by_id = {row["id"]: row for row in profiles}
    if not MOBILE_MODE:
        row = by_id["pc"]
        st.session_state._data_profile_id = row["id"]
        st.session_state._data_profile_name = row["name"]
        return row, dprof.ensure_profile_directory(DATA_ROOT, row["id"])

    current_id = st.session_state.get("_data_profile_id")
    if current_id in by_id:
        row = by_id[current_id]
        st.session_state._data_profile_name = row["name"]
        return row, dprof.ensure_profile_directory(DATA_ROOT, row["id"])

    st.markdown('<div class="eyebrow">DATA PROFILE</div>', unsafe_allow_html=True)
    st.title("📂 사용할 데이터 선택")
    st.caption("각 프로필은 관심종목·평단가·보유수량을 별도 파일에 저장합니다. iPhone과 PC 데이터를 섞지 않고 사용할 수 있습니다.")
    ids = [row["id"] for row in profiles]
    default_index = ids.index("iphone") if "iphone" in ids else 0
    selected = st.selectbox(
        "데이터 프로필",
        options=ids,
        index=default_index,
        format_func=lambda pid: by_id[pid]["name"],
        key="_profile_picker",
    )
    if st.button("이 데이터로 접속", type="primary", width="stretch"):
        clear_profile_session()
        st.session_state._data_profile_id = selected
        st.session_state._data_profile_name = by_id[selected]["name"]
        st.rerun()

    with st.expander("새로운 별도 데이터 만들기"):
        with st.form("create_data_profile", clear_on_submit=True):
            name = st.text_input("프로필 이름", placeholder="예: 가족용, 여행용, 테스트 계좌")
            create = st.form_submit_button("새 프로필 만들기", width="stretch")
        if create:
            try:
                row = dprof.create_profile(DATA_ROOT, name)
            except (ValueError, OSError) as exc:
                st.error(str(exc))
            else:
                clear_profile_session()
                st.session_state._data_profile_id = row["id"]
                st.session_state._data_profile_name = row["name"]
                st.rerun()
    st.info("프로필은 데이터를 분리하는 기능입니다. 보안 계정은 아니므로 같은 모바일 접속 PIN을 아는 사람은 다른 프로필도 선택할 수 있습니다.")
    st.stop()


choose_data_profile()

CLOUD_STATE, CLOUD_STORAGE_WARNING = cstore.load_state() if CLOUD_MODE else (None, None)
if CLOUD_STORAGE_WARNING:
    st.session_state.cloud_storage_warning = CLOUD_STORAGE_WARNING


def current_profile():
    if CLOUD_MODE:
        return {"id": "cloud_iphone", "name": "iPhone 브라우저 데이터", "builtin": True}
    profile_id = st.session_state.get("_data_profile_id", "pc")
    for row in dprof.list_profiles(DATA_ROOT):
        if row["id"] == profile_id:
            return row
    return {"id": "pc", "name": "PC 기본 데이터", "builtin": True}


def profile_root():
    if CLOUD_MODE:
        return DATA_ROOT
    return dprof.ensure_profile_directory(DATA_ROOT, current_profile()["id"])


def settings_path():
    return profile_root() / "watchlist.json"


def portfolio_path():
    return profile_root() / "portfolio.json"


def is_number(value):
    try:
        return value is not None and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def fmt_number(value, digits=2):
    return f"{float(value):,.{digits}f}" if is_number(value) else "—"


def fmt_price(value, currency, kind="stock"):
    if not is_number(value):
        return "조회 불가"
    if kind == "index":
        return f"{float(value):,.2f} pt"
    if currency == "KRW":
        return f"{float(value):,.0f} 원"
    if currency == "USD":
        return f"$ {float(value):,.2f}"
    return f"{float(value):,.2f} {currency or ''}".strip()


def display_time(value, day_only=False):
    if value is None or value == "":
        return "기준 시각 미제공"
    try:
        ts = pd.Timestamp(value)
        if day_only or ts.tzinfo is None:
            return ts.strftime("%Y-%m-%d")
        return ts.tz_convert("Asia/Seoul").strftime("%m/%d %H:%M KST")
    except (ValueError, TypeError):
        return str(value)


def sector_name(name):
    key = str(name).lower().replace(" ", "_").replace("-", "_")
    return SECTOR_KO.get(key, str(name))


@st.cache_data(ttl=60, show_spinner=False, max_entries=64)
def quote_cached(symbol):
    return md.fetch_quote(symbol)


@st.cache_data(ttl=60, show_spinner=False, max_entries=16)
def quotes_batch_cached(symbols):
    return md.fetch_quotes_batch(list(symbols))


@st.cache_data(ttl=86400, show_spinner=False, max_entries=64)
def profile_cached(symbol):
    return md.fetch_profile(symbol)


@st.cache_data(ttl=900, show_spinner=False, max_entries=64)
def history_cached(symbol):
    return md.fetch_history(symbol, period="2y")


@st.cache_data(ttl=86400, show_spinner=False, max_entries=64)
def fund_cached(symbol):
    return md.fetch_fund(symbol)


@st.cache_data(ttl=900, show_spinner=False, max_entries=64)
def news_cached(symbol, name):
    return nd.fetch_news(symbol, name=name, count=8, days=7)


@st.cache_data(ttl=900, show_spinner=False, max_entries=4)
def market_brief_cached():
    return mb.fetch_market_brief(count=100)


@st.cache_data(ttl=300, show_spinner=False, max_entries=32)
def instrument_search_cached(query):
    return md.search_instruments(query, max_results=8)


KNOWN = {item["symbol"]: item for item in md.WATCHLIST}
KNOWN.setdefault("VOO", {"symbol": "VOO", "name": "VOO · S&P 500 ETF", "kind": "etf", "market": "미국", "currency": "USD"})
DEFAULT_SYMBOLS = ["005930.KS", "000660.KS", "GOOGL", "NVDA", "QQQ", "^GSPC"]


def read_watchlist():
    if CLOUD_MODE:
        watch = (CLOUD_STATE or {}).get("watchlist") or {}
        values = watch.get("symbols") or DEFAULT_SYMBOLS.copy()
        valid = [s for s in values if isinstance(s, str) and re.fullmatch(r"[A-Z0-9^][A-Z0-9.^=\-]{0,23}", s)]
        return list(dict.fromkeys(valid))[:12] or DEFAULT_SYMBOLS.copy()
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
        values = data.get("symbols", DEFAULT_SYMBOLS)
        if not isinstance(values, list):
            return DEFAULT_SYMBOLS.copy()
        valid = [s for s in values if isinstance(s, str) and re.fullmatch(r"[A-Z0-9^][A-Z0-9.^=\-]{0,23}", s)]
        return list(dict.fromkeys(valid))[:12] or DEFAULT_SYMBOLS.copy()
    except (OSError, ValueError, AttributeError):
        return DEFAULT_SYMBOLS.copy()


def read_watchlist_meta():
    if CLOUD_MODE:
        raw = ((CLOUD_STATE or {}).get("watchlist") or {}).get("meta") or {}
    else:
        try:
            data = json.loads(settings_path().read_text(encoding="utf-8"))
            raw = data.get("meta", {})
        except (OSError, ValueError, AttributeError):
            return {}
    try:
        if not isinstance(raw, dict):
            return {}
        clean = {}
        for symbol, item in raw.items():
            if not isinstance(symbol, str) or not isinstance(item, dict):
                continue
            try:
                normalized = md.normalize_symbol(symbol)
            except ValueError:
                continue
            clean[normalized] = {
                "symbol": normalized,
                "name": str(item.get("name") or normalized)[:120],
                "kind": str(item.get("kind") or "stock"),
                "market": str(item.get("market") or ""),
                "currency": str(item.get("currency") or ""),
            }
        return clean
    except (ValueError, AttributeError, TypeError):
        return {}


def label(symbol):
    item = KNOWN.get(symbol)
    return f"{item['name']} · {symbol}" if item else symbol


def search_result_label(item):
    name = item.get("name") or item.get("symbol") or "종목"
    symbol = item.get("symbol") or ""
    extras = " · ".join(x for x in [item.get("exchange"), item.get("type_label")] if x)
    return f"{name} · {symbol}" + (f" · {extras}" if extras else "")


def search_item_to_known(item):
    quote_type = str(item.get("quote_type") or "").upper()
    kind = {"ETF": "etf", "INDEX": "index"}.get(quote_type, "stock")
    symbol = item.get("symbol") or ""
    currency = "KRW" if symbol.endswith((".KS", ".KQ")) else ("포인트" if kind == "index" else "")
    return {
        "symbol": symbol,
        "name": item.get("name") or symbol,
        "kind": kind,
        "market": item.get("exchange") or "",
        "currency": currency,
    }


def _dashboard_symbol_snapshot(symbol, position):
    known = KNOWN.get(symbol, {})
    quote = quote_cached(symbol)
    profile = profile_cached(symbol)
    history, history_error = history_cached(symbol)
    summary = None
    if history is not None and not history.empty:
        summary = md.summary_from_history(history)
    news = news_cached(symbol, known.get("name") or profile.get("name") or symbol)
    return {
        "symbol": symbol,
        "name": known.get("name") or profile.get("name") or symbol,
        "quote": quote,
        "sector": profile.get("sector"),
        "industry": profile.get("industry"),
        "analysis": summary,
        "analysis_error": history_error,
        "position": pf.evaluate_position(position, quote) if position else None,
        "news": news,
    }


def build_dashboard_snapshot(current_symbols):
    positions = st.session_state.positions
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(current_symbols)))) as pool:
        rows = list(pool.map(lambda s: _dashboard_symbol_snapshot(s, positions.get(s)), current_symbols))
    next_id = 1
    compact_rows = []
    for row in rows:
        compact_news = []
        for item in (row.get("news") or {}).get("items", [])[:4]:
            copied = dict(item)
            copied["id"] = f"S{next_id}"
            next_id += 1
            compact_news.append(copied)
        compact = dict(row)
        compact["news"] = {
            "items": compact_news,
            "fetched_at": (row.get("news") or {}).get("fetched_at"),
            "coverage_note": (row.get("news") or {}).get("coverage_note"),
            "error": (row.get("news") or {}).get("error"),
        }
        compact_rows.append(compact)
    return {
        "requested_at": datetime.now(KST).isoformat(),
        "market": market_brief_cached(),
        "stocks": compact_rows,
        "limits": (
            "최근 제공 시세·완료 일봉·뉴스 발행 시각은 서로 다를 수 있음. "
            "뉴스는 제목과 제공 요약 범위이며 기사 전문을 읽지 않음. "
            "뉴스와 가격의 동시 발생은 인과 증명이 아님. 비용·세금·배당·환율은 미반영. "
            "매수·보유·매도·관망은 참고용 검토 방향이며 실제 주문은 사용자가 결정함."
        ),
    }


def _source_index(snapshot):
    sources = {}
    for item in (snapshot.get("market") or {}).get("items", []):
        if isinstance(item, dict) and item.get("id"):
            sources[item["id"]] = item
    for row in snapshot.get("stocks", []):
        if not isinstance(row, dict):
            continue
        for item in (row.get("news") or {}).get("items", []):
            if isinstance(item, dict) and item.get("id"):
                sources[item["id"]] = item
    return sources


def _friendly_sector_label(value):
    text = str(value or "").strip()
    aliases = {
        "은행 예대마진 민감주": "은행주 (대출금리와 예금금리 차이에 민감)",
        "실적 기대가 과도하게 선반영된 업종": "실적 기대가 이미 주가에 많이 반영된 업종",
        "실적 개선이 집중된 해당 업종": "실적이 실제로 좋아진 기업이 많은 업종",
        "실적 하향이 집중된 해당 업종": "실적 전망이 나빠진 기업이 많은 업종",
        "고베타 성장주": "시장 등락에 크게 움직이는 성장주",
        "인플레이션 헤지 성격 자산": "물가 상승 때 상대적으로 강한 자산·업종",
        "가격전가력이 높은 방어주": "원가 상승을 판매가격에 반영하기 쉬운 방어주",
        "원화 환산 효과가 큰 수출주": "환율 변화가 원화 실적에 크게 반영되는 수출주",
        "중국 경기 방어형 포지션": "중국 경기 영향이 비교적 작은 방어 업종",
        "일부 방어주 상대수익률": "필수소비재·통신 등 일부 방어 업종의 상대 강도",
        "무역갈등 수혜 대체재 일부": "관세·무역갈등 때 대체 수요를 받을 수 있는 일부 업종",
        "방산·에너지 위험프리미엄": "방산·에너지 업종의 지정학적 위험 프리미엄",
    }
    return aliases.get(text, text)


def _sector_list_html(values, limit=4):
    # Older/stale analysis results may contain a single sector name as a string.
    # Iterating a string would split Korean text into individual characters, so
    # always normalize to a list before applying the display limit.
    if values is None:
        normalized = []
    elif isinstance(values, str):
        normalized = [values]
    elif isinstance(values, (list, tuple, set)):
        normalized = list(values)
        # Old analysis results may already be corrupted into character arrays,
        # e.g. ["은", "행", "·", "보", "험"]. Rejoin those before limiting rows.
        if len(normalized) >= 2 and all(isinstance(x, str) and len(x) == 1 for x in normalized):
            normalized = ["".join(normalized)]
    else:
        normalized = [values]

    rows = []
    for value in normalized[:max(1, int(limit))]:
        label = _friendly_sector_label(value)
        if label:
            rows.append(f"<li>{html.escape(label)}</li>")
    return "<ul>" + "".join(rows) + "</ul>" if rows else ""


def render_sector_impact_cards(impacts, title="오늘 토픽이 업종에 줄 수 있는 영향"):
    impacts = impacts or []
    if not impacts:
        return
    st.markdown(f"### 🧩 {title}")
    st.markdown(
        '<div class="sector-impact-help">'
        '<strong>호재 가능 업종</strong>은 현재 뉴스 방향이 이어질 때 상대적으로 유리할 수 있는 업종, '
        '<strong>불리할 수 있는 업종</strong>은 비용·수요·금리 등의 영향으로 상대적으로 부담을 받을 수 있는 업종을 뜻합니다. '
        '확정적인 주가 예측이나 매수·매도 추천은 아닙니다.</div>',
        unsafe_allow_html=True,
    )
    for start in range(0, min(len(impacts), 8), 2):
        cols = st.columns(2)
        for col, item in zip(cols, impacts[start:start + 2]):
            with col.container(border=True):
                st.caption(f"{item.get('region') or ''} · {item.get('topic') or '시장 토픽'} · 언급 {int(item.get('topic_count') or 0)}건")

                signal = html.escape(str(item.get('signal') or '방향 불명확'))
                confidence = html.escape(str(item.get('confidence') or '낮음'))
                st.markdown(
                    f'<div class="sector-impact-badges">'
                    f'<span class="sector-impact-badge signal">뉴스 방향 · {signal}</span>'
                    f'<span class="sector-impact-badge confidence">판단 확신도 · {confidence}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                beneficiaries = item.get('beneficiary_sectors') or []
                risks = item.get('risk_sectors') or []
                if beneficiaries:
                    st.markdown(
                        '<div class="sector-impact-box benefit"><strong>✅ 호재가 될 수 있는 업종</strong>'
                        + _sector_list_html(beneficiaries, limit=4) + '</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        '<div class="sector-impact-box neutral"><strong>➖ 호재 업종을 특정하기 어려움</strong><br>'
                        '뉴스의 방향이 서로 섞여 있거나 근거가 충분하지 않습니다.</div>',
                        unsafe_allow_html=True,
                    )
                if risks:
                    st.markdown(
                        '<div class="sector-impact-box risk"><strong>⚠️ 불리할 수 있는 업종</strong>'
                        + _sector_list_html(risks, limit=3) + '</div>',
                        unsafe_allow_html=True,
                    )
                if item.get('rationale'):
                    st.caption("왜 그렇게 보나 · " + str(item['rationale']))
                if item.get('basis'):
                    st.caption("뉴스 근거 · " + str(item['basis']))


def render_dashboard_brief(result, snapshot, created, model):
    engine_label = "분석 엔진" if CLOUD_MODE else "로컬 모델"
    st.caption(f"생성 {created} · {engine_label} {model} · 자동 주문 아님 · 새 데이터가 들어오면 다시 생성해 주세요.")
    recommendations = result.get("recommendations") or []
    if recommendations:
        st.markdown("**종목별 검토 의견**")
        for start in range(0, len(recommendations), 3):
            cols = st.columns(3)
            for col, rec in zip(cols, recommendations[start:start + 3]):
                symbol = rec["symbol"]
                with col.container(border=True):
                    st.caption(label(symbol))
                    st.subheader(rec.get("stance") or "관망")
                    st.caption(f"AI 확신도 · {rec.get('confidence') or '낮음'}")
                    st.write(rec.get("summary") or "요약이 제공되지 않았습니다.")
                    with st.expander("근거와 반대 근거"):
                        for reason in rec.get("reasons", []):
                            st.write(f"• 근거 · {reason}")
                        for counter in rec.get("counterpoints", []):
                            st.write(f"• 반대 가능성 · {counter}")
                        if not rec.get("reasons") and not rec.get("counterpoints"):
                            st.caption("모델이 구체적인 근거를 반환하지 않았습니다.")

    if result.get("market_summary"):
        with st.container(border=True):
            st.markdown("**오늘 시장 전체 요약**")
            st.write(result["market_summary"])

    domestic_summary = result.get("domestic_summary")
    overseas_summary = result.get("overseas_summary")
    if domestic_summary or overseas_summary:
        st.markdown("**국내·해외 이슈 분리 분석**")
        market_cols = st.columns(2)
        with market_cols[0].container(border=True):
            st.markdown("### 🇰🇷 국내 이슈")
            st.write(domestic_summary or "국내 이슈 요약이 제공되지 않았습니다.")
            for item in (result.get("domestic_keywords") or [])[:4]:
                st.markdown(f"**{item.get('keyword') or '키워드'}**")
                st.caption(item.get("why") or "추가 설명이 없습니다.")
        with market_cols[1].container(border=True):
            st.markdown("### 🌍 해외 이슈")
            st.write(overseas_summary or "해외 이슈 요약이 제공되지 않았습니다.")
            for item in (result.get("overseas_keywords") or [])[:4]:
                st.markdown(f"**{item.get('keyword') or '키워드'}**")
                st.caption(item.get("why") or "추가 설명이 없습니다.")

    render_sector_impact_cards(result.get("sector_impacts") or [], "핵심 토픽이 업종에 줄 수 있는 영향")

    cross = result.get("cross_market_impact") or {}
    if cross:
        with st.container(border=True):
            st.markdown("### 🔄 국내 ↔ 해외 상호 영향")
            if cross.get("net_effect"):
                st.write(cross["net_effect"])
            impact_cols = st.columns(2)
            with impact_cols[0]:
                st.markdown("**해외 → 국내**")
                st.write(cross.get("overseas_to_korea") or "현재 자료만으로 뚜렷한 영향 경로를 확인하기 어렵습니다.")
            with impact_cols[1]:
                st.markdown("**국내 → 해외**")
                st.write(cross.get("korea_to_overseas") or "현재 자료만으로 뚜렷한 영향 경로를 확인하기 어렵습니다.")
            channels = cross.get("channels") or []
            if channels:
                st.markdown("**주요 연결 경로**")
                for item in channels[:5]:
                    st.write(f"• {item.get('direction') or '상호'} · {item.get('channel') or '시장 연결'} — {item.get('impact') or ''}")

    sources = _source_index(snapshot)
    used = []
    for item in (result.get("domestic_keywords") or []):
        used.extend(item.get("news_ids", []))
    for item in (result.get("overseas_keywords") or []):
        used.extend(item.get("news_ids", []))
    for item in (cross.get("channels") or []):
        used.extend(item.get("news_ids", []))
    for item in recommendations:
        used.extend(item.get("news_ids", []))
    used = list(dict.fromkeys(x for x in used if x in sources))
    if used:
        with st.expander("AI 요약이 참조한 뉴스"):
            for source_id in used:
                source = sources[source_id]
                st.link_button(f"[{source_id}] {source.get('title')}", source.get("url"))
                st.caption(f"{source.get('publisher') or '매체 미제공'} · {display_time(source.get('published_at'))} · {source.get('region') or ''}")
    st.caption("국내·해외 영향 분석은 제공된 헤드라인과 시세의 동시 움직임을 바탕으로 한 참고 가설입니다. 인과관계를 확정하지 않으며, 확정적인 매매 지시나 수익 보장이 아닙니다.")


def render_issue_bucket(title, icon, bucket, chart_key):
    st.markdown(f"### {icon} {title}")
    keywords = (bucket or {}).get("keywords") or []
    topics = (bucket or {}).get("topics") or []
    items = (bucket or {}).get("items") or []
    sample_size = int((bucket or {}).get("sample_size") or len(items))
    st.caption(f"중복 제거 후 분석 표본 · {sample_size}건")
    if keywords:
        keyword_text = "  ·  ".join(f"**{item['keyword']}** {item['count']}건" for item in keywords[:5])
        st.markdown(keyword_text)
        keyword_df = pd.DataFrame(keywords[:8])
        keyword_chart = go.Figure(go.Pie(
            labels=keyword_df["keyword"], values=keyword_df["count"], hole=0.42,
            textinfo="label+percent",
            hovertemplate="%{label}<br>언급 %{value}건<br>키워드 언급 비중 %{percent}<extra></extra>",
            sort=False,
        ))
        keyword_chart.update_layout(
            height=300 if MOBILE_UI else 360,
            margin=dict(l=8, r=8, t=10, b=8),
            template="plotly_white",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            showlegend=False,
        )
        st.plotly_chart(keyword_chart, width="stretch", key=chart_key)
        st.caption("상위 키워드의 언급량 비중입니다. 한 기사에 여러 키워드가 동시에 포함될 수 있습니다.")
    else:
        st.info(f"현재 조건에서 {title} 키워드를 만들 만큼 헤드라인을 가져오지 못했습니다.")

    if topics:
        st.markdown("**핵심 토픽**")
        for item in topics[:5]:
            st.write(f"• {item.get('topic') or '토픽'} · {int(item.get('count') or 0)}건 · 표본의 {float(item.get('coverage_pct') or 0):.1f}%")

    with st.expander(f"{title} 헤드라인 보기 · 최근 20건"):
        for item in items[:20]:
            st.link_button(f"[{item['id']}] {item['title']}", item["url"])
            st.caption(f"{item.get('publisher') or '매체 미제공'} · {display_time(item.get('published_at'))} · {item.get('topic') or ''}")
        if len(items) > 20:
            st.caption(f"전체 분석 표본 {len(items)}건 중 최근 20건만 화면에 표시합니다. 나머지 기사도 키워드·토픽 집계에는 포함됩니다.")
        if not items:
            st.caption("표시할 헤드라인이 없습니다.")


def render_news(data, limit=8):
    st.caption(f"최근 7일 내 조회 자료 · 조회 {display_time(data.get('fetched_at'))} · {data.get('source') or '뉴스 제공자'}")
    if data.get("coverage_note"):
        st.caption(data["coverage_note"])
    if data.get("error"):
        st.info(data["error"])
    if not data.get("items"):
        st.info("현재 조건에 맞는 관련 뉴스를 가져오지 못했습니다. 뉴스가 없다는 뜻은 아닙니다.")
    for article in (data.get("items") or [])[:limit]:
        with st.container(border=True):
            st.markdown(f"**[{article['id']}]**")
            st.write(article["title"])
            st.caption(f"{article.get('publisher') or '매체 미제공'} · 발행 {display_time(article.get('published_at'))} · {article.get('relevance') or '관련성 직접 확인'}")
            if article.get("summary"):
                st.write(article["summary"])
                st.caption("제공자가 전달한 요약이며 기사 전문을 읽은 결과가 아닙니다.")
            st.link_button("기사 열기", article["url"])


def fetch_quotes(current_symbols):
    if not current_symbols:
        return {}
    quotes = quotes_batch_cached(tuple(current_symbols))
    # Keep the single-symbol cache useful for detail dashboards without issuing
    # another request during the same session.
    st.session_state.latest_quotes = {**st.session_state.get("latest_quotes", {}), **quotes}
    return quotes


def selection_context(symbol):
    known = KNOWN.get(symbol, {})
    profile = profile_cached(symbol)
    kind = known.get("kind") or profile.get("kind") or "stock"
    currency = profile.get("currency") or known.get("currency") or ""
    q = st.session_state.get("latest_quotes", {}).get(symbol)
    if not q:
        q = quote_cached(symbol)
        st.session_state.latest_quotes = {**st.session_state.get("latest_quotes", {}), symbol: q}
    return known, profile, kind, currency, q


def analysis_for(symbol):
    history, error = history_cached(symbol)
    if error:
        st.warning(error)
    if history is None or history.empty:
        st.info("가격 이력을 가져오지 못했습니다. 잠시 뒤 자료를 새로고침해 주세요.")
        return None, None
    return md.add_indicators(history), md.summary_from_history(history)


def render_market_ai_controls(active_symbols, key_prefix="market"):
    if CLOUD_MODE:
        st.caption("클라우드 기본판은 별도 API 키 없이 규칙 기반 자동 분석 엔진을 사용합니다. 생성형 LLM은 아닙니다.")
        if st.button("오늘 자동 분석 만들기", type="primary", width="stretch", key=f"{key_prefix}_cloud_brief_generate"):
            with st.spinner("국내·해외 이슈와 관심종목 데이터를 함께 검토하고 있습니다…"):
                snapshot = build_dashboard_snapshot(tuple(active_symbols))
                result, warning = cai.generate_dashboard_brief(snapshot)
            if warning:
                st.info(warning)
            if result:
                st.session_state.dashboard_brief = {
                    "result": result, "snapshot": snapshot, "model": "API 없는 클라우드 자동 분석",
                    "created": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
                }
                st.rerun()
        return
    controls = st.columns([1, 2, 2])
    if controls[0].button("로컬 AI 모델 확인", key=f"{key_prefix}_model_check"):
        models, model_error = list_local_models()
        st.session_state.local_models = models
        st.session_state.local_model_error = model_error
    models = st.session_state.get("local_models", [])
    if models:
        model = controls[1].selectbox("분석 모델", models, key=f"{key_prefix}_model")
        if controls[2].button("오늘 종합 AI 분석 만들기", type="primary", width="stretch", key=f"{key_prefix}_brief_generate"):
            with st.spinner("국내·해외 이슈와 관심종목 데이터를 함께 검토하고 있습니다…"):
                snapshot = build_dashboard_snapshot(tuple(active_symbols))
                result, warning = generate_dashboard_brief(model, snapshot)
            if warning:
                st.warning(warning)
            if result:
                st.session_state.dashboard_brief = {
                    "result": result, "snapshot": snapshot, "model": model,
                    "created": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
                }
                st.rerun()
    else:
        if st.session_state.get("local_model_error"):
            st.info(st.session_state.local_model_error)
        st.caption("Ollama 로컬 모델을 연결하면 국내↔해외 영향과 종목별 검토 의견까지 생성할 수 있습니다.")


def render_today_issue_dashboard(active_symbols):
    st.markdown('<div class="eyebrow">TODAY MARKET</div>', unsafe_allow_html=True)
    st.title("오늘의 이슈")
    st.markdown('<div class="intro">국내와 해외 경제·증시 이슈를 따로 보고, 마지막에는 서로 어떤 영향을 주고받을 수 있는지 확인합니다.</div>', unsafe_allow_html=True)
    issue_header = st.columns([4, 1])
    issue_header[0].caption("최근 약 24시간의 공개 경제·증시 헤드라인을 국내·해외로 나눠 중복 제거 후 약 100건 규모로 분석합니다.")
    if issue_header[1].button("오늘 이슈 새로고침", width="stretch", key="issue_refresh"):
        market_brief_cached.clear()
        st.rerun()
    with st.spinner("국내·해외 경제·증시 헤드라인을 나누어 확인하고 있습니다…"):
        market_brief = market_brief_cached()
    issue_cols = st.columns(2)
    with issue_cols[0].container(border=True):
        render_issue_bucket("국내 이슈", "🇰🇷", market_brief.get("domestic") or {}, "domestic_issue_donut")
    with issue_cols[1].container(border=True):
        render_issue_bucket("해외 이슈", "🌍", market_brief.get("overseas") or {}, "overseas_issue_donut")
    if market_brief.get("error"):
        st.info(market_brief["error"])
    st.divider()
    st.subheader("국내 ↔ 해외 영향 AI 분석")
    st.caption("뉴스 제목·제공 요약과 시세를 근거로 가능한 영향 경로를 정리합니다. 동시 발생을 인과관계로 확정하지 않습니다.")
    render_market_ai_controls(active_symbols, "issue")
    current_brief = st.session_state.get("dashboard_brief")
    current_issue_stamp = market_brief.get("fetched_at")
    brief_issue_stamp = (((current_brief or {}).get("snapshot") or {}).get("market") or {}).get("fetched_at")
    if current_brief and current_brief.get("result", {}).get("cross_market_impact") and brief_issue_stamp == current_issue_stamp:
        cross = current_brief["result"]["cross_market_impact"]
        with st.container(border=True):
            st.markdown("### 🔄 최종 상호 영향 요약")
            if cross.get("net_effect"):
                st.write(cross["net_effect"])
            cross_cols = st.columns(2)
            with cross_cols[0]:
                st.markdown("**해외 → 국내**")
                st.write(cross.get("overseas_to_korea") or "뚜렷한 연결 경로를 확인하기 어렵습니다.")
            with cross_cols[1]:
                st.markdown("**국내 → 해외**")
                st.write(cross.get("korea_to_overseas") or "뚜렷한 연결 경로를 확인하기 어렵습니다.")
            channels = cross.get("channels") or []
            if channels:
                st.markdown("**주요 연결 경로**")
                for item in channels[:5]:
                    st.write(f"• {item.get('direction') or '상호'} · {item.get('channel') or '시장 연결'} — {item.get('impact') or ''}")
        render_sector_impact_cards(current_brief["result"].get("sector_impacts") or [], "오늘 토픽이 업종에 줄 수 있는 영향")
    elif current_brief and brief_issue_stamp != current_issue_stamp:
        st.info("오늘 이슈 자료가 새로 갱신되었습니다. 위 버튼으로 AI 분석을 다시 만들면 최신 자료 기준으로 갱신됩니다.")
    else:
        st.caption("AI 모델을 준비한 뒤 분석을 만들면 이 위치에 해외→국내, 국내→해외 영향 요약이 표시됩니다.")
    st.caption(f"출처: {market_brief.get('source') or '공개 뉴스 RSS'} · 조회 {display_time(market_brief.get('fetched_at'))}. {market_brief.get('coverage_note') or ''}")


def render_ai_summary_dashboard(active_symbols):
    st.markdown('<div class="eyebrow">AI REVIEW</div>', unsafe_allow_html=True)
    st.title("AI 매매 검토")
    st.markdown('<div class="intro">종목별 등락·기술지표·관련 뉴스·내 보유 상태를 함께 읽어 참고용 검토 의견과 근거를 정리합니다.</div>', unsafe_allow_html=True)
    st.info("AI 의견은 자동 주문이나 투자 권유가 아닙니다. ‘매수 검토 / 보유 검토 / 매도 검토 / 관망’은 확인할 방향을 정리하는 참고 표현입니다.")
    render_market_ai_controls(active_symbols, "summary")
    dashboard_brief = st.session_state.get("dashboard_brief")
    if dashboard_brief:
        saved_symbols = [row.get("symbol") for row in dashboard_brief.get("snapshot", {}).get("stocks", []) if isinstance(row, dict)]
        if set(saved_symbols) != set(active_symbols):
            st.warning("관심·보유 종목 구성이 AI 요약 생성 이후 바뀌었습니다. 현재 종목 기준으로 다시 생성해 주세요.")
        render_dashboard_brief(dashboard_brief["result"], dashboard_brief["snapshot"], dashboard_brief["created"], dashboard_brief["model"])
    else:
        st.caption("아직 생성된 종합 AI 요약이 없습니다.")


def render_quotes_once(current_symbols):
    with st.spinner("가격과 기준 시각을 확인하는 중입니다…"):
        quotes = fetch_quotes(current_symbols)
    failures = []
    for start in range(0, len(current_symbols), 3):
        cols = st.columns(3)
        for col, symbol in zip(cols, current_symbols[start:start + 3]):
            item = KNOWN.get(symbol, {"name": symbol, "kind": "index" if symbol.startswith("^") else "stock", "currency": ""})
            q = quotes[symbol]
            with col.container(border=True):
                st.caption(f"{item['name']}  /  {symbol}")
                change = q.get("change_pct")
                delta = f"{float(change):+.2f}% · 전 거래일 대비" if is_number(change) else None
                st.metric("최근 제공 시세", fmt_price(q.get("price"), q.get("currency") or item.get("currency"), item["kind"]), delta=delta, delta_color="off", label_visibility="collapsed")
                st.caption(f"{q.get('asof_label') or '시세 기준'} · {display_time(q.get('asof'), q.get('asof_label', '').find('일봉') >= 0)}")
                if q.get("error"):
                    failures.append(f"{symbol}: {q['error']}")
    if failures:
        with st.expander(f"조회 상태 확인 ({len(failures)}개)"):
            for message in failures:
                st.write(message)
    return quotes


def render_quotes_dashboard(active_symbols):
    st.markdown('<div class="eyebrow">WATCHLIST</div>', unsafe_allow_html=True)
    st.title("관심종목 시세")
    st.markdown('<div class="intro">관심종목과 보유종목의 최근 제공 시세와 전 거래일 대비 등락을 한 화면에서 확인합니다.</div>', unsafe_allow_html=True)
    quotes = render_quotes_once(tuple(active_symbols))
    st.caption(f"화면 확인 · {datetime.now(KST):%Y-%m-%d %H:%M:%S} KST · 가격 캐시 최대 60초")
    return quotes


def render_portfolio_dashboard(active_symbols):
    st.markdown('<div class="eyebrow">PORTFOLIO</div>', unsafe_allow_html=True)
    st.title("보유·수익률")
    st.markdown('<div class="intro">보유량·평균 매수가·평가금액·수익률을 통화별로 보고, 종목별 기준을 수정합니다.</div>', unsafe_allow_html=True)
    symbols_for_quotes = list(dict.fromkeys([*active_symbols, *st.session_state.positions]))
    with st.spinner("보유종목의 최근 시세를 확인하고 있습니다…"):
        quotes = fetch_quotes(tuple(symbols_for_quotes))
    render_portfolio_summary(st.session_state.positions, quotes, label)
    if not active_symbols:
        return
    st.divider()
    selection = st.selectbox("보유 정보를 입력·수정할 종목", options=active_symbols, format_func=label, key="portfolio_selection")
    known, profile, kind, currency, q = selection_context(selection)
    render_position_editor(selection, kind, currency, q, portfolio_path(), save_callback=cstore.save_positions if CLOUD_MODE else None)


def render_price_dashboard(active_symbols):
    st.markdown('<div class="eyebrow">PRICE</div>', unsafe_allow_html=True)
    st.title("가격 차트")
    st.markdown('<div class="intro">선택한 종목의 최근 가격 흐름과 기본 기술지표를 확인합니다.</div>', unsafe_allow_html=True)
    selection = st.selectbox("종목 선택", options=active_symbols, format_func=label, key="price_selection")
    known, profile, kind, currency, q = selection_context(selection)
    df, summary = analysis_for(selection)
    if df is None:
        return
    duration = st.radio("차트 기간", ["3개월", "6개월", "1년", "2년"], index=2, horizontal=True, key="price_duration")
    count = {"3개월": 63, "6개월": 126, "1년": 252, "2년": 504}[duration]
    view = df.tail(count)
    chart = go.Figure()
    chart.add_trace(go.Scatter(x=view.index, y=view["Close"], name="일봉 종가·진행 중 가격", line=dict(color=ACCENT, width=2)))
    chart.update_layout(height=340 if MOBILE_UI else 430, margin=dict(l=15, r=15, t=20, b=20), template="plotly_white",
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        yaxis_title="지수(pt)" if kind == "index" else currency,
                        hovermode="x unified", showlegend=False, font=dict(family="sans-serif"))
    st.plotly_chart(chart, width="stretch")
    if summary:
        a, b, c = st.columns(3)
        a.metric("20거래일 변화율", f"{fmt_number(summary.get('return_20d_pct'))}%" if is_number(summary.get('return_20d_pct')) else "—", delta_color="off")
        b.metric("RSI · 14거래일", fmt_number(summary.get("rsi14"), 1))
        c.metric("20거래일 연환산 변동성", f"{fmt_number(summary.get('annual_volatility_20d_pct'))}%" if is_number(summary.get('annual_volatility_20d_pct')) else "—")
        st.caption(f"지표 기준일: {display_time(summary.get('asof'), True)} · {summary.get('basis', '제공자 종가')}")
    st.caption("출처: Yahoo Finance. 당일 일봉은 장중·지연 값일 수 있으며 지표만으로 미래 가격을 확정할 수 없습니다.")




def _research_hero_html(result):
    stance = str(result.get("stance") or "관망")
    direction = str(result.get("direction") or "혼조·중립")
    confidence = str(result.get("confidence") or "낮음")
    stance_class = "buy" if "매수" in stance else "sell" if "매도" in stance else "hold" if "보유" in stance else "wait"
    direction_class = "up" if "상승" in direction else "down" if "하락" in direction else "flat"
    return (
        '<div class="research-hero">'
        f'<div class="research-hero-card {stance_class}"><div class="label">매매 검토</div><div class="value">{html.escape(stance)}</div></div>'
        f'<div class="research-hero-card {direction_class}"><div class="label">가격 방향 전망</div><div class="value">{html.escape(direction)}</div></div>'
        f'<div class="research-hero-card confidence"><div class="label">판단 확신도</div><div class="value">{html.escape(confidence)}</div></div>'
        '</div>'
    )


def _render_research_score_chart(result):
    labels = ["오늘 이슈·섹터", "가격·기술", "종목 뉴스"]
    values = [
        float(result.get("issue_score") or 0),
        float(result.get("technical_score") or 0),
        float(result.get("news_score") or 0),
    ]
    colors = ["#2B7A66" if value >= 0 else "#B35A4A" for value in values]
    figure = go.Figure(go.Bar(
        x=values,
        y=labels,
        orientation="h",
        text=[f"{value:+.2f}" for value in values],
        textposition="auto",
        marker_color=colors,
        hovertemplate="%{y}<br>점수 %{x:+.2f}<extra></extra>",
    ))
    bound = max(3.0, max((abs(v) for v in values), default=0) + .5)
    figure.update_layout(
        height=235 if MOBILE_UI else 260,
        margin=dict(l=10, r=15, t=10, b=10),
        template="plotly_white",
        xaxis=dict(title="방향 점수 · +는 우호적 / -는 부담", range=[-bound, bound], zeroline=True),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    st.plotly_chart(figure, width="stretch", key="research_score_breakdown")


def _render_research_price_chart(history, summary, currency, kind):
    if history is None or history.empty:
        st.info("가격 이력을 가져오지 못해 가격 추세 그래프를 표시하지 못했습니다.")
        return
    try:
        completed = md.completed_daily_history(history)
        data = md.add_indicators(completed)
    except Exception:
        data = md.add_indicators(history)
    if data is None or data.empty:
        st.info("가격 이력이 부족해 추세 그래프를 만들지 못했습니다.")
        return
    view = data.tail(126)
    price_col = "AnalysisClose" if "AnalysisClose" in view.columns else "Close"
    figure = go.Figure()
    figure.add_trace(go.Scatter(x=view.index, y=view[price_col], name="가격", line=dict(width=2.3)))
    if "SMA20" in view and view["SMA20"].notna().any():
        figure.add_trace(go.Scatter(x=view.index, y=view["SMA20"], name="20일선", line=dict(width=1.4)))
    if "SMA60" in view and view["SMA60"].notna().any():
        figure.add_trace(go.Scatter(x=view.index, y=view["SMA60"], name="60일선", line=dict(width=1.4)))
    figure.update_layout(
        height=330 if MOBILE_UI else 410,
        margin=dict(l=10, r=10, t=15, b=10),
        template="plotly_white",
        yaxis_title="지수(pt)" if kind == "index" else (currency or "가격"),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(figure, width="stretch", key="research_price_trend")
    if summary:
        cols = st.columns(4)
        cols[0].metric("20거래일", f"{float(summary['return_20d_pct']):+.2f}%" if is_number(summary.get("return_20d_pct")) else "—", delta_color="off")
        cols[1].metric("RSI 14", f"{float(summary['rsi14']):.1f}" if is_number(summary.get("rsi14")) else "—", delta_color="off")
        cols[2].metric("20일선", fmt_number(summary.get("sma20"), 2) if is_number(summary.get("sma20")) else "—", delta_color="off")
        cols[3].metric("60일선", fmt_number(summary.get("sma60"), 2) if is_number(summary.get("sma60")) else "—", delta_color="off")
        st.caption(f"완료 일봉 기준 · {display_time(summary.get('asof'), True)} · {summary.get('basis') or '제공자 가격'}")


def _render_research_sector_detail(selection, profile, kind, fund):
    st.subheader("섹터·산업 / ETF 구성")
    if kind == "stock":
        left, right = st.columns(2)
        with left.container(border=True):
            st.caption("상위 분류 · 섹터")
            st.subheader(sector_name(profile.get("sector")) if profile.get("sector") else "자료 미제공")
            if profile.get("sector"):
                st.caption(str(profile.get("sector")))
        with right.container(border=True):
            st.caption("세부 분류 · 산업")
            st.subheader(profile.get("industry") or "자료 미제공")
        st.caption(f"Yahoo Finance 기업 분류 · 조회 {display_time(profile.get('fetched_at'))}")
        if profile.get("error"):
            st.warning(profile["error"])
        return

    if kind not in {"etf", "index"}:
        st.info("이 상품 유형은 상세 섹터 구성을 제공하지 않습니다.")
        return
    if selection == "^GSPC":
        st.info("S&P 500 지수는 구성 참고용으로 VOO의 섹터 비중을 사용합니다.")
    if not fund:
        st.info("ETF 구성 정보를 가져오지 못했습니다.")
        return
    fund_symbol = str(fund.get("symbol") or ("VOO" if selection == "^GSPC" else selection))
    sectors = fund.get("sectors") or {}
    if sectors:
        series = pd.Series({sector_name(k): float(v) * 100 for k, v in sectors.items() if is_number(v) and float(v) >= 0}).sort_values(ascending=False).head(8)
        figure = go.Figure(go.Bar(
            x=series.iloc[::-1].values,
            y=series.iloc[::-1].index,
            orientation="h",
            text=[f"{v:.1f}%" for v in series.iloc[::-1]],
            textposition="outside",
        ))
        figure.update_layout(
            height=320 if MOBILE_UI else 360,
            margin=dict(l=10, r=55, t=10, b=10),
            template="plotly_white",
            xaxis_title="섹터 비중(%)",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(figure, width="stretch", key="research_fund_sectors")
    else:
        st.info("섹터 비중을 제공받지 못했습니다.")

    holdings = fund.get("holdings")
    with st.expander("상위 보유 종목 보기"):
        if isinstance(holdings, pd.DataFrame) and not holdings.empty:
            shown = holdings.head(10).copy()
            for column in shown.columns:
                if "holding" in str(column).lower() or "weight" in str(column).lower():
                    shown[column] = shown[column].map(lambda x: f"{float(x)*100:.2f}%" if is_number(x) else str(x))
            st.dataframe(shown, width="stretch")
        else:
            st.caption("상위 보유 종목 자료를 제공받지 못했습니다.")
    st.caption(f"출처: Yahoo Finance / yfinance · 구성 기준일: {fund.get('asof') or '미제공'} · 조회 {display_time(fund.get('fetched_at'))}")
    if fund.get("error"):
        st.warning(fund["error"])


def _render_research_issue_detail(result):
    st.subheader("오늘 이슈가 이 종목에 미치는 영향")
    st.caption(f"오늘 이슈 분석 표본 {int(result.get('sample_size') or 0)}건 · 선택 종목과 실제 섹터/산업 또는 ETF 섹터 비중을 연결했습니다.")
    factors = result.get("factors") or []
    if factors:
        for item in factors[:6]:
            contribution = float(item.get("contribution") or 0)
            icon = "↗️" if contribution > 0 else "↘️"
            with st.container(border=True):
                st.markdown(f"**{icon} {item.get('topic') or '시장 토픽'} · {item.get('signal') or '방향 불명확'}**")
                st.caption(f"{item.get('region') or '시장'} · 언급 {int(item.get('topic_count') or 0)}건 · 분석 확신도 {item.get('confidence') or '낮음'} · 영향점수 {contribution:+.2f}")
                matched = item.get("matched_benefits") if contribution > 0 else item.get("matched_risks")
                if matched:
                    st.write("연결된 업종: " + ", ".join(str(x) for x in matched))
    else:
        st.info("오늘 핵심 토픽과 선택 종목의 섹터 사이에서 뚜렷한 직접 연결을 찾지 못했습니다.")


def _render_research_detailed_reasoning(result):
    st.subheader("상세 AI 분석")
    st.markdown(
        f'<div class="research-note"><strong>종합 판단</strong><br>{html.escape(str(result.get("summary") or "분석 요약이 없습니다."))}</div>',
        unsafe_allow_html=True,
    )
    positive = (result.get("issue_reasons") or []) + (result.get("technical_positive") or []) + (result.get("news_positive") or [])
    caution = (result.get("issue_cautions") or []) + (result.get("technical_caution") or []) + (result.get("news_caution") or [])
    cols = st.columns(2)
    with cols[0].container(border=True):
        st.markdown("**상승·매수/보유 쪽 근거**")
        if positive:
            for row in positive[:8]:
                st.write(f"• {row}")
        else:
            st.caption("현재 자료에서 뚜렷한 우호 근거가 충분하지 않습니다.")
    with cols[1].container(border=True):
        st.markdown("**하락·매도 쪽 위험요인**")
        if caution:
            for row in caution[:8]:
                st.write(f"• {row}")
        else:
            st.caption("현재 자료에서 별도 경계 요인이 충분히 잡히지 않았습니다.")
    basis = result.get("exposure_basis") or []
    if basis:
        with st.expander("분석에서 종목과 이슈를 연결한 기준"):
            for row in basis:
                st.write(f"• {row}")


def _render_research_extra_ai(selection, snapshot):
    st.subheader("추가 질문 분석")
    st.caption("위 종합분석 외에 선택 종목의 가격·뉴스·보유정보를 기준으로 원하는 질문을 추가할 수 있습니다.")
    question = st.text_input(
        "궁금한 점",
        value="오늘 이슈와 최근 종목 뉴스를 함께 봤을 때 지금 가장 주의해서 확인할 요소를 알려줘.",
        max_chars=600,
        key="research_ai_question",
    )
    if CLOUD_MODE:
        if st.button("추가 분석 만들기", width="stretch", key="research_cloud_ai_generate"):
            answer, error = cai.explain_snapshot(snapshot, question)
            if error:
                st.info(error)
            if answer:
                st.session_state.research_ai_result = {
                    "symbol": selection,
                    "text": answer,
                    "created": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
                    "model": "API 없는 클라우드 자동 분석",
                }
                st.rerun()
    else:
        if st.button("설치된 로컬 모델 확인", key="research_model_check"):
            models, model_error = list_local_models()
            st.session_state.local_models = models
            st.session_state.local_model_error = model_error
        models = st.session_state.get("local_models", [])
        if st.session_state.get("local_model_error"):
            st.info(st.session_state.local_model_error)
        if models:
            model = st.selectbox("분석 모델", models, key="research_ai_model")
            if st.button("추가 AI 분석 만들기", width="stretch", key="research_local_ai_generate"):
                answer, error = explain_snapshot(model, snapshot, question)
                if error:
                    st.warning(error)
                if answer:
                    st.session_state.research_ai_result = {
                        "symbol": selection,
                        "text": answer,
                        "created": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
                        "model": model,
                    }
                    st.rerun()
        else:
            st.caption("Ollama 로컬 모델을 연결하면 자유로운 추가 질문 분석을 사용할 수 있습니다.")

    saved = st.session_state.get("research_ai_result") or {}
    if saved.get("symbol") == selection and saved.get("text"):
        with st.container(border=True):
            st.caption(f"{saved.get('model') or '분석 엔진'} · 생성 {saved.get('created') or ''}")
            st.markdown(saved["text"])



def _render_all_symbol_review(active_symbols, selected_symbol):
    st.subheader("관심·보유 종목 전체 매매 검토")
    st.caption(
        "현재 관심종목과 보유종목을 같은 기준으로 비교합니다. 선택 종목의 상세 분석은 아래에서 이어집니다."
    )

    if CLOUD_MODE:
        if st.button("전체 종목 AI 비교 갱신", type="primary", width="stretch", key="research_all_refresh"):
            with st.spinner("관심·보유 종목의 가격·기술지표·뉴스를 같은 기준으로 비교하고 있습니다…"):
                snapshot = build_dashboard_snapshot(tuple(active_symbols))
                result, warning = cai.generate_dashboard_brief(snapshot)
            if warning:
                st.info(warning)
            if result:
                st.session_state.dashboard_brief = {
                    "result": result,
                    "snapshot": snapshot,
                    "model": "API 없는 클라우드 자동 분석",
                    "created": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
                }
                st.rerun()
    else:
        render_market_ai_controls(active_symbols, "research_all")

    brief = st.session_state.get("dashboard_brief") or {}
    result = brief.get("result") or {}
    recommendations = result.get("recommendations") or []
    if not recommendations:
        st.info("아직 전체 종목 비교 결과가 없습니다. 위 버튼으로 현재 종목들을 한 번에 분석해 주세요.")
        return

    saved_symbols = [
        row.get("symbol")
        for row in (brief.get("snapshot") or {}).get("stocks", [])
        if isinstance(row, dict)
    ]
    if set(saved_symbols) != set(active_symbols):
        st.warning("관심·보유 종목 구성이 전체 비교 생성 이후 바뀌었습니다. 최신 종목 기준으로 다시 갱신해 주세요.")

    rows = []
    for rec in recommendations:
        symbol = str(rec.get("symbol") or "")
        item = KNOWN.get(symbol, {})
        name = str(item.get("name") or symbol)
        direction = str(rec.get("direction") or ("상승 우세" if "매수" in str(rec.get("stance")) else "하락 우세" if "매도" in str(rec.get("stance")) else "혼조·중립"))
        score = rec.get("score")
        rows.append({
            "종목": name,
            "티커": symbol,
            "매매 검토": rec.get("stance") or "관망",
            "방향": direction,
            "확신도": rec.get("confidence") or "낮음",
            "참고점수": float(score) if is_number(score) else None,
        })

    priority = {"매수 검토": 0, "보유 검토": 1, "관망": 2, "매도 검토": 3}
    rows.sort(key=lambda row: (priority.get(str(row.get("매매 검토")), 9), -(row.get("참고점수") or 0)))
    table = pd.DataFrame(rows)
    if not table.empty:
        st.dataframe(
            table,
            width="stretch",
            hide_index=True,
            column_config={
                "참고점수": st.column_config.NumberColumn("참고점수", format="%+.2f"),
            },
        )

    selected = next((rec for rec in recommendations if str(rec.get("symbol")) == str(selected_symbol)), None)
    if selected:
        with st.expander("현재 선택 종목의 전체 비교 근거"):
            st.markdown(
                f"**{label(selected_symbol)} · {selected.get('stance') or '관망'} · "
                f"{selected.get('direction') or '혼조·중립'} · 확신도 {selected.get('confidence') or '낮음'}**"
            )
            for reason in selected.get("reasons") or []:
                st.write(f"• 우호 근거 · {reason}")
            for counter in selected.get("counterpoints") or []:
                st.write(f"• 경계 요인 · {counter}")

    st.caption(
        f"전체 비교 생성 {brief.get('created') or '시각 미제공'} · 같은 시점의 데이터로 종목 간 상대적인 검토 방향을 비교합니다."
    )


def render_ai_research_dashboard(active_symbols):
    st.markdown('<div class="eyebrow">AI STOCK RESEARCH</div>', unsafe_allow_html=True)
    st.title("AI 종합분석")
    st.markdown(
        '<div class="intro">관심·보유 종목 전체의 매매 검토와 선택 종목의 이슈·섹터·가격·뉴스·보유 상태를 한 화면에서 자세히 분석합니다.</div>',
        unsafe_allow_html=True,
    )
    selection = st.selectbox("종목 선택", options=active_symbols, format_func=label, key="sector_selection")
    known, profile, kind, currency, q = selection_context(selection)

    header_cols = st.columns([3, 1])
    header_cols[0].caption("오늘의 이슈는 시장 전체를 빠르게 보고, 이 화면에서는 전체 종목 비교와 선택 종목 상세 분석을 함께 확인합니다.")
    if header_cols[1].button("분석 새로고침", width="stretch", key="research_refresh"):
        history_cached.clear(); news_cached.clear(); market_brief_cached.clear(); fund_cached.clear(); quote_cached.clear()
        st.session_state.pop("research_ai_result", None)
        st.rerun()

    with st.spinner("선택 종목의 이슈·가격·뉴스·섹터 자료를 함께 분석하고 있습니다…"):
        history, history_error = history_cached(selection)
        summary = md.summary_from_history(history) if history is not None and not history.empty else None
        news = news_cached(selection, known.get("name") or profile.get("name") or selection)
        market = market_brief_cached()
        fund = None
        fund_symbol = None
        if kind == "etf" or selection == "^GSPC":
            fund_symbol = "VOO" if selection == "^GSPC" else selection
            fund = fund_cached(fund_symbol)
        position = st.session_state.positions.get(selection)
        evaluated_position = pf.evaluate_position(position, q) if position else None
        snapshot = {
            "symbol": selection,
            "name": known.get("name") or profile.get("name") or selection,
            "kind": kind,
            "sector": profile.get("sector"),
            "industry": profile.get("industry"),
            "quote": q,
            "analysis": summary,
            "position": evaluated_position,
            "news": news,
            "fund_sectors": (fund or {}).get("sectors") or {},
            "fund_composition": {
                "symbol": fund_symbol,
                "is_proxy": selection == "^GSPC",
                "sectors": (fund or {}).get("sectors") or {},
                "asof": (fund or {}).get("asof"),
            } if fund_symbol else None,
            "market_context": {
                "sample_size": int(market.get("sample_size") or len(market.get("items") or [])),
                "domestic_topics": (market.get("domestic") or {}).get("topics") or [],
                "overseas_topics": (market.get("overseas") or {}).get("topics") or [],
            },
        }
        result, warning = cai.generate_issue_stock_review(snapshot, market)

    if result is None:
        st.warning(warning or "종합분석을 만들지 못했습니다.")
        return

    # 가장 중요한 판단을 화면 최상단에 고정한다.
    st.markdown(_research_hero_html(result), unsafe_allow_html=True)
    st.caption(
        f"현재 자료 기준 · 시장 이슈 표본 {int(result.get('sample_size') or 0)}건 · 종목 뉴스 {int(result.get('stock_news_count') or 0)}건 · "
        "매매 검토와 방향 전망은 참고용이며 미래 가격을 보장하지 않습니다."
    )
    if warning:
        st.info(warning)
    if history_error:
        st.info("가격 이력 일부를 가져오지 못해 이용 가능한 자료 중심으로 분석했습니다.")

    with st.container(border=True):
        st.markdown("**핵심 결론**")
        st.write(result.get("summary") or "분석 요약이 없습니다.")
        qcols = st.columns(3)
        qcols[0].metric("현재 가격", fmt_price(q.get("price"), currency, kind), delta_color="off")
        qcols[1].metric("당일 등락", f"{float(q.get('change_pct')):+.2f}%" if is_number(q.get("change_pct")) else "—", delta_color="off")
        qcols[2].metric("종목 뉴스 방향", result.get("news_direction") or "혼재")
        if evaluated_position:
            st.caption(
                "내 보유 기준 · "
                + (f"평가수익률 {float(evaluated_position.get('return_pct')):+.2f}%" if is_number(evaluated_position.get("return_pct")) else "평가수익률 계산 불가")
            )

    st.divider()
    _render_all_symbol_review(active_symbols, selection)
    st.divider()

    st.subheader("선택 종목 판단 점수 구성")
    _render_research_score_chart(result)
    st.caption("점수는 서로 다른 성격의 자료를 비교하기 위한 내부 참고척도입니다. +는 우호적, -는 부담 요인이 상대적으로 많다는 뜻입니다.")

    st.subheader("가격 추세와 기술지표")
    _render_research_price_chart(history, summary, currency, kind)

    _render_research_issue_detail(result)
    _render_research_sector_detail(selection, profile, kind, fund)

    st.subheader("종목 뉴스")
    ncols = st.columns(3)
    ncols[0].metric("긍정 표현 기사", int(result.get("news_positive_count") or 0), delta_color="off")
    ncols[1].metric("부정·경계 표현 기사", int(result.get("news_negative_count") or 0), delta_color="off")
    ncols[2].metric("중립·혼재 기사", int(result.get("news_neutral_count") or 0), delta_color="off")
    render_news(news, limit=8)

    _render_research_detailed_reasoning(result)
    snapshot["issue_review"] = result
    _render_research_extra_ai(selection, snapshot)

    st.caption(
        "상승/하락 전망은 오늘 이슈·섹터 노출·최근 가격·종목 뉴스의 현재 방향을 요약한 시나리오입니다. "
        "실적 발표, 공시, 정책 변화, 장중 급변 등 새로운 정보가 나오면 판단이 달라질 수 있습니다."
    )

def render_stock_news_dashboard(active_symbols):
    st.markdown('<div class="eyebrow">NEWS</div>', unsafe_allow_html=True)
    st.title("종목 뉴스")
    st.markdown('<div class="intro">선택한 종목과 관련된 최근 뉴스를 출처·발행 시각과 함께 확인합니다.</div>', unsafe_allow_html=True)
    selection = st.selectbox("종목 선택", options=active_symbols, format_func=label, key="news_selection")
    known, profile, kind, currency, q = selection_context(selection)
    if st.button("이 종목 뉴스 새로고침", key="stock_news_refresh"):
        news_cached.clear()
        if hasattr(nd, "clear_caches"):
            nd.clear_caches()
        st.rerun()
    with st.spinner("관련 뉴스의 제목·출처·발행 시각을 확인하고 있습니다…"):
        news = news_cached(selection, known.get("name") or profile.get("name") or selection)
    render_news(news)
    st.caption("연관 뉴스 검색 결과에는 시장·산업 전반의 기사가 섞일 수 있습니다. 가격 변동 원인은 기사 제목만으로 확정하지 않습니다.")


def render_stock_ai_dashboard(active_symbols):
    st.markdown('<div class="eyebrow">STOCK AI</div>', unsafe_allow_html=True)
    st.title("종목 AI 분석")
    st.markdown('<div class="intro">선택한 종목의 가격·기술지표·뉴스·내 보유 수익률을 함께 읽는 참고 분석입니다.</div>', unsafe_allow_html=True)
    selection = st.selectbox("종목 선택", options=active_symbols, format_func=label, key="ai_selection")
    known, profile, kind, currency, q = selection_context(selection)
    df, summary = analysis_for(selection)
    st.subheader("수치로 확인하는 분석 노트")
    if summary:
        for fact in summary.get("facts", []):
            st.write(f"• {fact}")
        st.caption(f"분석 기준일: {display_time(summary.get('asof'), True)} · {summary.get('basis', '제공자 종가')}")
    with st.spinner("분석에 사용할 관련 뉴스를 확인하고 있습니다…"):
        news = news_cached(selection, known.get("name") or profile.get("name") or selection)
    with st.expander(f"이번 분석에 사용할 뉴스 {len(news.get('items') or [])}건"):
        render_news(news)

    question = st.text_input("궁금한 점", value="최근 뉴스와 가격 상승·하락을 함께 해석하고, 내 수익률 기준에서 매수·매도를 검토할 요소를 알려줘.", max_chars=600, key="stock_ai_question")
    has_data = bool((summary or {}).get("asof") or is_number(q.get("price")) or news.get("items"))

    if CLOUD_MODE:
        st.caption("클라우드 기본판은 API 키 없는 규칙 기반 자동 분석입니다. 자유로운 생성형 LLM 답변과는 다릅니다.")
        if st.button("종목 자동 분석 만들기", type="primary", disabled=not has_data, key="stock_cloud_ai_generate"):
            position = st.session_state.positions.get(selection)
            snapshot = {
                "symbol": selection, "name": known.get("name") or profile.get("name"),
                "quote": q, "sector": profile.get("sector"), "industry": profile.get("industry"),
                "analysis": summary, "requested_at": datetime.now(KST).isoformat(),
                "position": pf.evaluate_position(position, q) if position else None,
                "news": news,
                "limits": "시세·뉴스·완료 일봉의 기준 시각은 다를 수 있음. 비용·세금·배당·환율은 미반영. 사용자 검토 기준은 최적 매매 지점이 아님.",
            }
            answer, error = cai.explain_snapshot(snapshot, question)
            if error:
                st.info(error)
            if answer:
                st.session_state.ai_result = {"symbol": selection, "model": "API 없는 클라우드 자동 분석", "created": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"), "text": answer, "asof": (summary or {}).get("asof"), "quote_asof": q.get("asof"), "news_sources": news.get("items") or [], "position_snapshot": snapshot["position"]}
                st.rerun()
    else:
        if st.button("설치된 로컬 모델 확인", key="stock_ai_model_check"):
            models, model_error = list_local_models()
            st.session_state.local_models = models
            st.session_state.local_model_error = model_error
        models = st.session_state.get("local_models", [])
        if st.session_state.get("local_model_error"):
            st.info(st.session_state.local_model_error)
        if models:
            model = st.selectbox("사용할 모델", models, key="stock_ai_model")
            if st.button("AI 분석 노트 만들기", type="primary", disabled=not has_data, key="stock_ai_generate"):
                position = st.session_state.positions.get(selection)
                snapshot = {
                    "symbol": selection, "name": known.get("name") or profile.get("name"),
                    "quote": q, "sector": profile.get("sector"), "industry": profile.get("industry"),
                    "analysis": summary, "requested_at": datetime.now(KST).isoformat(),
                    "position": pf.evaluate_position(position, q) if position else None,
                    "news": news,
                    "limits": "시세·뉴스·완료 일봉의 기준 시각은 다를 수 있음. 비용·세금·배당·환율은 미반영. 사용자 검토 기준은 최적 매매 지점이 아님.",
                }
                if kind == "etf" or selection == "^GSPC":
                    fund_symbol = "VOO" if selection == "^GSPC" else selection
                    fund = fund_cached(fund_symbol)
                    snapshot["fund_composition"] = {"symbol": fund_symbol, "is_proxy": selection == "^GSPC", "sectors": fund.get("sectors"), "asof": fund.get("asof"), "fetched_at": fund.get("fetched_at"), "error": fund.get("error")}
                with st.spinner("로컬 모델이 제공된 수치를 읽고 있습니다…"):
                    answer, error = explain_snapshot(model, snapshot, question)
                if error:
                    st.warning(error)
                if answer:
                    st.session_state.ai_result = {"symbol": selection, "model": model, "created": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"), "text": answer, "asof": (summary or {}).get("asof"), "quote_asof": q.get("asof"), "news_sources": news.get("items") or [], "position_snapshot": snapshot["position"]}
                    st.rerun()
        else:
            if DESKTOP_MODE:
                st.info("생성형 분석을 처음 사용한다면 Ollama를 설치·실행한 뒤 배포 폴더의 AI_MODEL_SETUP.cmd를 실행하세요.")
            else:
                st.code("ollama pull qwen3:4b", language="bash")
            st.link_button("Ollama 설치 안내", "https://ollama.com/download")

    result = st.session_state.get("ai_result")
    if result and result["symbol"] == selection:
        with st.container(border=True):
            st.caption(f"저장된 분석 · {result['model']} · 생성 {result['created']}")
            st.markdown(result["text"])
            with st.expander("이 설명에 사용된 뉴스 원문 링크"):
                for source in result.get("news_sources", []):
                    st.link_button(f"[{source['id']}] {source['title']}", source["url"])
                    st.caption(f"{source.get('publisher') or ''} · {display_time(source.get('published_at'))}")
            st.caption("참고용 분석입니다. 가격·뉴스·보유 정보가 변경되면 필요할 때 다시 생성하세요.")


if "watch_symbols" not in st.session_state:
    st.session_state.watch_symbols = read_watchlist()
if "watch_meta" not in st.session_state:
    st.session_state.watch_meta = read_watchlist_meta()
    for _symbol, _item in st.session_state.watch_meta.items():
        KNOWN[_symbol] = _item
if "positions" not in st.session_state:
    if CLOUD_MODE:
        raw_positions = dict((CLOUD_STATE or {}).get("positions") or {})
        cleaned, errors = {}, []
        for _symbol, _row in raw_positions.items():
            try:
                validated = pf.validate_position(_row)
                if validated["symbol"] == md.normalize_symbol(_symbol):
                    cleaned[validated["symbol"]] = validated
            except (ValueError, TypeError) as exc:
                errors.append(str(exc))
        st.session_state.positions = cleaned
        st.session_state.portfolio_load_error = None
        if errors:
            st.session_state.cloud_storage_warning = "일부 저장된 보유정보 형식이 올바르지 않아 제외했습니다."
    else:
        st.session_state.positions, st.session_state.portfolio_load_error = pf.load_portfolio(portfolio_path())
if "available_symbols" not in st.session_state:
    st.session_state.available_symbols = list(dict.fromkeys([*KNOWN, *st.session_state.watch_symbols]))
if "pending_symbol" in st.session_state:
    pending = st.session_state.pop("pending_symbol")
    if pending not in st.session_state.watch_symbols:
        st.session_state.watch_symbols = [*st.session_state.watch_symbols, pending]

DASHBOARDS = [
    "🏠 오늘의 이슈",
    "🧠 AI 종합분석",
    "📊 관심종목 시세",
    "💼 보유·수익률",
    "📈 가격 차트",
]

with st.sidebar:
    if CLOUD_MODE:
        st.success("☁️ iPhone 클라우드 모드")
        st.caption("보유정보·관심종목은 이 브라우저의 로컬 저장소에 보관합니다.")
        st.caption("메뉴가 닫혀 있으면 화면 왼쪽 위 메뉴 아이콘으로 다시 열 수 있습니다.")
    elif MOBILE_MODE:
        st.success("📱 iPhone 접속 모드")
        st.caption(f"현재 데이터: {current_profile()['name']}")
        if st.button("데이터 프로필 바꾸기", width="stretch"):
            clear_profile_session(include_profile=True)
            st.rerun()
        st.caption("메뉴가 닫혀 있으면 화면 왼쪽 위의 ≫ 또는 메뉴 아이콘으로 다시 열 수 있습니다.")
    else:
        st.caption(f"데이터: {current_profile()['name']}")
    st.markdown("## 📊 대시보드")
    if st.session_state.get("dashboard_page") not in DASHBOARDS:
        st.session_state.dashboard_page = "🏠 오늘의 이슈"
    dashboard = st.radio("화면 선택", DASHBOARDS, index=0, label_visibility="collapsed", key="dashboard_page")
    st.caption("처음 실행하면 ‘오늘의 이슈’가 메인 화면으로 열립니다.")
    st.divider()
    st.markdown("### 나의 관심종목")
    symbols = st.multiselect("모아볼 종목", options=st.session_state.available_symbols,
                             key="watch_symbols", format_func=label, max_selections=12)
    st.caption("종목명·ETF명·티커로 검색한 뒤 후보를 선택해 추가할 수 있습니다.")
    with st.form("search_symbol", clear_on_submit=False):
        search_query = st.text_input("종목 검색", placeholder="예: 삼성전자, 하이닉스, NVIDIA, QQQ, 005930.KS")
        search_clicked = st.form_submit_button("검색", width="stretch")
    if search_clicked:
        with st.spinner("종목을 검색하고 있습니다…"):
            st.session_state.instrument_search = instrument_search_cached(search_query.strip())
    search_state = st.session_state.get("instrument_search") or {}
    search_items = search_state.get("items") or []
    if search_items:
        by_symbol = {item["symbol"]: item for item in search_items}
        selected_search_symbol = st.selectbox(
            "검색 결과", options=list(by_symbol),
            format_func=lambda s: search_result_label(by_symbol[s]), key="selected_search_symbol",
        )
        if st.button("선택한 종목 추가", width="stretch"):
            value = selected_search_symbol
            if len(symbols) >= 12 and value not in symbols:
                st.warning("한 번에 최대 12개까지 표시합니다.")
            else:
                item = search_item_to_known(by_symbol[value])
                KNOWN[value] = item
                st.session_state.watch_meta[value] = item
                if value not in st.session_state.available_symbols:
                    st.session_state.available_symbols.append(value)
                st.session_state.pending_symbol = value
                st.session_state.instrument_search = {}
                st.rerun()
    elif search_state.get("error"):
        st.caption(search_state["error"])
    with st.expander("티커 코드를 직접 알고 있다면"):
        with st.form("direct_symbol", clear_on_submit=True):
            direct_symbol = st.text_input("티커 직접 추가", placeholder="예: 005930.KS, AAPL, SPY, ^IXIC")
            direct_clicked = st.form_submit_button("티커 추가", width="stretch")
        if direct_clicked:
            try:
                value = md.normalize_symbol(direct_symbol)
            except ValueError as exc:
                st.warning(str(exc))
            else:
                if len(symbols) >= 12 and value not in symbols:
                    st.warning("한 번에 최대 12개까지 표시합니다.")
                else:
                    if value not in st.session_state.available_symbols:
                        st.session_state.available_symbols.append(value)
                    st.session_state.pending_symbol = value
                    st.rerun()
    if st.button("관심종목 저장", width="stretch"):
        meta = {s: st.session_state.watch_meta[s] for s in symbols if s in st.session_state.watch_meta}
        if CLOUD_MODE:
            error = cstore.save_watchlist(list(symbols), meta)
            if error:
                st.warning(error)
            else:
                st.success("이 iPhone/Safari의 브라우저 저장소에 관심종목을 저장했습니다.")
        else:
            try:
                temporary = settings_path().with_suffix(".tmp")
                temporary.write_text(json.dumps({"symbols": symbols, "meta": meta}, ensure_ascii=False, indent=2), encoding="utf-8")
                temporary.replace(settings_path())
                st.success("다음 실행에도 같은 종목을 불러옵니다.")
            except OSError as exc:
                st.error(f"저장하지 못했습니다: {type(exc).__name__}")
    st.divider()
    st.markdown("### 데이터")
    auto = st.toggle("가격 자동 갱신", value=True)
    refresh_minutes = st.select_slider("조회 간격", options=[1, 5, 10], value=5, format_func=lambda v: f"{v}분")
    st.caption("자동 갱신 설정은 시세 대시보드에서 사용합니다. 거래소·제공자의 시세 지연은 별도로 적용됩니다.")
    if st.button("자료 새로고침", width="stretch"):
        quote_cached.clear(); quotes_batch_cached.clear(); profile_cached.clear(); history_cached.clear(); fund_cached.clear(); news_cached.clear(); market_brief_cached.clear()
        if hasattr(md, "clear_caches"):
            md.clear_caches()
        if hasattr(nd, "clear_caches"):
            nd.clear_caches()
        st.rerun()
    st.divider()
    st.caption("시세 · Yahoo Finance / yfinance\n\n국내 주식 · 제공자 안내상 20분 지연\n\n표시 시각 · 한국 시간(KST)")
    if CLOUD_MODE:
        with st.expander("iPhone 홈 화면에 추가"):
            st.caption("Safari에서 공유 → ‘홈 화면에 추가’ → ‘웹 앱으로 열기’를 켜면 앱처럼 사용할 수 있습니다.")
            st.caption("PC나 같은 Wi-Fi가 필요하지 않습니다. 인터넷 연결만 있으면 접속할 수 있습니다.")
        with st.expander("iPhone 데이터 백업·복원"):
            st.caption("Safari의 사이트 데이터가 삭제되면 브라우저 저장정보도 사라질 수 있어 가끔 백업하는 것이 좋습니다.")
            st.download_button("내 데이터 JSON 백업", data=cstore.export_json(), file_name="stock_ai_iphone_backup.json", mime="application/json", width="stretch")
            uploaded_backup = st.file_uploader("백업 JSON 복원", type=["json"], key="cloud_backup_upload")
            if uploaded_backup is not None and st.button("이 백업으로 복원", width="stretch", key="cloud_backup_restore"):
                error = cstore.import_json(uploaded_backup.getvalue())
                if error:
                    st.error(error)
                else:
                    for key in ("watch_symbols", "watch_meta", "positions", "available_symbols"):
                        st.session_state.pop(key, None)
                    st.success("백업을 복원했습니다.")
                    st.rerun()
    elif MOBILE_MODE:
        with st.expander("iPhone 홈 화면에 추가"):
            st.caption("Safari에서 공유 버튼 → ‘홈 화면에 추가’ → 가능하면 ‘웹 앱으로 열기’를 켜면 앱처럼 열 수 있습니다.")
            st.caption("PC의 MOBILE_START.cmd와 같은 Wi-Fi 연결이 필요하며, PC를 끄면 iPhone에서도 접속할 수 없습니다.")
    if DESKTOP_MODE:
        with st.expander("내 데이터와 앱 종료"):
            st.caption(f"현재 프로필: {current_profile()['name']}")
            st.caption("프로필별 관심종목과 보유 정보는 서로 다른 폴더에 저장됩니다.")
            st.code(str(profile_root()), language=None)
            if MOBILE_MODE:
                st.caption("PC 기본 데이터는 기존 데이터 폴더를 사용하고, iPhone/추가 프로필은 profiles 하위 폴더에 따로 저장됩니다.")
            st.caption("앱을 완전히 종료하려면 배포 폴더의 STOP.cmd를 실행하세요.")

if st.session_state.get("cloud_storage_warning"):
    st.warning(st.session_state.cloud_storage_warning)
if CLOUD_MODE and not _cloud_secret("APP_PIN"):
    st.caption("현재 클라우드 앱에 접속 PIN이 설정되지 않았습니다. 개인 배포라면 Streamlit Secrets의 APP_PIN 설정을 권장합니다.")

if st.session_state.get("position_notice"):
    st.success(st.session_state.pop("position_notice"))
if st.session_state.get("portfolio_load_error"):
    st.warning(st.session_state.portfolio_load_error)

active_symbols = list(dict.fromkeys([*symbols, *st.session_state.positions]))
if not active_symbols and dashboard != "🏠 오늘의 이슈":
    st.info("왼쪽에서 관심종목을 하나 이상 선택해 주세요. 오늘의 이슈 화면은 종목 없이도 볼 수 있습니다.")
    st.stop()

if dashboard == "🏠 오늘의 이슈":
    render_today_issue_dashboard(active_symbols)
elif dashboard == "🧠 AI 종합분석":
    render_ai_research_dashboard(active_symbols)
elif dashboard == "📊 관심종목 시세":
    @st.fragment(run_every=refresh_minutes * 60 if auto else None)
    def _auto_price_dashboard():
        render_quotes_dashboard(active_symbols)
    _auto_price_dashboard()
elif dashboard == "💼 보유·수익률":
    render_portfolio_dashboard(active_symbols)
elif dashboard == "📈 가격 차트":
    render_price_dashboard(active_symbols)

st.divider()
st.caption("개인 학습·연구용 · 매매 검토 표시는 참고 자료입니다. 가격·뉴스는 누락·지연될 수 있으며, AI 해석은 판단 근거와 원문을 함께 확인해 주세요.")
