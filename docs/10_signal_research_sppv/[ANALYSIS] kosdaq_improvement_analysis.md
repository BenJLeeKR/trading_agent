# KOSDAQ 종목 편입 관련 현황 분석 및 개선 사항

작성일: 2026-06-18

## 1. 현재 KOSDAQ 종목 매매 가능 여부 (현황)
질문하신 대로 **현재 시스템 상태에서는 KOSDAQ 종목을 매매할 수 없습니다.**
*   `trading.instruments` 테이블에 동기화된 종목 수는 현재 951개로, 이는 KOSPI(유가증권시장) 활성 종목 수와 일치합니다.
*   만약 외부 이벤트(OpenDART 등)나 오버레이 로직에 의해 KOSDAQ 종목이 일시적으로 후보군에 오르더라도, 마지막 `LiquidityFilter` 검사 단계에서 DB(`instruments` 테이블)에 종목 정보가 없는 `unknown_instrument`로 처리되어 최종 유니버스에서 강제 탈락됩니다.

## 2. KOSDAQ 편입을 위한 시스템 반영 현황 (관련 프로그램 확인)
KOSDAQ 마스터 데이터를 CSV로 넣어 동기화(`sync_kis_instrument_master.py`)하는 것 자체는 현재 스크립트로도 바로 가능합니다. 하지만 **단순히 KOSDAQ 종목을 DB에 밀어넣으면 치명적인 부작용이 발생하도록 시스템 구조가 엮여 있습니다.**

**발견된 핵심 위험 요소:**
1.  **Core Universe 로직의 한계 (`universe_selection.py`)**
    *   현재 `_add_core_universe` 함수는 `instruments.list_active_by_market("KRX")`를 호출하여 **"활성화된 모든 종목"**을 Core Universe로 간주합니다.
    *   여기에 약 1,700개의 KOSDAQ 종목이 추가되면, Core 후보군이 총 2,600여 개로 늘어납니다. 앞서 파악했던 '알파벳(종목코드) 순 잘림 현상' 때문에, Core Universe는 우량주(KOSPI 100 등)가 아닌 '앞번호를 가진 KOSDAQ/KOSPI 소형주 20~30개'로만 영구적으로 채워지는 심각한 버그가 발생합니다.
2.  **Market Overlay 탐색 버그 (`universe_selection.py`)**
    *   현재 장중 수급/변동성 탐지기능인 `_add_market_overlay`는 전체 종목 중 **알파벳 순서로 상위 50개(pre-pool)**만 KIS API로 현재가를 조회하여 급등 여부를 판별합니다.
    *   KOSDAQ 종목이 대거 추가되면, 이 역시 앞번호 50개만 영원히 조회하게 되므로 시장 전체의 수급/모멘텀을 감지하는 Market Overlay의 본래 목적이 완전히 무력화됩니다.

## 3. 개선 및 선결 과제
KOSDAQ 종목을 안전하게 매매 대상(특히 Market-driven 또는 Event-driven 오버레이용)으로 포함하려면 다음 세 가지 개선이 반드시 선행되어야 합니다.

### 개선 과제 1: Core Universe 필터링 명확화
*   전체 활성 종목(`list_active_by_market`)을 Core Universe로 사용하는 현재 코드를 수정해야 합니다.
*   `instruments` 테이블의 `metadata`에 `is_core_universe: true` 속성을 부여하거나, KOSPI 100 등의 명시적 화이트리스트 테이블을 신설하여 **우량 대형주만 Core Universe로 선별**되게 해야 합니다.

### 개선 과제 2: KOSPI / KOSDAQ 식별 데이터 보강
*   현재 `sync_kis_instrument_master.py`는 모든 종목의 `market_code`를 `KRX`로 통일하고 있습니다.
*   CSV 파싱 시 KOSPI와 KOSDAQ을 구분할 수 있도록 `metadata.exchange_code` (또는 별도 필드)를 명확히 기록하여, 추후 에이전트나 필터가 KOSDAQ 여부를 인지할 수 있게 해야 합니다.

### 개선 과제 3: Market Overlay Pre-pool 생성 방식 개편
*   알파벳 순 50개를 잘라서 현재가를 조회하는 로직을 폐기해야 합니다.
*   KIS의 **'거래량 급등 API' 또는 '순위 분석 API'**를 직접 연동하여 1차 후보군을 가져오거나, KOSDAQ/KOSPI를 망라하여 사전에 필터링된 모멘텀 풀(예: 직전 5일 거래대금 상위 N개)만 50개 추려서 조회하도록 `_add_market_overlay` 로직을 고도화해야 합니다.

---
**결론:**
질문하신 대로 현재 KOSDAQ 종목 정보가 없어 매매가 불가능한 것이 맞습니다. 다만, KOSDAQ 데이터를 DB에 넣기 전에 **Core Universe 강제 편입 문제와 Market Overlay의 알파벳 순 자르기 버그를 먼저 수정**해야만 자동매매 시스템이 오작동(소형/잡주 무한 매수)하는 것을 막을 수 있습니다.
