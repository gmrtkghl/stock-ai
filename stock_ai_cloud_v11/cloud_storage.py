"""Browser-local persistence for the cloud/iPhone edition.

The durable copy lives in the browser's localStorage. Streamlit Community Cloud's
server filesystem is intentionally not used for portfolio persistence.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

import streamlit as st

try:
    from streamlit_local_storage import LocalStorage
except Exception:  # dependency is installed by Community Cloud from requirements.txt
    LocalStorage = None

STORAGE_KEY = "stock_ai_cloud_v11_state"
SCHEMA_VERSION = 1
DEFAULT_SYMBOLS = ["005930.KS", "000660.KS", "GOOGL", "NVDA", "QQQ", "^GSPC"]
_SYMBOL_RE = re.compile(r"[A-Z0-9^][A-Z0-9.^=\-]{0,23}\Z")


def _default() -> dict:
    return {"schema_version": SCHEMA_VERSION, "watchlist": {"symbols": DEFAULT_SYMBOLS.copy(), "meta": {}}, "positions": {}}


def _parse(raw: Any) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return _default()
    if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
        return _default()
    watch = raw.get("watchlist") if isinstance(raw.get("watchlist"), dict) else {}
    symbols = watch.get("symbols") if isinstance(watch.get("symbols"), list) else DEFAULT_SYMBOLS.copy()
    symbols = [x for x in symbols if isinstance(x, str) and _SYMBOL_RE.fullmatch(x)][:12] or DEFAULT_SYMBOLS.copy()
    meta = watch.get("meta") if isinstance(watch.get("meta"), dict) else {}
    positions = raw.get("positions") if isinstance(raw.get("positions"), dict) else {}
    return {"schema_version": SCHEMA_VERSION, "watchlist": {"symbols": list(dict.fromkeys(symbols)), "meta": meta}, "positions": positions}


def _manager():
    if LocalStorage is None:
        return None
    if "_stock_ai_local_storage_manager" not in st.session_state:
        st.session_state._stock_ai_local_storage_manager = LocalStorage()
    return st.session_state._stock_ai_local_storage_manager


def load_state() -> tuple[dict, str | None]:
    if "_stock_ai_cloud_state" in st.session_state:
        return _parse(st.session_state._stock_ai_cloud_state), st.session_state.get("_stock_ai_cloud_storage_warning")
    manager = _manager()
    if manager is None:
        state = _default()
        st.session_state._stock_ai_cloud_state = state
        warning = "브라우저 저장 구성요소를 불러오지 못해 현재 세션에서만 데이터가 유지됩니다."
        st.session_state._stock_ai_cloud_storage_warning = warning
        return state, warning
    try:
        raw = manager.getItem(STORAGE_KEY, key="_stock_ai_cloud_load_component")
        if raw is None:
            raw = st.session_state.get("_stock_ai_cloud_load_component")
        if raw is None:
            # The browser component may need one render cycle before returning.
            # Do not cache an empty default here, so a component-triggered rerun can
            # still load an existing iPhone value.
            return _default(), None
        state = _parse(raw)
        st.session_state._stock_ai_cloud_state = state
        return state, None
    except Exception as exc:
        state = _default()
        st.session_state._stock_ai_cloud_state = state
        warning = f"브라우저 저장소를 읽지 못해 현재 세션 데이터로 시작했습니다. ({type(exc).__name__})"
        st.session_state._stock_ai_cloud_storage_warning = warning
        return state, warning


def save_state(state: dict) -> str | None:
    state = _parse(state)
    st.session_state._stock_ai_cloud_state = state
    manager = _manager()
    if manager is None:
        return "브라우저 저장 구성요소가 없어 현재 세션에서만 저장되었습니다."
    try:
        manager.setItem(STORAGE_KEY, json.dumps(state, ensure_ascii=False, separators=(",", ":")))
        # streamlit-local-storage is a browser component; give the frontend a brief
        # opportunity to commit before callers immediately st.rerun().
        time.sleep(0.35)
        return None
    except Exception as exc:
        return f"iPhone 브라우저 저장소에 저장하지 못했습니다. ({type(exc).__name__})"


def watchlist() -> tuple[list[str], dict, str | None]:
    state, warning = load_state()
    watch = state["watchlist"]
    return list(watch["symbols"]), dict(watch.get("meta") or {}), warning


def save_watchlist(symbols: list[str], meta: dict) -> str | None:
    state, _ = load_state()
    state["watchlist"] = {"symbols": symbols, "meta": meta}
    return save_state(state)


def positions() -> tuple[dict, str | None]:
    state, warning = load_state()
    return dict(state.get("positions") or {}), warning


def save_positions(positions_value: dict) -> str | None:
    state, _ = load_state()
    state["positions"] = positions_value
    return save_state(state)


def export_json() -> str:
    state, _ = load_state()
    return json.dumps(state, ensure_ascii=False, indent=2)


def import_json(raw: bytes | str) -> str | None:
    try:
        text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else str(raw)
        payload = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return "가져올 JSON 파일 형식을 확인해 주세요."
    state = _parse(payload)
    return save_state(state)
