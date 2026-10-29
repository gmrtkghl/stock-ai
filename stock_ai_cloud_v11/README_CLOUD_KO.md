# 주식 리서치 노트 v11 · iPhone 독립 클라우드판

이 버전은 Windows PC를 서버로 사용하지 않습니다. 앱 코드를 Streamlit Community Cloud에 배포한 뒤 iPhone Safari에서 접속합니다.

## 목표 환경

- iPhone 14 이상
- Safari
- Wi-Fi / LTE / 5G 인터넷 연결
- PC 상시 실행 불필요
- Python / JupyterLab / Ollama 설치 불필요

## v10과 달라진 점

- PC의 `MOBILE_START.cmd`가 필요하지 않습니다.
- 보유수량, 평균 매수가, 관심종목은 iPhone Safari의 브라우저 localStorage에 저장합니다.
- Streamlit Community Cloud의 서버 파일에 개인 포트폴리오를 영구 저장하지 않습니다.
- 오늘 이슈, 국내/해외 이슈, 시세, 뉴스, 수익률, 섹터/ETF, 종목 검색 기능은 유지합니다.
- Ollama 대신 API 키 없이 작동하는 규칙 기반 자동 분석 엔진을 기본으로 사용합니다.
- 자동 분석은 생성형 LLM이 아니며, 가격/기술지표/헤드라인/사용자 기준을 구조화해서 검토하는 기능입니다.

## 배포 준비

1. GitHub 계정을 만듭니다.
2. 새 저장소(repository)를 만들고 이 폴더의 파일을 모두 업로드합니다.
3. Streamlit Community Cloud에 GitHub 계정으로 로그인합니다.
4. `Create app`을 선택합니다.
5. Repository와 branch를 선택하고 Main file path를 `streamlit_app.py`로 지정합니다.
6. Advanced settings의 Secrets에 다음처럼 개인 접속 PIN을 넣는 것을 권장합니다.

```toml
APP_PIN = "원하는-개인-PIN"
```

7. Deploy를 누릅니다.
8. 배포가 끝나면 `*.streamlit.app` 주소가 생성됩니다.

## iPhone에서 앱처럼 사용

1. iPhone Safari에서 배포 주소를 엽니다.
2. 공유 메뉴를 엽니다.
3. `홈 화면에 추가`를 선택합니다.
4. `웹 앱으로 열기` 옵션이 보이면 켭니다.
5. 홈 화면의 아이콘으로 실행합니다.

## 개인 데이터 저장 방식

관심종목과 보유정보는 서버의 `portfolio.json`이나 `watchlist.json`에 저장하지 않고 iPhone Safari의 localStorage에 저장합니다.

장점:
- 다른 방문자의 데이터와 섞이지 않습니다.
- Streamlit 서버 재부팅에 덜 영향을 받습니다.
- PC 데이터와 완전히 분리됩니다.

주의:
- Safari의 웹사이트 데이터/기록을 삭제하면 localStorage도 삭제될 수 있습니다.
- iPhone 교체 시 자동 이전을 보장하지 않습니다.
- 왼쪽 메뉴의 `iPhone 데이터 백업·복원`에서 JSON 백업 파일을 가끔 저장해 두는 것을 권장합니다.

## 자동 분석에 대하여

v11 기본판은 외부 LLM API 키가 없어도 동작하도록 설계했습니다.

자동 분석은 다음 자료를 합칩니다.
- 전 거래일 대비 등락률
- 20/60일 이동평균
- RSI
- 최근 20거래일 변화율
- 관련 뉴스 헤드라인의 단순 방향성 표현
- 내 평균 매수가 대비 수익률
- 내가 설정한 이익/손실/추가매수 검토 기준

결과는 `매수 검토 / 보유 검토 / 매도 검토 / 관망` 중 하나로 제한하고, 근거와 반대 가능성을 같이 표시합니다.

이는 투자 자문, 자동 주문, 목표가, 수익 보장이 아닙니다.

## 생성형 AI를 나중에 붙이고 싶다면

클라우드에서는 PC의 Ollama를 사용할 수 없습니다. 나중에 생성형 AI가 필요하면 별도의 LLM API를 Streamlit Secrets에 연결하는 방식으로 확장할 수 있습니다. 기본 기능은 API 없이 계속 사용할 수 있도록 분리되어 있습니다.

## 파일 설명

- `streamlit_app.py` : Streamlit Community Cloud 실행 파일
- `app.py` : 메인 화면
- `cloud_storage.py` : iPhone 브라우저 저장소 처리
- `cloud_analysis.py` : API 없는 자동 분석 엔진
- `market_data.py` : 시세/가격/섹터/ETF
- `market_brief.py` : 국내/해외 오늘 이슈
- `news_data.py` : 종목 뉴스
- `portfolio.py` / `portfolio_view.py` : 보유수익률/검토 기준
- `.streamlit/config.toml` : 모바일 친화 테마/서버 설정
- `requirements.txt` : 클라우드 의존성

## 알려진 제한

- Yahoo/Google News 공개 데이터는 지연, 누락, 일시적 차단이 있을 수 있습니다.
- 한국 주식 가격은 제공자 안내 기준 지연 시세일 수 있습니다.
- 뉴스 제목만으로 가격 변동의 원인을 확정하지 않습니다.
- 브라우저 localStorage는 사용자가 사이트 데이터를 삭제하면 사라질 수 있습니다.
- Streamlit Community Cloud의 무료 자원 정책이나 서비스 정책은 향후 변경될 수 있습니다.
