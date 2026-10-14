# v0.6 GitHub 단일 업데이트 안내

`UPDATE.bat`를 실행하면 **전체 코드 파일을 GitHub에서 함께 갱신**하고 `app_data`/`.venv`를 보존합니다. 기존에 설치한 ZIP 패치를 하나씩 덮어쓰지 마세요. `release_manifest.json`의 SHA256으로 완전한 릴리스를 검증합니다.

# 쿠팡 소싱 탐색기 v0.5 — 공식 API 403 오류 진단 개선

## 먼저 알아둘 점

- 실행 주소: `http://127.0.0.1:8789` — 내 컴퓨터 전용 주소. 기존 순익 대시보드 8787과 분리.
- **직접 쿠팡 검색 1P 접근은 외부 검사에서 HTTP 403 / 접근 불가**였습니다. 따라서 **검색·랭킹 자동 수집은 아직 미구현**입니다. 이를 우회하려는 코드는 없습니다.
- 공식 카테고리 API(`RFM`) 또는 계정에서 확보한 공식 카테고리 파일, 사용자 보유/허용된 순위 자료와 불사자 파일 분석은 준비돼 있습니다.
- 분석 결과의 `1페이지 매출`은 불사자 추정치이며, 같은 상품의 옵션 중복이 제거된 확정 매출이 아닙니다.

## Windows 설치 및 실행

1. ZIP을 **전체 압축 해제**합니다. 기존 설치 폴더에 덮어쓰는 경우 `app_data` 폴더는 **절대 지우지 마세요**.
2. Windows에 Python 3.10~3.13을 설치하고 PATH에 등록합니다.
3. `START.bat` 파일을 더블클릭하면 최초 실행 시 `.venv` 생성, 필수 패키지 설치, 서버 기동, 브라우저 열기를 순서대로 수행합니다. 설치 중에는 인터넷 연결이 필요합니다.
4. 브라우저 주소는 `http://127.0.0.1:8789`입니다.
5. 매번 Windows 로그인 때 서버를 자동 실행하려면 `AUTO_START_ON.bat`를 **한 번만** 실행합니다. 해제하려면 `AUTO_START_OFF.bat`.
6. 문제가 발생하면 `DIAGNOSE.bat`를 실행하고 `logs/launcher.log`, `logs/setup_stderr.log` 등을 확인합니다. Python 환경 없이도 실행기 오류 로그는 남습니다.

`127.0.0.1`은 공인 IP가 아니며, PC를 끄면 웹서버도 종료됩니다. 재부팅 시 자동 시작 여부를 확인하세요.

## 화면 사용 순서

1. **카테고리 필터:** 생활용품 최하위 카테고리 목록(RFM API/CSV/JSON/엑셀) 가져오기 → **적합/조건부/제외** 자동 판정. 대형/인증 위험/시즌 우선 제외. 오판일 때 수동 변경 가능.
2. **랭킹 40개 분석:** `적합` 카테고리만 대상으로 사용자 제공 상품 순위 CSV 업로드. 상품명·가격·리뷰 등으로 점수 및 메인키워드 추출. 미수집 자료는 **자료 부족** 표시.
3. **메인키워드 DB:** 발견 키워드 정리·중복 관리. CSV 내려받기.
4. **검색 1P 검증:** 발견 키워드 검증 대기열에 등록하고 URL을 열어 확인. **사용자 보유 불사자 v0.6 JSON**을 한꺼번에 업로드하면 요약과 `agGrids` 판매자 리스트가 함께 분석됨. 또는 허용된 키워드/순위 CSV 여러 개를 한 번에 수입.
5. **상품 소싱 판단:** 검색 1P 검증 유망 키워드만 1688에서 마진·부피·차별화 검토.

## 파일 업로드 형식

- 카테고리 JSON: 공식 `data` → `child` 중첩 구조. 또는 표준화된 카테고리 CSV/엑셀.
- 카테고리 상품: `sample_data/products_example.csv` (데모 카테고리용 가상 자료, 실제 시장 데이터 아님).
- 검색 1P 상품: `sample_data/search_1p_example.csv`. 열: `keyword,rank,title,product_id,price,reviews,delivery,estimated_sales,estimated_revenue,url`. 1~100위 허용, 1~40위 수집 여부 별도 표시. 데모 값은 시장평가에 사용하지 마세요.
- 불사자: 사용자 보유 기존 수집기 `records[].summary.fields`, `records[].agGrids[].rows[].cells` 구조를 지원. 상품 목록이 없다면 요약 지표만 수입.

