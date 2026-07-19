# 한국투자증권 오픈API 핵심 요약

원본 문서:
- `reference_docs/한국투자증권_오픈API_전체문서_20260503_030000.xlsx`

용도:
- Roo Code가 한국투자증권(KIS) 연동 구현 시 전체 엑셀 338개 시트를 처음부터 훑지 않도록, 자동매매 MVP에 직접 필요한 API만 추린 요약본이다.
- 이 문서는 구현용 네비게이션 문서다. 최종 구현 직전에는 반드시 원본 엑셀과 최신 공식 문서를 다시 확인해야 한다.

## 1. 문서 구조 평가

- 엑셀 파일 자체는 정상이다.
- 시트 수는 `338개`이며, 첫 시트 `API 목록`이 인덱스 역할을 한다.
- 각 API가 개별 시트로 분리되어 있고, 시트마다 다음 구조가 반복된다.
  - 기본정보
  - 개요
  - Layout
  - Request Header / Body or Query
  - Response Header / Body
  - Example
- 한글 텍스트는 정상 추출된다.
- 다만 구현자가 전체를 직접 읽기에는 과하므로, 주문/조회/실시간 관련 시트만 우선 사용해야 한다.

## 2. MVP 구현 시 우선 참고할 시트

### 인증 / 세션

- `접근토큰발급(P)`
- `접근토큰폐기(P)`
- `실시간 (웹소켓) 접속키 발급`

### 국내주식 주문 / 계좌

- `주식주문(현금)`
- `주식주문(정정취소)`
- `주식일별주문체결조회`
- `주식정정취소가능주문조회`
- `주식잔고조회`
- `매수가능조회`
- `매도가능수량조회`

### 국내주식 시세 / 호가 / 주문 이벤트

- `주식현재가 시세`
- `국내주식 실시간체결가 (KRX)`
- `국내주식 실시간호가 (KRX)`
- `국내주식 실시간체결통보`

## 3. 구현 우선순위 권장

1. OAuth 접근토큰 발급/폐기
2. WebSocket approval key 발급
3. 현금 주문
4. 주문 정정/취소
5. 일별 주문체결조회
6. 잔고/매수가능/매도가능 조회
7. 실시간 주문체결통보 구독
8. 실시간 체결가/호가 구독

이 순서가 맞는 이유:
- 주문 성공/실패보다 먼저 인증과 세션 수명이 안정돼야 한다.
- 주문 submit만 먼저 붙이면 unknown state가 생겼을 때 복구 경로가 약해진다.
- 조회 API와 실시간 주문통보를 함께 붙여야 reconciliation 경로를 만들 수 있다.

## 4. 인증 관련 핵심 요약

### 4.1 접근토큰발급(P)

- 통신방식: `REST`
- Method: `POST`
- URL: `/oauth2/tokenP`
- 실전 Domain: `https://openapi.koreainvestment.com:9443`
- 모의 Domain: `https://openapivts.koreainvestment.com:29443`

핵심 포인트:
- 접근토큰 유효기간은 일반 고객 기준 `1일`
- 재발급은 지나치게 자주 호출하면 신규 토큰 대신 직전 토큰을 재응답할 수 있음
- 응답에는 `access_token`, `token_type`, `expires_in`, `access_token_token_expired`가 포함됨
- 실제 호출 시 `Authorization: Bearer <token>` 형식 필요

구현 메모:
- 토큰 재발급은 single-flight 처리
- 만료 시각은 응답 본문의 `access_token_token_expired` 기준으로 저장
- 문서상 “1일 1회 발급 원칙”과 “일정시간 이내 재호출 시 기존 토큰 재응답”을 감안해 토큰 폭주를 막아야 함

### 4.2 접근토큰폐기(P)

- 통신방식: `REST`
- Method: `POST`
- URL: `/oauth2/revokeP`

용도:
- 명시적으로 토큰을 더 이상 사용하지 않을 때 폐기

### 4.3 실시간 (웹소켓) 접속키 발급

- 통신방식: `WEBSOCKET` 문맥이지만 실제 발급은 `POST`
- URL: `/oauth2/Approval`

핵심 포인트:
- 응답 `approval_key`를 WebSocket 구독 헤더에 사용
- 문서상 접속키 유효기간은 `24시간`
- 다만 WebSocket 연결 시 초기 1회 인증용이므로, 세션 유지 중이면 반복 발급이 필수는 아님

