# FDC 429 조용한 fallback 관측성 개선 + 호출 동시성 완화

## 배경 — 오늘(2026-08-18) 429 실측 요약

read-only 실측 턴에서 확인된 사실:

- 오늘 08:00 KST 이후 `trade_decisions` 144건 중 **51건(35.4%)**이
  `decision_type="HOLD"`, `confidence=0.0`, `reason_codes=()`,
  `decision_json.ai_call_path.fdc_skipped=false`인 조합으로 나타났다 —
  이는 `_check_fdc_skip()`이 설계한 정상 스킵(예: `no_events_no_position`,
  `reason_codes` 비어있지 않음)과 달리, **FDC provider 호출이 실제로
  시도됐지만 실패해 예외 fallback으로 떨어진** 흔적이다.
- `ops-scheduler` 로그에서 오늘 하루 `"429 Too Many Requests"`가
  Gemini OpenAI-호환 엔드포인트(`generativelanguage.googleapis.com`,
  `model_id=gemini-3.5-flash-lite`)에 대해 206건 발생했다.
- `_diag()` 진단 파일(파이프 우회, truncation 없음)로 여러 건을 직접
  대조한 결과, 조용한 fallback 건들의 FDC 단계 소요시간이 3.39~3.48초로
  매우 일관됐다 — `provider_client.py`의 재시도 백오프(1.0s+2.0s=3.0s
  최소) + 요청 왕복시간과 정확히 일치해, **429 재시도 3회 소진이
  실질적 원인일 개연성이 매우 높다**고 판단했다(단, `docker logs`의
  2000자 stderr truncation으로 예외 메시지 원문 자체는 확정 불가).
- `agent_runs.status`는 이 51건 전부 `'completed'`로 남아, status
  필드만으로는 정상/fallback을 구분할 수 없었다.
- 동시성 확인: `run_decision_loop.py`가 종목당 독립 subprocess로 FDC를
  호출하며 동시 처리 상한이 하드코딩 5였다 — 사용자 제공 정보로 Gemini
  RPM limit=15인데 관측 RPM이 19까지 나온 것으로 확인돼, 동시성 자체가
  429 대량 발생의 유력한 기여 요인으로 판단했다.

## 이번 PR 범위

1. **fallback 원인 구조화 저장**(관측성) — `FinalDecisionComposerAgent`
   의 예외 fallback에 `reason_codes`/`summary` 마커 추가.
2. **FDC 호출 동시성 완화** — `run_decision_loop.py`의 종목 동시 처리
   상한을 환경변수로 조정 가능하게 하고 기본값을 낮춤.

## 구현 A — fallback 원인 분류

`src/agent_trading/services/ai_agents/final_decision_composer.py`에
`_classify_provider_exception(exc) -> str` 함수를 추가했다:

- `httpx.HTTPStatusError` + status 429 → `"provider_rate_limit"`
- `httpx.HTTPStatusError` + 5xx → `"provider_error"`
- `json.JSONDecodeError` / `TypeError` / `ValueError`(파싱·dataclass
  구성 실패) → `"provider_parse_error"`
- `asyncio.TimeoutError` / `httpx.TimeoutException` → `"provider_timeout"`
- `httpx.TransportError` / `socket.gaierror` / 그 외 → `"provider_error"`

`FinalDecisionComposerAgent.run()`의 `except Exception:` 블록에서 이
마커를 `reason_codes=(reason_marker,)`, `summary=f"provider fallback:
{reason_marker}"`로 fallback 출력에 채운다. `schema_version`/
`agent_name`/`decision_context_id`는 기존과 동일하게 보존한다.
`decision_type="HOLD"` fallback 정책 자체, `symbol` 처리 방식(기존과
동일하게 미보존) 등은 전혀 바꾸지 않았다.

`decision_json`에는 `reason_codes`가 이미 top-level로 저장되고 있어
(`decision_factory.py` 미변경), 재배포 후 이 마커가 그대로
`decision_json.reason_codes`에 나타난다.

## 구현 B — FDC 호출 동시성 완화

`scripts/run_decision_loop.py`:

- `DEFAULT_DECISION_LOOP_MAX_CONCURRENCY = 3`(신규 상수, 기존 하드코딩
  5보다 낮춤), `ENV_DECISION_LOOP_MAX_CONCURRENCY =
  "DECISION_LOOP_MAX_CONCURRENCY"`(신규 환경변수명) 추가.
- `_read_max_concurrency()` 헬퍼 함수를 기존 `_read_interval()`과
  동일한 패턴(환경변수 → `int()` 파싱 → 1 미만/파싱 실패 시 경고 로그+
  기본값 폴백)으로 추가.
- 종목 동시 처리 세마포어 생성부(`_SEMAPHORE_MAX = 5` 하드코딩)를
  `_SEMAPHORE_MAX = _read_max_concurrency()`로 교체.
- `.env.example`에 `DECISION_LOOP_MAX_CONCURRENCY=3` 키를 문서화
  (`.env` 자체는 수정하지 않음).

### 후보 검토 및 선택 근거

