# FDC strict no-bypass rate limiter + 재시도 포함 shared permit 전환

## 배경

2026-08-21 새벽 `280360`/`196170` 두 종목에서 `provider_rate_limit`
(실제 Gemini 429)이 기록된 인시던트를 조사한 결과(별도 세션, 코드
변경 없음), `fdc_rate_limiter.py`의 fail-open 설계(대기 상한 초과/
상태 파일 오류 시 제한 없이 통과)와, `provider_client.py`의 재시도
루프(`MAX_RETRIES=3`)가 limiter의 permit 1회당 최대 3회의 실제 HTTP
요청을 허용하는 구조가 함께, 실제 Gemini 요청 수가 limiter의 목표
(`DEFAULT_MAX_CALLS_PER_WINDOW=10`/60s)를 초과할 수 있는 근본 원인으로
지목됐다.

이 작업은 그 설계 검토(별도 세션, 코드 변경 없음)에서 제시된 두 안
가운데, **안 A(strict queue 전환)** 와 **안 B(재시도 포함 shared
limiter)** 를 모두 이번 턴에서 함께 구현한다. 목적은 단순히
`provider_rate_limit`을 다른 timeout 코드로 바꾸는 것이 아니라,
**실제 HTTP 요청이 limiter를 우회하지 못하게 만들고**, queue에서
포기한 경우와 Gemini가 실제로 거절한 경우를 DB에서 명확히 구분하는
것이다.

## 변경 파일과 이유

| 파일 | 변경 이유 |
|---|---|
| `src/agent_trading/services/ai_agents/fdc_rate_limiter.py` | fail-open bypass 제거 → strict no-bypass. `FdcRateLimitResult`를 `allowed/bypassed/bypass_reason` → `granted/queue_timeout/state_file_error`로 재정의. `DEFAULT_MAX_WAIT_SECONDS` 20.0→18.0 재계산(아래 예산 계산 참고). |
| `src/agent_trading/services/ai_agents/provider_client.py` | 재시도 루프 안에 permit 체크 삽입 — 최초 요청 + 매 재시도마다 `acquire_permit()` 재호출. `PermitResult`/`PermitCallback`/`PermitDeniedError`(얕은 프로토콜, `fdc_rate_limiter.py` import 없음) 신설. `RawProviderResponse`에 `http_attempt_count`/`http_429_count` 추가(`base.py`). |
| `src/agent_trading/services/ai_agents/final_decision_composer.py` | `acquire_permit` 주입 지점 추가, `PermitDeniedError`를 `provider_queue_timeout`/`provider_limiter_unavailable`로 분류하는 `_classify_provider_exception()` 확장, `last_provider_observation`(신규 `ProviderCallObservation`) 속성으로 provider 호출 관측성 노출(LLM 스키마 오염 방지). |
| `scripts/run_agent_subprocess.py` | 외부 1회성 `wait_for_fdc_slot()` 호출 제거 → `_FdcPermitAccumulator`가 재시도별 permit 콜백을 감싸 `FinalDecisionComposerAgent`에 주입. FDC 전용 `_FDC_PER_AGENT_TIMEOUT=70` 신설(EI/AR/AC의 기존 `_PER_AGENT_TIMEOUT=30`은 그대로). `AgentSubprocessOutput`에 8개 관측성 필드 추가. `_build_fdc_timeout_fallback()`의 `reason_codes` 빈 튜플 결함 수정(`provider_timeout` 추가). |
| `src/agent_trading/services/common_types.py` | `AgentExecutionBundle`에 `provider_observability` 필드 추가(신규 DB 테이블 없이 기존 JSONB 경로 재사용). |
| `src/agent_trading/services/subprocess_helpers.py` | `deserialize_agent_output()`에서 subprocess stdout의 8개 관측성 키를 읽어 `provider_observability` dict로 조립(구버전 payload 호환 기본값 포함). |
| `src/agent_trading/services/decision_orchestrator.py` | `_rehydrate_subprocess_agent_runs()`에서 FDC structured_output에 `__provider_observability__` side-channel 키 주입(EI의 기존 `__error__` 패턴과 동일). |
| `tests/services/ai_agents/test_fdc_rate_limiter.py` | 기존 fail-open 계약(`allowed`/`bypassed`) 테스트를 strict 계약(`granted`/`queue_timeout`/`state_file_error`)으로 전면 재작성. |
| `tests/services/ai_agents/test_provider_client.py` | `TestAcquirePermitGating` 신설 — permit이 시도마다 재호출되는지, 거부 시 HTTP 요청이 0번 발생하는지 검증. |
| `tests/scripts/test_fdc_skip.py` | `_build_fdc_timeout_fallback()` reason_codes 비어있지 않음 테스트 추가. |
| `tests/services/test_subprocess_helpers.py` | subprocess stdout-JSON → `deserialize_agent_output()` → `provider_observability` 무손실 round-trip 테스트 4건 추가. |