구현 메모:
- approval key 재발급 중 재구독 순서 보장 필요
- 토큰과 approval key의 생명주기를 분리 관리할 것

## 5. 주문 API 핵심 요약

### 5.1 주식주문(현금)

- API ID: `v1_국내주식-001`
- Method: `POST`
- URL: `/uapi/domestic-stock/v1/trading/order-cash`
- 실전 TR:
  - 매도 `TTTC0011U`
  - 매수 `TTTC0012U`
- 모의 TR:
  - 매도 `VTTC0011U`
  - 매수 `VTTC0012U`

핵심 요청 필드:
- Header
  - `authorization`
  - `appkey`
  - `appsecret`
  - `tr_id`
  - `custtype`
- Body
  - `CANO`
  - `ACNT_PRDT_CD`
  - `PDNO`
  - `ORD_DVSN`
  - `ORD_QTY`
  - `ORD_UNPR`
  - `SLL_TYPE` optional
  - `CNDT_PRIC` optional
  - `EXCG_ID_DVSN_CD` optional

핵심 응답 필드:
- `rt_cd`
- `msg_cd`
- `msg1`
- `output.KRX_FWDG_ORD_ORGNO`
- `output.ODNO`
- `output.ORD_TMD`

중요 주의사항:
- POST body key는 문서 기준 `대문자` 사용
- `ORD_QTY`, `ORD_UNPR` 등은 문자열로 전달
- 시장가 등 단가 없는 주문은 `ORD_UNPR = "0"` 규칙을 사용하는 게 안전
- 거래소 구분은 `KRX`, `NXT`, `SOR`가 존재하지만 모의투자는 `KRX` 중심으로 보는 것이 안전

자동매매 구현 시 해석:
- 내부 `client_order_id`와 KIS `ODNO`를 분리 저장해야 한다
- 응답 성공이 곧 최종 체결이 아니라 “주문 접수/전송” 단계임
- 이후 `주식일별주문체결조회` 또는 `실시간체결통보`로 상태를 닫아야 한다

### 5.2 주식주문(정정취소)

- API ID: `v1_국내주식-003`
- Method: `POST`
- URL: `/uapi/domestic-stock/v1/trading/order-rvsecncl`
- 실전 TR: `TTTC0013U`
- 모의 TR: `VTTC0013U`

핵심 요청 필드:
- `KRX_FWDG_ORD_ORGNO`
- `ORGN_ODNO`
- `ORD_DVSN`
- `RVSE_CNCL_DVSN_CD`
  - `01` 정정
  - `02` 취소
- `ORD_QTY`
- `ORD_UNPR`
- `QTY_ALL_ORD_YN`
- `CNDT_PRIC` optional
- `EXCG_ID_DVSN_CD` optional

문서상 중요한 운영 규칙:
- 이미 체결된 건은 정정/취소 불가
- 정정/취소 전에 `주식정정취소가능주문조회`로 가능수량(`psbl_qty`)을 먼저 확인 권장

자동매매 구현 시 해석:
- cancel/replace를 신규 주문이 아니라 원주문 연결 이벤트로 저장해야 함
- cancel timeout 시 취소 완료로 간주하면 안 됨
- 정정 실패 시 원주문 상태 재조회가 필요

## 6. 조회 / 복구 API 핵심 요약

### 6.1 주식일별주문체결조회

- API ID: `v1_국내주식-005`
- Method: `GET`
- URL: `/uapi/domestic-stock/v1/trading/inquire-daily-ccld`
- 실전 TR:
  - 3개월 이내 `TTTC0081R`
  - 3개월 이전 `CTSC9215R`
- 모의 TR:
  - 3개월 이내 `VTTC0081R`
  - 3개월 이전 `VTSC9215R`

핵심 포인트:
- 실전은 1회 최대 `100건`
- 모의는 1회 최대 `15건`
- `tr_cont`, `CTX_AREA_FK100`, `CTX_AREA_NK100`로 연속조회
- 장중 대량 조회는 지연 가능성이 있다고 문서가 경고함

자동매매 구현 시 해석:
- submit timeout 이후 1차 복구 조회 API 후보
- reconciliation budget을 반드시 별도 확보해야 함
- 대량 계좌/빈번한 조회에서는 polling 남용 금지

### 6.2 주식정정취소가능주문조회

- API ID: `v1_국내주식-004`
- Method: `GET`
- URL: `/uapi/domestic-stock/v1/trading/inquire-psbl-rvsecncl`

