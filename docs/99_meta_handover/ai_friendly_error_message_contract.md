# AI 친화적 오류 메시지 계약

## 문서 목적

이 문서는 오류 메시지, API 오류 응답, 운영 로그, 하네스 출력이 AI 에이전트와 사람이 같은 근거로 진단할 수 있도록 하는 표준 계약을 정의한다.

현재 1차 범위는 계약 문서화다. API 응답 형태나 런타임 동작은 이 문서만으로 변경하지 않는다.

## 배경

현재 하네스 출력은 `*_count`, `*_exit_code`, `DETAIL`, `ADVISORY` 중심이라 AI가 성공·실패를 판정하기 쉽다. 반면 API 오류 응답과 일부 런타임 로그는 문자열 설명 중심이라 다음 정보가 부족한 경우가 있다.

- 실패한 컴포넌트와 작업 단계.
- 안정적인 `error_code`.
- `account_id`, `symbol`, `order_request_id`, `decision_context_id` 같은 추적 식별자.
- 기대값과 실제값.
- 재시도 가능 여부.
- 운영자가 다음에 확인할 항목.

## 적용 범위

이 계약은 다음 경로에 우선 적용한다.

1. `scripts/harness/run.sh`와 `Makefile` 기반 검증 출력.
2. `src/agent_trading/api/`의 Inspection API 오류 응답.
3. `src/agent_trading/services/`의 주문, 정합성, 스케줄러, 브로커 연동 로그.
4. 운영 리포트와 `summary_json` 검증 출력.

분석·리서치용 일회성 스크립트는 같은 원칙을 따르되, 안정 API 계약으로 취급하지 않는다.

## 공통 원칙

- 사람이 읽는 문장만으로 실패를 설명하지 않는다.
- AI가 파싱할 수 있는 안정적인 키와 카운트를 함께 남긴다.
- 비밀값, 토큰, 계좌 원문, `.env` 값은 출력하지 않는다.
- 실패를 성공처럼 보이게 만들기 위해 오류를 삼키지 않는다.
- 재시도, 우회, 스킵, fallback은 각각 다른 상태로 기록한다.
- 오류 메시지 보강은 매매 의미론, 리스크 정책, 주문 상태 전이 정책을 바꾸지 않는다.

## 표준 필드

가능한 출력 채널에는 다음 필드를 우선 포함한다.

| 필드 | 의미 | 예시 |
|------|------|------|
| `error_code` | 안정적인 기계 판독 코드 | `invalid_uuid`, `broker_auth_failed`, `reconciliation_lock_conflict` |
| `component` | 실패가 발생한 컴포넌트 | `inspection_api`, `order_manager`, `reconciliation_worker` |
| `operation` | 수행 중이던 작업 | `create_order`, `post_submit_sync`, `resolve_unknown_state` |
| `status` | 결과 상태 | `failed`, `skipped`, `retrying`, `blocked` |
| `retryable` | 동일 입력으로 재시도 가능한지 | `true`, `false` |
| `reason` | 사람이 읽는 짧은 이유 | `Invalid account_id UUID` |
| `next_action` | 다음 확인 또는 조치 | `check account_id format`, `run accept backend-runtime` |
| `expected` | 기대한 조건 | `UUID string`, `failed_count=0` |
| `actual` | 실제 관측값 | `abc`, `failed_count=2` |
| `count` 계열 | 처리량과 실패 수 | `processed_count`, `skipped_count`, `failed_count` |

## 추적 식별자

운영 경로에서는 가능한 경우 다음 식별자를 함께 남긴다.

- `account_id`
- `broker_account_id`
- `symbol`
- `decision_context_id`
- `trade_decision_id`
- `order_request_id`
- `execution_attempt_id`
- `reconciliation_run_id`
- `correlation_id`

식별자가 없어서 남길 수 없는 경우에는 임의 값을 만들지 않고 `missing_<field>_count` 또는 `has_<field>=0`처럼 부재를 카운트로 보고한다.

## 출력 채널별 기준

