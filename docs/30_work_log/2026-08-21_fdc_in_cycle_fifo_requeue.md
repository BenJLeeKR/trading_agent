# FDC strict limiter — in-cycle FIFO 재대기열 도입

## 배경

PR #311(strict no-bypass limiter)의 배포 후 다회 사이클 실측(별도
세션, 코드 변경 없음)에서 `provider_rate_limit`(실제 429)은 0건으로
사라졌지만, 대신 `provider_queue_timeout`이 실제 FDC 호출의 39.4%에서
발생했고, 그 비율이 시간이 지날수록 악화되는 추세가 관측됐다. 뒤이은
설계 검토(별도 세션, 코드 변경 없음)에서 기존 구조가 진짜 FIFO 큐가
아니라 "폴링 기반 경쟁" 구조임이 코드로 확인됐고, 안 A(대기 상한
확대)/안 B(파일 기반 FIFO ticket queue)/안 C(부모 관리 broker)를
비교해 안 B(1회 재대기 포함 FIFO ticket queue)를 추천했다.

이 작업은 그 추천안을 실제로 구현한다: timeout된 최초 FDC permit
요청을 같은 decision cycle 안에서 FIFO 대기열의 맨 뒤로 1회만
재등록해 한 번 더 판단 기회를 준다. 429를 다시 허용하는 것이 목적이
아니다 — 모든 HTTP 요청은 여전히 permit을 획득한 경우에만 전송된다
(strict no-bypass 유지).

## 변경 파일과 이유