용도:
- 특정 주문이 정정/취소 가능한지 사전 확인

자동매매 구현 시 해석:
- cancel/replace 전 사전 검증 경로로 유용
- 원주문 남은 수량 검증에 사용

### 6.3 주식잔고조회

- API ID: `v1_국내주식-006`
- Method: `GET`
- URL: `/uapi/domestic-stock/v1/trading/inquire-balance`
- 실전 TR: `TTTC8434R`
- 모의 TR: `VTTC8434R`

문서상 주의사항:
- 실전은 1회 최대 `50건`
- 모의는 1회 최대 `20건`
- 연속조회 필요
- 제공 정보량이 많아 상대적으로 느린 API라고 명시
- 주문 준비용으로는 이 API보다 `매수가능조회` / `매도가능수량조회` TR을 권장한다고 문서에 직접 적혀 있음

자동매매 구현 시 해석:
- 실시간 주문 직전 핫패스에서 직접 남용하지 말 것
- reconciliation이나 정기 snapshot 용도로 쓰는 편이 안전

### 6.4 매수가능조회

- API ID: `v1_국내주식-007`
- Method: `GET`
- URL: `/uapi/domestic-stock/v1/trading/inquire-psbl-order`
- 실전 TR: `TTTC8908R`
- 모의 TR: `VTTC8908R`

문서상 중요한 포인트:
- 1회 최대 `1건`
- 특정 종목 전량매수 가능수량 조회 시 `ORD_DVSN=01(시장가)` 권장
  - 지정가 `00`는 종목 증거금율이 반영되지 않을 수 있다고 문서가 명시
- 주문구분 코드는 현금주문과 거의 같은 범주를 공유

자동매매 구현 시 해석:
- 주문 전 cash/exposure 확인용 핵심 API
- 가격 기반 가능수량과 시장가 기준 가능수량을 분리 해석해야 함

### 6.5 매도가능수량조회

- API ID: `국내주식-165`
- Method: `GET`
- URL: `/uapi/domestic-stock/v1/trading/inquire-psbl-sell`
- 실전 TR: `TTTC8408R`
- 모의는 문서상 `미지원`

자동매매 구현 시 해석:
- 보유 포지션의 매도 가능 수량 확인용
- sell-side hard guardrail과 exit 안전성에 직접 연결됨

## 7. 시세 / 호가 / 실시간 이벤트 핵심 요약

### 7.1 주식현재가 시세

- API ID: `v1_국내주식-008`
- Method: `GET`
- URL: `/uapi/domestic-stock/v1/quotations/inquire-price`
- TR ID: `FHKST01010100`

핵심 요청 필드:
- `FID_COND_MRKT_DIV_CODE`
  - `J` KRX
  - `NX` NXT
  - `UN` 통합
- `FID_INPUT_ISCD`

핵심 응답 필드 예:
- `iscd_stat_cls_code`
  - 관리종목, 투자위험, 투자경고, 투자주의, 거래정지 등 상태 해석 가능
- `marg_rate`
- `temp_stop_yn`
- `stck_prpr`
- `prdy_vrss`
- `prdy_ctrt`
- `acml_tr_pbmn`

자동매매 구현 시 해석:
- 주문 전 종목 상태 검증에 중요
- 거래정지/투자경고/관리종목 제한 로직에 직접 사용 가능

### 7.2 국내주식 실시간체결가 (KRX)

- API ID: `실시간-003`
- WebSocket TR ID: `H0STCNT0`

구독 방식:
- header
  - `approval_key`
  - `custtype`
  - `tr_type`
  - `content-type`
- body
  - `tr_id`
  - `tr_key` = 종목코드

응답 특징:
- 최초 응답은 JSON subscription ack
- 이후 실시간 데이터는 `|` 와 `^` 구분 문자열
- `0|TR_ID|건수|payload...` 형태
- 데이터가 여러 건이면 페이징된 형태로 여러 tick이 함께 옴

자동매매 구현 시 해석:
- parser를 JSON parser와 delimited-string parser로 분리해야 함
- 단건 전제 금지
- 여러 체결 레코드를 한 프레임에서 순차 분해해야 함

### 7.3 국내주식 실시간호가 (KRX)

- API ID: `실시간-004`
- WebSocket TR ID: `H0STASP0`

핵심 데이터:
- `ASKP1..10`
- `BIDP1..10`
- `ASKP_RSQN1..10`
- `BIDP_RSQN1..10`
- `HOUR_CLS_CODE`로 장중/예상/시간외 상태 구분

