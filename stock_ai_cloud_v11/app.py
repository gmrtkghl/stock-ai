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
elif dashboard == "🤖 AI 매매 검토":
    render_ai_summary_dashboard(active_symbols)
elif dashboard == "📊 관심종목 시세":
    @st.fragment(run_every=refresh_minutes * 60 if auto else None)
    def _auto_price_dashboard():
        render_quotes_dashboard(active_symbols)
    _auto_price_dashboard()
elif dashboard == "💼 보유·수익률":
    render_portfolio_dashboard(active_symbols)
elif dashboard == "📈 가격 차트":
    render_price_dashboard(active_symbols)
elif dashboard == "🧭 섹터·ETF 구성":
    render_sector_dashboard(active_symbols)
elif dashboard == "📰 종목 뉴스":
    render_stock_news_dashboard(active_symbols)
else:
    render_stock_ai_dashboard(active_symbols)

st.divider()
st.caption("개인 학습·연구용 · 매매 검토 표시는 참고 자료입니다. 가격·뉴스는 누락·지연될 수 있으며, AI 해석은 판단 근거와 원문을 함께 확인해 주세요.")