## strict queue vs. 기존 fail-open 구조적 차이

- **기존(fail-open)**: `wait_for_fdc_slot()`이 대기 상한 초과 또는 상태
  파일 오류 시에도 `allowed=True`를 반환해 호출자가 그대로 Gemini에
  요청을 보냈다(`bypassed=True`로만 표시). 이 permit 획득은
  `FinalDecisionComposerAgent.run()` **호출 전** 딱 1회만 일어났고,
  `provider_client.py`의 재시도 루프(최대 3회)는 이 permit과 완전히
  무관하게 동작했다.
- **신규(strict)**: `wait_for_fdc_slot()`이 대기 상한 초과/상태 파일
  오류 시 `granted=False`를 반환하고, 호출자는 이 경우 **HTTP 요청을
  절대 보내지 않는다**. permit 획득 지점이
  `provider_client.py::generate_structured()`의 재시도 루프 **안**으로
  이동해, 최초 요청과 매 재시도가 각각 독립적으로 permit을 획득해야
  한다.

## 최초 요청 vs. 재시도별 limiter 적용 흐름

```
FinalDecisionComposerAgent.run()
  → provider_client.generate_structured(acquire_permit=...)
       for attempt in range(MAX_RETRIES):        # MAX_RETRIES=3
           permit = await acquire_permit()        # ← 매 attempt마다 재호출
           if not permit.granted:
               raise PermitDeniedError(permit)     # HTTP 요청 없이 즉시 중단
           response = await client.post(...)       # 실제 Gemini HTTP 요청
           if response는 429/5xx and attempt < MAX_RETRIES-1:
               backoff 후 continue                  # 다음 루프에서 다시 permit 획득
           else:
               return 또는 raise
```

`acquire_permit`은 `run_agent_subprocess.py`의 `_FdcPermitAccumulator.
acquire()`이며, 내부적으로 `fdc_rate_limiter.wait_for_fdc_slot()`을
호출하고 누적 대기시간/거부사유를 기록한다. `provider_client.py`는
`fdc_rate_limiter.py`를 전혀 import하지 않는다 — `PermitResult`라는
얕은 모양의 프로토콜만 안다(계층 결합 회피).

## reason code별 의미와 실제 Gemini HTTP 요청 발생 여부

| reason_codes 값 | 의미 | 실제 Gemini HTTP 요청 발생? |
|---|---|---|
| `provider_queue_timeout` | 정상 대기 큐에서 `max_wait_seconds`(18.0s)를 넘도록 슬롯을 못 얻어 포기 | **아니오** — `PermitDeniedError` 발생 시점에 `client.post()` 호출 이전이므로 확정적으로 미발생 |
| `provider_limiter_unavailable` | 상태 파일 접근 자체가 실패(OSError) | **아니오** — 동일하게 `client.post()` 호출 이전 |
| `provider_rate_limit` | 실제 Gemini HTTP 429 응답을 받고 재시도까지 소진 | **예** — 최소 1회, 최대 `MAX_RETRIES`회 |
| `provider_timeout` | FDC per-agent timeout(`_FDC_PER_AGENT_TIMEOUT=70s`) 초과, 또는 provider 응답 자체가 `httpx.TimeoutException` | 상황에 따라 다름(요청은 나갔으나 응답을 못 받았을 수 있음) |
| `provider_error`, `provider_parse_error` | 기존 의미 그대로(5xx/네트워크 오류, JSON 파싱 실패) | 상황에 따라 다름 |