자동매매 구현 시 해석:
- Fast execution layer에서 top-of-book 및 depth 계산에 사용
- stale orderbook 감지 기준이 필요

### 7.4 국내주식 실시간체결통보

- WebSocket 기반 주문/정정/취소/거부/체결 통보 채널
- 예시 TR ID: `H0STCNI0`

문서상 특징:
- subscription 성공 시 `iv`, `key`가 내려와 AES 복호화에 사용될 수 있음
- 실시간 output 예시는 `^` 구분 문자열
- 예시상 다음 구분값이 중요:
  - `RFUS_YN` 거부 여부
  - `CNTG_YN` 체결 여부
  - `ACPT_YN` 접수 여부
  - `CNTG_QTY`
  - `CNTG_UNPR`
  - `STCK_CNTG_HOUR`
  - `ORD_EXG_GB`

자동매매 구현 시 해석:
- REST submit 응답만으로 주문 상태를 닫으면 안 됨
- 이 채널은 `order_state_event`, `fill_event`, `reconciliation`의 핵심 입력이다
- 암호화 여부/복호화 키 갱신/채널 재구독 복구를 별도 계층으로 둬야 한다

## 8. Roo Code 구현 시 바로 반영해야 할 운영 포인트

### 8.1 주문 안정성

- submit 성공 응답은 `접수/전송`이지 최종 상태가 아니다
- 주문 상태 source of truth는 내부 `OrderManager + reconciliation`이어야 한다
- `ODNO`를 받지 못했거나 REST 응답이 애매하면 재주문보다 조회 우선

### 8.2 조회 예산 분리

- `주식잔고조회`는 느리다고 문서가 직접 경고한다
- `매수가능조회`, `매도가능수량조회`, `주식일별주문체결조회`는 역할이 다르므로 호출 버킷을 분리해야 한다
- inquiry budget이 고갈되면 unknown-state recovery가 막힐 수 있으므로, reconciliation reserve가 필요하다

### 8.3 WebSocket 파서 분리

- subscription ack는 JSON
- 실시간 이벤트는 구분자 기반 문자열
- 다건 패킷 지원 필요
- 암호화 여부 플래그 지원 필요

### 8.4 거래소 구분

- 일부 주문/시세 API는 `KRX`, `NXT`, `SOR` 구분이 있다
- 모의투자는 `KRX` 제약이 많다
- live/paper capability 차이를 adapter capability로 노출하는 것이 안전하다

### 8.5 문자열 숫자 처리

- 주문 수량/단가가 문자열로 정의된 필드가 많다
- parser/normalizer에서 `Decimal`로 변환하고, 원문 문자열도 audit에 남기는 편이 안전하다

## 9. Roo Code에 권장하는 실제 읽기 순서

1. `API 목록`
2. `접근토큰발급(P)`
3. `실시간 (웹소켓) 접속키 발급`
4. `주식주문(현금)`
5. `주식주문(정정취소)`
6. `주식일별주문체결조회`
7. `주식정정취소가능주문조회`
8. `주식잔고조회`
9. `매수가능조회`
10. `매도가능수량조회`
11. `국내주식 실시간체결통보`
12. `국내주식 실시간체결가 (KRX)`
13. `국내주식 실시간호가 (KRX)`
14. `주식현재가 시세`

## 10. 이 문서만 믿으면 안 되는 부분

- 전체 338개 시트 중 이 요약은 MVP 직접 관련 부분만 추렸다.
- 해외주식, 선물옵션, 채권, 연금, 고급 주문유형 전체를 커버하지 않는다.
- KIS는 구TR/신TR 전환, 모의투자 지원 여부, 거래소 확장(NXT/SOR), 응답 포맷이 바뀔 수 있다.
- 실구현 직전에는 반드시 다음을 다시 확인해야 한다.
  - 원본 엑셀의 해당 시트
  - 한국투자증권 공식 GitHub 샘플
  - 한국투자증권 Wikidocs
  - 최신 공지사항

## 11. Roo Code 작업 지시용 한 줄 요약

Roo는 이 엑셀 전체를 처음부터 다 읽지 말고, 이 문서의 우선 시트 14개만 먼저 따라가며 `auth -> order submit -> amend/cancel -> order inquiry -> balance/capacity -> websocket order event -> websocket quote/orderbook` 순으로 구현하면 된다.