사용자가 제시한 후보 A(subprocess 실행 전후 FDC 전용 공유 세마포어),
B(`run_agent_subprocess.py` 내부 전역 세마포어), C(provider client
레벨 프로세스 내 세마포어)를 검토했다. **A/B/C 전부 각 종목이 독립
OS subprocess로 실행되는 현재 구조에서는 프로세스 간 실제로 공유되는
rate limiter가 아니다** — `asyncio.Semaphore`는 단일 프로세스의
이벤트 루프 내에서만 유효하며, `run_agent_subprocess.py`는 매 종목마다
새 프로세스로 fork되므로 그 안에 세마포어를 둬도 프로세스 간 조율이
되지 않는다. 진짜 공유 rate limiter를 만들려면 파일 락, DB 카운터,
Redis 등 IPC가 필요한데, 이는 이번 PR의 "가장 작은 안전한 범위" 요구와
"과도한 구조 변경 회피" 지침에 맞지 않는다고 판단했다.

따라서 **사용자가 제시한 대안 경로("프로세스 간 공유가 어렵다면 symbol
concurrency 자체를 낮추라")를 채택**했다 — `run_decision_loop.py`가
이미 유일하게 모든 subprocess를 스폰하는 부모 프로세스이므로, 여기서
동시에 몇 개의 subprocess(=몇 개의 동시 FDC 요청)를 허용할지 조절하는
것이 실제로 공유되는 유일한 지점이다.

**장단점**:
- 장점: 실제로 동시 provider 요청 수를 직접적으로, 확실하게 낮춘다
  (근사가 아니라 정확한 상한). 구현이 단순해 위험이 낮다.
- 단점: latency가 늘어난다(한 사이클 전체 완료 시간이 동시성에 반비례).
  사용자가 "목표는 429를 줄이는 것이지 latency 최적화가 아니다"라고
  명시했으므로 이 trade-off는 의도적으로 수용했다. 또한 이는 여전히
  "근사적" 해법이다 — 3개마저도 재시도가 겹치면 여전히 429가 발생할
  수 있고, Gemini의 정확한 RPM 계약치를 모르는 상태의 보수적 추정치일
  뿐이다.

## 정책/주문 영향 여부

없음. `translation.py`/`execution_service.py`/`expected_value_gate`/
sizing semantics/EI·AR·AC wiring — 전부 미변경. FDC의 판단 로직
(성공 경로의 프롬프트/파싱/재시도)도 미변경 — 오직 (a) 실패 시
`reason_codes`/`summary`에 사유를 남기는 것, (b) 동시성 파라미터
값만 바꿨다.

## 검증 명령과 결과

| 명령 | 결과 |
|---|---|
| `test-file tests/services/ai_agents/test_agents.py` | 124 passed(신규 fallback 분류 테스트 8건 포함) |
| `test-file tests/scripts/test_run_decision_loop.py` | 137 passed(신규 `TestReadMaxConcurrency` 7건 포함) |
| `accept backend-file src/agent_trading/services/ai_agents/final_decision_composer.py` | 자동 매칭된 `tests/services/ai_agents/test_fdc_prompt.py`에서 5건 실패 — `git stash`로 대조해 clean main에서도 동일하게 실패함을 확인(이번 변경과 무관한 사전 존재 이슈, `SELL`/`WATCH`/`REDUCE`/`EXIT`/`APPROVE` decision_type의 `build_submit_order_request_from_decision()` 관련 실패로 보이며 이번 PR의 변경 파일과 무관) |
| `accept script-file scripts/run_decision_loop.py` | PASS — 자동 매칭 3개 테스트 파일 전부 0 실패 |
| `accept backend-runtime` / `architecture` / `no-bypass` / `style` / `docs` | 전부 PASS |

**회귀 테스트 유효성 검증**: (1) fallback 분류 코드를 임시로 제거하고
재실행해 신규 6건이 실제로 실패함을 확인(`reason_codes=()`로 복귀).
(2) `DEFAULT_DECISION_LOOP_MAX_CONCURRENCY`를 임시로 5로 되돌려
`test_default_is_lowered_from_legacy_five`가 실제로 실패함을 확인.
두 경우 모두 원상 복구 후 전체 재통과 확인.

## 미검증 사항

- `test_fdc_prompt.py`의 5건 실패는 이번 PR과 무관함을 `git stash`로
  확인했으나, 그 자체의 근본 원인은 이번 턴 범위 밖이라 조사하지 않음
  (별도 이슈로 남겨둠 — 필요 시 별도 세션에서 확인 권장).
- Gemini `gemini-3.5-flash-lite`의 실제 계약된 RPM 한도(`.env` 열람
  금지 원칙상 확인 불가) — 동시성 3이 충분히 낮은지, 혹은 더 낮춰야
  하는지는 배포 후 실측으로 검증 필요.
- 동시성 3으로 낮췄을 때 실제 사이클 전체 소요 시간(latency) 증가 폭.

## 배포 후 실측 항목

- `docker logs`의 `"429 Too Many Requests"` 건수(오늘 대비 감소 여부).
- `trade_decisions.decision_json.reason_codes`에서
  `"provider_rate_limit"`/`"provider_parse_error"`/`"provider_timeout"`/
  `"provider_error"` 마커 건수와 비율(이제 DB만으로 fallback 원인을
  구분 가능해야 함).
- 조용한 FDC fallback 비율(`confidence=0.0 AND reason_codes` 마커
  존재로 재정의된 정확한 지표) — 오늘 실측한 35.4%에서 개선되는지.
- HOLD fallback 비율, BUY/APPROVE 전환율 변화(동시성 완화가 판단
  분포 자체를 왜곡하지 않는지 확인).
- 사이클 전체 소요 시간(latency) 변화 — 동시성 완화의 트레이드오프
  확인용.