`provider_queue_timeout`/`provider_limiter_unavailable` 모두: (a)
`PermitDeniedError.http_attempt_count == 0`으로 테스트에서 실증(HTTP
요청 미발생), (b) `decision_type="HOLD"` fallback 유지, (c)
`reason_codes`가 항상 비어있지 않음, (d) `summary`에 fallback 종류가
명시됨, (e) `symbol`/`decision_context_id` 보존 — 모두
`final_decision_composer.py`의 예외 처리 경로와
`test_subprocess_helpers.py`의 round-trip 테스트로 검증됨.

## 타임아웃 예산 계산

**중요(2026-08-21 PR #311 코드 검토로 표현 수정)**: 아래 계산은 "최악
시간을 보장한다"는 뜻이 아니다 — Gemini HTTP 왕복을 약 3초/회로 가정한
**설계 목표치**일 뿐이다. 실제 시간 상한 보장은 `_FDC_PER_AGENT_TIMEOUT`
자체의 `asyncio.wait_for()` 강제 종료가 담당한다 — 실제 HTTP 요청이
이 가정보다 오래 걸리면, 아래 `max_wait_seconds` 산식과 무관하게 70초
지점에서 `provider_timeout` fallback으로 확정 종료된다.

```
subprocess 전체 timeout (DecisionAgentRunner.subprocess_timeout)  = 90s
  - EI/AR/AC 소요(수 ms, 무시 가능)
  - 프로세스 spawn/직렬화/SIGTERM 유예 등 안전마진               ≈ 20s
  = FDC 전용 per-agent timeout(_FDC_PER_AGENT_TIMEOUT)            = 70s   (신규 상수, run_agent_subprocess.py — 이 값이 실제 시간 상한을 강제)

70s 예산을 나누는 설계 목표치(MAX_RETRIES=3, 매번 429 후 재시도, HTTP 왕복 3s/회 가정):
  3 x max_wait_seconds(permit 대기)
  + 3 x 가정 HTTP 왕복(~3s/회)
  + 재시도 사이 backoff(RETRY_DELAY 기반, 약 1s+2s=3s)
  <= 70s
  => 3 x max_wait_seconds <= 70 - 9 - 3 = 58
  => max_wait_seconds <= 19.33s

DEFAULT_MAX_WAIT_SECONDS = 18.0s로 설정(fdc_rate_limiter.py)
  → 가정 위 여유: 3x18 + 9 + 3 = 66s <= 70s(약 4s) — 단 실제 HTTP 왕복이
    가정보다 느리면 이 여유는 줄거나 소진될 수 있으며, 그 경우
    `_FDC_PER_AGENT_TIMEOUT=70s`가 확정적으로 종료시킨다.
```

**EI/AR/AC는 이번 변경 대상이 아니다** — 재시도/permit 대기가 없으므로
기존 공유 `_PER_AGENT_TIMEOUT=30`을 그대로 유지한다. **subprocess
전체 timeout(90초) 자체는 변경하지 않았다** — FDC per-agent
timeout(70초)이 그 예산 안에서 충분한 안전마진(20초)을 두고 재계산됐기
때문에, 상위 예산을 늘릴 필요가 없다고 판단했다. `wait_for_fdc_slot()`
은 `max_wait_seconds`에서 항상 확정적으로 종료되므로(무한 대기 없음),
이 경로는 항상 유한 시간 안에 `provider_queue_timeout`으로 귀결된다.

## 검증

- `bash scripts/harness/run.sh test-file tests/services/ai_agents/test_fdc_rate_limiter.py` — 11 passed
- `bash scripts/harness/run.sh test-file tests/services/ai_agents/test_provider_client.py` — 26 passed
- `bash scripts/harness/run.sh test-file tests/scripts/test_fdc_skip.py` — 34 passed
- `bash scripts/harness/run.sh test-file tests/services/test_subprocess_helpers.py` — 6 passed
- `bash scripts/harness/run.sh test-file tests/services/ai_agents/test_agent_subprocess.py` — 25 passed(무관 회귀 없음)
- `bash scripts/harness/run.sh test-file tests/services/test_decision_orchestrator.py` — 98 passed(무관 회귀 없음)
- `bash scripts/harness/run.sh accept backend-file <7개 변경 파일>` — 각각 PASS, test_failed_count=0
- `bash scripts/harness/run.sh accept script-file scripts/run_agent_subprocess.py` — PASS
- `bash scripts/harness/run.sh accept architecture` — PASS(architecture_violation_count=0)
- `bash scripts/harness/run.sh accept no-bypass` — PASS(hard_bypass_count=0). `review_bypass_count=2`
  (`provider_client.py`의 `# type: ignore[union-attr]` 2건 — 재시도
  소진 후 `last_exception: Exception | None`에 관측성 카운트를 부착하는
  지점. 타입 좁히기가 불가능한 구조적 이유(어떤 예외 타입이 최종적으로
  던져질지 런타임에만 결정됨)로 의도적으로 추가했으며, 정적 검사만
  우회하고 실행 동작에는 영향이 없다.)
- `bash scripts/harness/run.sh accept style` — PASS
- `bash scripts/harness/run.sh accept docs` — PASS
- `bash scripts/harness/run.sh type-check backend` — PASS(mypy/pyright 미설치 환경, 실질 미실행)
- 명시적으로 실행하지 않음(요청에 따라 스코프 밖): 전체 pytest, smoke/integration/broker/KIS 테스트, 외부 API 호출.

## 후속 수정(PR #311 코드 검토 반영, 같은 브랜치)

코드 검토에서 `AgentSubprocessOutput`(`run_agent_subprocess.py`)에
추가한 관측성 필드 8개가 실제 stdout JSON 페이로드를 만드는
`subprocess_io.py::build_agent_subprocess_output_payload()`에는
반영되지 않아 조용히 누락되는 배관 결함이 발견됐다 — 부모 프로세스와
DB는 항상 "호출 없음" 기본값만 보고 있었다. `subprocess_io.py`의
`AgentSubprocessOutputLike`/`build_agent_subprocess_output_payload()`
양쪽에 8개 필드를 추가해 수정했고, `write_agent_subprocess_output()`
실제 호출을 통한 round-trip 테스트(`TestProviderObservabilityRoundTrip`,
`tests/services/ai_agents/test_agent_subprocess.py`)와
`decision_orchestrator._rehydrate_subprocess_agent_runs()` 경로까지
검증하는 recorder 테스트를 추가했다.

또한 `DEFAULT_MAX_WAIT_SECONDS`/`_FDC_PER_AGENT_TIMEOUT` 관련 주석과
이 문서의 "타임아웃 예산 계산" 절에서 "최악 시간을 보장한다"처럼 읽힐
수 있는 표현을 수정했다 — 그 계산은 HTTP 왕복 3초/회를 가정한 설계
목표치일 뿐이며, 실제 시간 상한 보장은 `_FDC_PER_AGENT_TIMEOUT`의
`asyncio.wait_for()` 강제 종료가 담당한다는 점을 명시했다(위 "타임아웃
예산 계산" 절 참고). permit 거부/FDC timeout/재시도 중 permit 재획득
실패 경계는 mock/controlled coroutine 기반 신규 테스트로 추가
검증했다(`tests/services/ai_agents/test_agents.py::
TestFinalDecisionComposerAgent`의 `test_run_fallback_on_permit_*`,
`test_fdc_per_agent_timeout_produces_provider_timeout_fallback`).

추가 검증:
- `bash scripts/harness/run.sh test-file tests/services/ai_agents/test_agent_subprocess.py` — 29 passed(신규 round-trip/recorder 테스트 4건 포함)
- `bash scripts/harness/run.sh test-file tests/services/ai_agents/test_agents.py` — 128 passed(신규 permit/timeout boundary 테스트 4건 포함)
- `bash scripts/harness/run.sh test-file tests/services/ai_agents/test_fdc_rate_limiter.py` — 11 passed(예산 테스트가 실제 상수 import로 강화됨)
- `bash scripts/harness/run.sh accept backend-file src/agent_trading/services/ai_agents/subprocess_io.py` / `fdc_rate_limiter.py` — 각각 PASS
- `bash scripts/harness/run.sh accept script-file scripts/run_agent_subprocess.py` — PASS
- `bash scripts/harness/run.sh accept backend-runtime` / `accept architecture` / `accept no-bypass`(hard_bypass_count=0) / `accept style` / `accept docs` — 전부 PASS

## 미검증 항목

- `httpx.HTTPStatusError` 등 provider 예외 인스턴스에 임의 속성
  (`http_attempt_count`/`http_429_count`)을 부착하는 패턴 자체는 이번
  테스트(`TestAcquirePermitGating`, MockTransport 기반)로 실제
  `httpx` 라이브러리에 대해 검증됐다(호스트에 `httpx`가 없어 별도
  스크립트로는 확인 못 했으나, 하네스 컨테이너의 실제 pytest 실행으로
  대체 검증함).
- 실제 운영 컨테이너에서 Gemini API에 대해 이 변경이 배포된 이후의
  실측 `provider_queue_timeout`/`provider_limiter_unavailable`/
  `provider_rate_limit` 분포는 배포 후 관측이 필요하다(아래 배포 후
  측정 항목 참고) — 이번 턴은 코드/테스트 레벨 검증만 수행했다.
- `build_fallback_bundle()`(subprocess 전체 90초 timeout 시 parent가
  직접 구성하는 fallback, `subprocess_helpers.py`)의 기존 빈
  `reason_codes` 문제는 이번 작업의 명시적 스코프(`_build_fdc_timeout_
  fallback()`만 수정하도록 요청됨) 밖이라 그대로 남아있다 — 별도 후속
  작업 필요.

## 배포 후 측정 항목

1개 사이클 확인:
```sql
SELECT symbol, decision_type, reason_codes, summary,
       structured_output_json->'__provider_observability__' AS provider_obs
FROM agent_runs
WHERE agent_type = 'final_decision_composer'
  AND created_at > now() - interval '10 minutes'
ORDER BY created_at DESC;
```

3~5 사이클 집계(원인별 분포):
```sql
SELECT
  (structured_output_json->'__provider_observability__'->>'provider_final_status') AS final_status,
  count(*) AS n,
  avg((structured_output_json->'__provider_observability__'->>'rate_limiter_waited_seconds')::float) AS avg_waited,
  avg((structured_output_json->'__provider_observability__'->>'provider_http_attempt_count')::int) AS avg_attempts
FROM agent_runs
WHERE agent_type = 'final_decision_composer'
  AND created_at > now() - interval '30 minutes'
GROUP BY 1
ORDER BY n DESC;
```

확인 포인트: (1) `provider_queue_timeout`/`provider_limiter_unavailable`
비율이 0이 아니라면 — 실제로 큐에서 확정적으로 거절되는 케이스가
발생 중이라는 뜻이며, 이는 설계대로 동작하는 것이지 결함이 아니다.
(2) `provider_rate_limit` 비율이 이전 대비 감소했는지(재시도까지
limiter가 적용되므로 감소 예상). (3) `avg_attempts`가 1에 가까운지
(재시도가 드물게만 발생해야 정상). (4) FDC 전체 fallback 비율이
`_FDC_PER_AGENT_TIMEOUT=70s` 확장으로 인해 cycle wall-clock에 미치는
영향(늘어난 예산만큼 극단적으로 느려지는 종목이 있는지).