## 데이터 안전성

- 모든 기록은 로컬 `app_data/sourcing.db`(SQLite WAL)에 저장됩니다.
- CSV/JSON 상품 파일을 다시 올려도 같은 키워드·동일 소스·동일 목록이면 중복 스냅샷을 생성하지 않습니다.
- 새 측정값은 날짜별로 보존하며, 시장 자료가 없으면 **미측정/추가 검증 필요**라고 표시합니다.
- 설정 메뉴의 **DB 백업**은 SQLite backup API를 사용하므로 WAL 자료까지 포함합니다.
- API 키는 비밀번호 입력 칸으로 받고 프로그램 DB에는 저장하지 않습니다. API 키·비밀번호를 ZIP, GitHub, 채팅에 넣지 마세요.

## 개발·테스트 결과

- 카테고리 트리의 3/4차 leaf 판정, 제외 규칙, 수동 예외, 40개 상품 점수화, 키워드 추출, 불사자 요약 파싱, 불사자 상품 목록 파싱, 다중 키워드 CSV 입력, 검색 URL 인코딩, DB 재실행·중복 방지를 Python 자동 테스트로 검증합니다.
- 개발환경에서 `python -m unittest discover -s tests -v`로 검증 (19개 테스트 통과). **실제 Windows BAT·브라우저·쿠팡 접근은 사용자 PC에서 마지막 확인 필요**합니다.
- 쿠팡 카테고리 공식 API 호출은 계정 Access/Secret Key가 없어 실제 응답 테스트 전 단계입니다.


## v0.5: 공식 RFM API HTTP 403 대응

**HTTP 403은 API 키 미입력 증거가 아니라 서버 측 접근 거부입니다.**

1. 오류 발생 시 API 조회를 10분간 멈추세요. 프로그램에서도 같은 세션에서 재조회 버튼을 10분간 비활성화합니다.
2. WING 로그인 → 추가판매정보/판매자정보 → OPEN API 키 발급·연동정보에서 발급 방식 확인. **연동업체 전용 키는 자체개발 프로그램에서 사용할 수 없습니다.** 이미 사용 중인 외부 셀러툴 연결을 바꾸면 해당 서비스가 중단될 수 있으므로 신중히 변경하세요.
3. 자체개발(직접입력) 방식이라면 https://www.findip.kr/ 에서 PC의 **외부 공인 IP**를 확인하여 등록된 IP와 비교. `127.0.0.1`이나 `192.168.x.x`는 등록 IP가 아닙니다.
4. 키 연동정보/IP를 변경했다면 쿠팡 시스템 반영 최대 30분 후 다시 시도합니다.
5. 빠르게 진행하려면 `1. 카테고리 필터 → 파일 가져오기`에서 공식 카테고리 Excel 파일을 사용하세요.

v0.5는 API 요청의 쿠팡 공식 HMAC 구성과 URL을 재검토하고, **압축된 403 오류 본문이 깨져 표시되던 문제**와 재시도 제한을 개선했습니다. IP 등록 및 보안 차단 자체를 해결하거나 우회하지는 않습니다. API 키/Secret Key를 채팅·로그·GitHub에 공유하지 마세요.

관련 쿠팡 공식 문서:
- https://developers.coupang.com/ko/faq/when-calling-the-api-a-403-forbidden-not-allowed-ip-error-occurs
- https://developers.coupang.com/ko/faq/how-to-resolve-sorry-access-denied-http-403-error-when-calling-coupang-openapi
- https://developers.coupang.com/ko/getting-started/issue-open-api-keynew

## 아직 남은 연결 작업

- 소비자용 쿠팡 카테고리 랭킹 40개 자동 수집: **허용된 실제 상품 정보 공급원 또는 사용자 접근 테스트 필요**.
- 실제 쿠팡 검색 1P 실시간 자동 조회: 현 개발 환경에서 403, **접근 허용 경로 확인 전 자동화 불가**.
- 구글 스프레드시트 앱 내부 직접 동기화: OAuth 또는 인증 구성 필요. 현재 채팅으로 업로드한 자료는 ChatGPT가 연결된 구글 시트에 기록 가능.
- Windows 실기기 재부팅/자동시작 검증.

기존 구글 소싱 DB: https://docs.google.com/spreadsheets/d/18D_zimerpl1km4reH-ExY_75TjM2M9D0dVtzKP7Oo5k/edit