| 파일 | 변경 이유 |
|---|---|
| `src/agent_trading/services/ai_agents/fdc_rate_limiter.py` | 상태 파일을 `{"version", "grants", "pending"}`으로 분리해 진짜 FIFO ticket queue 구현. `grants`는 60초 sliding window(기존과 동일 의미), `pending`은 ticket 목록(`ticket_id`/`lane`/`enqueued_at`/`last_heartbeat_at`/`lease_expires_at`/`requeue_count`). head ticket만 grant 가능. 1차 대기(18초) 초과 시 `allow_requeue=True`인 호출에 한해 새 ticket으로 tail 재등록(최대 1회). `FdcRateLimitResult`에 5개 필드 추가. lease(30초) 기반 orphan 정리. |
| `scripts/run_agent_subprocess.py` | `_FdcPermitAccumulator`가 호출 횟수로 "최초 요청(재대기 허용)"과 "재시도(재대기 금지)"를 구분해 `allow_requeue`를 결정. `lane`(source_type)을 accumulator에 전달. `AgentSubprocessOutput`에 5개 신규 관측 필드 추가. |
| `src/agent_trading/services/ai_agents/subprocess_io.py` | `AgentSubprocessOutputLike`/`build_agent_subprocess_output_payload()` 양쪽에 5개 필드 추가(이전 PR #311의 8필드 누락 결함을 반복하지 않기 위해 반드시 두 지점을 함께 수정). |
| `src/agent_trading/services/subprocess_helpers.py` | `deserialize_agent_output()`의 `provider_observability` dict 조립에 5개 필드 추가(구버전 payload 호환 기본값 포함). |
| `tests/services/ai_agents/test_fdc_rate_limiter.py` | FIFO 순서, 재대기(1회 한정), strict 재시도 거부, ticket 정리(정상/취소/orphan), grant vs pending 수명 규칙 분리 — 전면 재작성/확장. |
| `tests/scripts/test_fdc_skip.py` | `_FdcPermitAccumulator`가 최초 호출에만 `allow_requeue=True`를 전달하는지 검증하는 신규 테스트. |
| `tests/services/ai_agents/test_agent_subprocess.py` / `test_subprocess_helpers.py` | 신규 5개 필드의 round-trip 검증 확장, 기존 `SimpleNamespace` fixture에 신규 필드 추가(회귀 방지). |

`final_decision_composer.py`/`decision_orchestrator.py`/`translation.py`/
`expected_value_gate.py`/`provider_client.py`는 이번 변경 대상이
아니다 — `provider_client.py`는 `acquire_permit()`을 반복 호출할 뿐,
"최초 요청인지 재시도인지"를 전혀 모른다(그 구분은 전적으로
`_FdcPermitAccumulator` 내부(`self._call_count`)가 담당). 이 계층
분리 덕분에 `provider_client.py`는 이번 턴에서 단 한 줄도 수정하지
않았다.

## FIFO와 tail 재대기의 실제 상태 전이

```
ENQUEUED(최초 등록, requeue_count=0)
  → 폴링마다 heartbeat 갱신, head+윈도우 여유 시 GRANTED
  → 1차 대기 상한(18초) 초과 시:
      allow_requeue=True(최초 요청)  → 기존 ticket 제거 → 새 ticket으로
                                        FIFO 맨 뒤에 재등록(requeue_count=1)
                                        → 2차 대기(최대 18초)
                                        → GRANTED 또는 QUEUE_TIMEOUT(확정)
      allow_requeue=False(재시도 permit) → 즉시 QUEUE_TIMEOUT(확정)
  → 정상 종료/예외/취소 시: finally에서 자기 ticket 즉시 제거(lease 만료
    대기 불필요)
  → 프로세스가 SIGKILL 등으로 정리 기회를 놓친 ticket만: 다른 참여자가
    폴링 중 flock 안에서 heartbeat 경과 > lease(30초)로 판별해 정리
    (orphan cleanup)
```

## grant/pending 분리 구조와 60초 trim 규칙

- `grants`: 실제 permit이 발급된 시각(float)만 담는 리스트. 매 폴링마다
  `now - window_seconds`(기본 60초) 이전 항목을 트림한다 — 기존
  sliding-window 의미 그대로 유지.
- `pending`: FIFO ticket 목록. **60초 경과를 이유로 삭제되지 않는다**
  (요청사항) — `enqueued_at`이 아무리 오래됐어도 `last_heartbeat_at`이
  신선하면(lease 이내) 보존된다. 오직 `last_heartbeat_at` 기준 lease
  초과만 orphan 판정 기준이다. 이 분리는 테스트로 명시적으로 검증했다
  (`TestGrantTrimVsPendingLifetime`).

## lease 30초 및 orphan 정리 근거

- lease는 poll 주기(1초)의 30배로 설정해, 짧은 스케줄링 지연이나 GC
  pause만으로 살아있는 ticket이 orphan으로 오인되지 않게 했다(요청사항
  — 3~5초처럼 짧게 잡지 않음).
- 정상 경로(성공/queue_timeout 확정/state_file_error/취소)는 전부
  `wait_for_fdc_slot()`의 `finally` 블록에서 자기 ticket을
  **즉시** 제거한다 — lease 만료를 기다릴 필요가 없다.
- orphan 정리는 다른 참여자가 `_poll_ticket()`의 flock 임계구역 안에서
  수행하며, **자기 ticket은 정리 대상에서 항상 제외**하고, 남의
  ticket 중 heartbeat가 lease를 넘은 것만 제거한다 — 살아있는 ticket의
  순서를 어지럽히지 않는다(요청사항 충족, `TestTicketCleanup`으로 검증).

## 최초 요청과 재시도의 재대기 정책 차이

- **최초 요청**(`_FdcPermitAccumulator.acquire()`의 1번째 호출):
  `allow_requeue=True` — 1차 대기(18초) 초과 시 새 ticket으로 FIFO
  맨 뒤에 1회 재등록, 2차 대기(최대 18초)까지 총 최대 36초.
- **재시도(429/5xx)**(2번째 이후 호출): `allow_requeue=False` — 1차
  대기(18초) 초과 시 즉시 확정 실패, 재대기 없음.
- 이유(요청사항 그대로): 재시도마다 18+18초씩 재대기를 허용하면
  `_FDC_PER_AGENT_TIMEOUT`(70초) 및 부모 subprocess(90초) 예산을
  침범할 수 있다. 실제 최악 계산(`fdc_rate_limiter.py` 모듈 docstring
  "2026-08-21(2차)" 절):
  ```
  최초 요청(1차+재대기, 최악 36초)
  + 재시도 2회(재대기 없음, 각 18초) = 36초
  + HTTP 3회(가정 3초/회) = 9초
  + 재시도 backoff(1+2초) = 3초
  ─────────────────────────────────
  최악 84초 > _FDC_PER_AGENT_TIMEOUT(70초)
  ```
  이 84초는 "재대기 + 최대 재시도"가 동시에 발생하는 드문 복합
  케이스에서만 나타나며, 이 경우 시스템이 멈추거나 예산을 무한정
  넘기지 않는다 — 기존에 이미 검증된 `_FDC_PER_AGENT_TIMEOUT`의
  `asyncio.wait_for()` 강제 종료가 70초에서 확정적으로 개입해
  `provider_timeout`으로 귀결시킨다(결함이 아니라 기존 안전판의 정상
  작동). `_FDC_PER_AGENT_TIMEOUT`/`_SUBPROCESS_TIMEOUT` 자체는 이번
  턴에서 올리지 않았다(요청 범위 밖).

## 안전 불변식 확인

- permit 없이 `client.post()`가 실행되지 않는다 — `provider_client.py`
  는 무수정이며, 기존 계약(`acquire_permit()`이 `granted=False`를
  반환하면 `PermitDeniedError`를 즉시 던지고 HTTP를 보내지 않음)이
  그대로 유지된다.
- `provider_queue_timeout`은 여전히 HTTP 미발생 상태를 보장한다 —
  재대기가 발생해도 permit이 실제로 발급되지 않는 한(양쪽 attempt
  모두) `client.post()`에 도달할 방법이 없다(코드 구조상 확인).
- 주문 정책/EV gate/sell guard/sizing/override 로직 — `git diff`
  기준으로 이번 변경분에 해당 파일들이 전혀 포함되지 않음을 확인했다.
- held_position SELL의 stale snapshot 예외 경로는 이번 작업에서
  건드리지 않았다 — 기존 `KIS_SNAPSHOT_STALE_THRESHOLD_SECONDS`(900초)
  및 Pass 2 재검증이 재대기로 인한 지연(최대 +18초)과 무관하게 계속
  독립적으로 동작한다(설계 검토에서 이미 확인된 사실, 이번 구현에서
  변경 없음).
- 새 DB 테이블/마이그레이션 없음 — 기존 `agent_runs.structured_
  output_json["__provider_observability__"]` 경로만 확장.

## 관측성 필드명 결정(요청사항과의 차이 — 명시적 판단)

요청 목록의 `rate_limiter_total_waited_seconds`는 별도 신규 필드로
추가하지 **않고**, PR #311에서 이미 만든 `rate_limiter_waited_seconds`
필드(``_FdcPermitAccumulator.total_waited_seconds`` — 이번 재대기
구현에서도 1차+2차 대기를 누적한 "총 대기시간"과 정확히 같은 의미)를
그대로 재사용했다. 이유: (1) 두 필드가 완전히 동일한 값을 담게 되는
중복을 피하기 위함, (2) 기존 필드명이 이미 운영 SQL/이전 조사
보고서에서 참조되고 있어 이름을 바꾸면 과거 조회 스크립트가 깨진다.
대신 진짜 신규 개념인 `rate_limiter_final_waited_seconds`(마지막
attempt 단독 대기시간)만 추가했다. 이 판단이 요청 의도와 다르면 알려
주시면 후속 턴에서 조정한다.

## 검증

- `bash scripts/harness/run.sh test-file tests/services/ai_agents/test_fdc_rate_limiter.py` — 20 passed(연속 6회 재실행으로 timing flake 없음 확인)
- `bash scripts/harness/run.sh test-file tests/scripts/test_fdc_skip.py` — 38 passed(신규 `_FdcPermitAccumulator` 정책 테스트 포함)
- `bash scripts/harness/run.sh test-file tests/services/ai_agents/test_agent_subprocess.py` — 29 passed(무관 회귀 없음, 신규 5필드 round-trip 확장)
- `bash scripts/harness/run.sh test-file tests/services/test_subprocess_helpers.py` — 6 passed(신규 5필드 round-trip 확장)
- `bash scripts/harness/run.sh test-file tests/services/ai_agents/test_provider_client.py` — 26 passed(무관 회귀 없음 — provider_client.py 무수정 확인)
- `bash scripts/harness/run.sh test-file tests/services/ai_agents/test_agents.py` — 128 passed(무관 회귀 없음)
- `bash scripts/harness/run.sh test-file tests/services/test_decision_orchestrator.py` — 98 passed(무관 회귀 없음)
- `bash scripts/harness/run.sh accept backend-file`(fdc_rate_limiter.py/subprocess_io.py/subprocess_helpers.py) / `accept script-file`(run_agent_subprocess.py) — 전부 PASS
- `bash scripts/harness/run.sh accept backend-runtime` / `accept architecture`(violation=0) / `accept no-bypass`(hard_bypass_count=0, review_bypass_count=3는 `# type: ignore` 1건 + `monkeypatch` 사용 2건 — 정상 테스트 패턴) / `accept style` / `accept docs` — 전부 PASS
- 명시적으로 실행하지 않음(요청에 따라 스코프 밖): 전체 pytest, smoke/integration/broker/KIS 테스트, 외부 API 호출, DB write, 컨테이너 재기동.

## 미검증 운영 가정

- 실제 운영 트래픽 패턴(사이클당 15~19 FDC 호출, held_position lane
  집중)에서 이 1회 재대기가 실제로 `provider_queue_timeout` 비율을
  얼마나 낮추는지는 배포 후 실측이 필요하다 — 설계 검토에서 지적했듯
  이전 관측(첫 10슬롯이 5~6초 안에 거의 동시 소진, 자연 회복 시점이
  사이클 시작 후 약 55~60초)을 볼 때, 1회 재대기(최대 총 36초 대기)로
  모든 실패 사례가 구제되지는 않을 것으로 예상된다 — 사이클 초반에
  일찍 밀린 요청은 여전히 실패할 수 있다.
- core lane 100% starvation 문제는 이번 설계의 명시적 범위 밖이다 —
  순수 FIFO는 "도착 순서"만 공정하게 지킬 뿐, core lane 호출이 매
  사이클 항상 맨 마지막에 "도착"하는 상류(`UniverseSelectionService.
  compose()`) 문제 자체는 해결하지 않는다. ticket에 `lane` 필드를
  남겨뒀으므로, 다음 턴에 lane 최소 슬롯/우선순위 정책을 상태 파일
  스키마 재변경 없이 추가할 수 있다.
- 재대기+최대 재시도 복합 케이스(이론상 84초)가 실제로 얼마나 자주
  `provider_timeout`(outer 70s)으로 귀결되는지는 배포 후 관측 필요.

## 배포 후 측정 SQL과 확인 항목

1개 사이클 확인:
```sql
SELECT td.symbol, td.source_type,
       ar.structured_output_json->'reason_codes' AS fdc_reason_codes,
       ar.structured_output_json->'__provider_observability__' AS obs
FROM trade_decisions td
JOIN agent_runs ar ON ar.agent_run_id = td.agent_run_id
WHERE td.created_at > now() - interval '10 minutes'
  AND (td.decision_json->'ai_call_path'->>'fdc_skipped') = 'false'
ORDER BY td.created_at;
```

3~5 사이클 집계(재대기 효과 측정):
```sql
SELECT
  ar.structured_output_json->'__provider_observability__'->>'provider_final_status' AS final_status,
  count(*) AS n,
  count(*) FILTER (
    WHERE (ar.structured_output_json->'__provider_observability__'->>'rate_limiter_requeue_count')::int >= 1
  ) AS requeued_n,
  count(*) FILTER (
    WHERE (ar.structured_output_json->'__provider_observability__'->>'rate_limiter_requeue_count')::int >= 1
      AND ar.structured_output_json->'__provider_observability__'->>'provider_final_status' = 'success'
  ) AS requeued_then_succeeded_n,
  count(*) FILTER (
    WHERE ar.structured_output_json->'__provider_observability__'->>'rate_limiter_queue_deadline_exceeded' = 'true'
  ) AS deadline_exceeded_n,
  round(avg((ar.structured_output_json->'__provider_observability__'->>'rate_limiter_waited_seconds')::numeric), 2) AS avg_total_wait
FROM trade_decisions td
JOIN agent_runs ar ON ar.agent_run_id = td.agent_run_id
WHERE td.created_at > now() - interval '30 minutes'
  AND (td.decision_json->'ai_call_path'->>'fdc_skipped') = 'false'
GROUP BY 1
ORDER BY n DESC;
```

**확인할 핵심 지표**(요청사항 그대로):
1. `provider_rate_limit`/HTTP 429 건수 — 배포 후에도 0에 가까운지.
2. `provider_queue_timeout` 비율 — 배포 전(39.4%) 대비 감소했는지.
3. `rate_limiter_requeue_count=1` 후 실제로 permit을 얻어 `success`가
   된 건수 — 재대기가 실제로 효과가 있었는지 직접 증거.
4. 재대기 후에도 결국 `queue_timeout`으로 끝난 건수
   (`rate_limiter_queue_deadline_exceeded=true`) — 재대기가 얼마나
   자주 무의미했는지.
5. `rate_limiter_waited_seconds`(누적) 분포 — 재대기로 인해 평균 대기가
   얼마나 늘었는지.
6. lane별(core/held_position) timeout 분포 — core starvation이 이번
   변경으로 개선/불변/악화됐는지(설계상 불변이 예상됨, §미검증 운영
   가정 참고).
7. `provider_queue_timeout` 건 전부 `provider_http_attempt_count=0`인지
   — HTTP 미발생 보장이 실측으로도 유지되는지.
8. cycle wall-clock 변화 — 재대기로 인한 지연이 실제 cycle 소요시간에
   미치는 영향.
9. outer `provider_timeout` 발생 건수 — §타임아웃 예산 계산에서 지적한
   "재대기+최대 재시도 복합 케이스"가 실제로 발생하는지.