### 하네스 출력

하네스 출력은 현재 형식을 유지한다.

- 첫 줄은 `<AREA> <command>: PASS|FAIL` 형태로 둔다.
- 판정 근거는 `- key=value` 카운트로 출력한다.
- 상세 항목은 `DETAIL <name>:` 아래에 값이 아닌 식별 가능한 위치와 종류를 출력한다.
- 조치가 필요한 비차단 항목은 `ADVISORY <name>:`로 분리한다.

### API 오류 응답

API 오류 응답은 다음 순서로 개선한다.

1. 기존 문자열 `detail` 호환성을 깨지 않는다.
2. 공통 오류 응답 스키마를 먼저 문서화하고 테스트를 추가한다.
3. `build_http_exception()` 기본 모드는 문자열 `detail`을 유지한다.
4. 신규 또는 변경 endpoint에서 구조화 응답이 필요할 때만 `structured_detail=True`로 opt-in한다.
5. Admin UI가 사용하는 endpoint는 UI 영향 범위를 먼저 확인한다.

권장 구조는 다음 필드를 포함하는 객체다.

- `error_code`
- `message`
- `field`
- `received`
- `expected`
- `request_path`
- `next_action`

단, `received`에는 토큰, 비밀번호, 계좌 원문, API secret을 넣지 않는다.

### 런타임 로그

런타임 로그는 JSON 로깅을 당장 도입하지 않더라도 `key=value` 형태의 구조화 단서를 포함한다.

권장 형식:

`event=<event_name> status=<status> component=<component> operation=<operation> error_code=<error_code> retryable=<true|false> account_id=<uuid> symbol=<symbol> order_request_id=<uuid>`

예외 스택이 필요한 경우 `logger.exception`을 사용하되, 로그 메시지 자체에도 이벤트명과 핵심 식별자를 포함한다.

### 운영 리포트

운영 리포트는 “성공” 표현 대신 처리량을 포함한다.

- `processed_count`
- `skipped_count`
- `failed_count`
- `timed_out_count`
- `persisted_record_count`
- `missing_identifier_count`

## 오류 코드 명명 규칙

- 소문자 `snake_case`를 사용한다.
- 원인과 단계가 드러나야 한다.
- 외부 시스템 코드가 있으면 별도 필드로 분리한다.

예시:

- `invalid_account_id`
- `missing_authorization_header`
- `broker_auth_failed`
- `kis_token_expired`
- `order_submit_rejected`
- `post_submit_sync_failed`
- `reconciliation_truth_unavailable`
- `ops_summary_missing_decision_metrics`

## 보안 및 비밀값 규칙

다음 값은 오류 메시지, 로그, 보고서에 원문 출력하지 않는다.

- `.env` 값.
- API key, token, secret, password.
- KIS 계좌번호 원문.
- Authorization header 전체.
- 외부 provider credential.

필요한 경우 `present-redacted`, `missing`, `invalid_format`, `fingerprint=<short_hash>`처럼 비식별 값으로 표현한다.

## 우선 적용 순서

1. 공통 문서와 에이전트 작업 규칙에 계약을 연결한다.
2. Inspection API의 `HTTPException` 문자열 오류를 분류하고 공통 스키마 후보를 만든다.
3. `orders`, `decisions`, `performance`처럼 식별자 검증 오류가 많은 route부터 테스트를 추가한다.
4. `order_manager`, `order_sync_service`, `reconciliation_worker`의 운영 로그에 `event`, `error_code`, 핵심 ID를 보강한다.
5. 하네스에 오류 메시지 계약 정적 점검을 추가할지 별도 결정한다.

API 오류 분류 현황은 [`api_error_message_inventory.md`](./api_error_message_inventory.md)를 기준으로 갱신한다.

## 이번 단계의 비목표

- API 응답 형식 즉시 변경.
- 전체 로그 시스템 교체.
- JSON logger 도입.
- 기존 테스트 대량 수정.
- 매매·리스크·주문 상태 전이 정책 변경.
