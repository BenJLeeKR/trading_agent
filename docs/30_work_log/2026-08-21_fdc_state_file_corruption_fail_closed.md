# FDC strict limiter — 손상 상태 파일 fail-closed 보정

## 배경

PR #313(in-cycle FIFO 재대기열)의 코드 검토에서, `fdc_rate_limiter.py`
의 `_read_state()`가 상태 파일 내용을 JSON 파싱 실패/최상위 구조
이상/지원하지 않는 `version`/`grants`·`pending` 타입 이상 등 **어떤
이유로든 해석할 수 없으면 전부 조용히 빈 상태(`_empty_state()`)로
대체**하고 있었음이 확인됐다. 이는 strict no-bypass 원칙의 구멍이다
— 상태 파일이 손상되면 최근 60초 `grants` 기록이 통째로 사라지고,
다음 폴러가 "윈도우가 비어 있다"고 오판해 `DEFAULT_MAX_CALLS_PER_
WINDOW=10` 한도를 무시한 채 새 permit을 계속 발급할 수 있었다 —
사실상 fail-open으로 되돌아가는 경로였다. 이번 작업은 이 구멍을
막고, 동시에 in-cycle FIFO 재대기가 실제로 성공에 이르는 핵심 경로를
테스트로 증명한다.

## 손상 상태가 왜 기존에는 strict limiter를 우회할 수 있었는지

기존 `_read_state()`:
```python
if not isinstance(data, dict) or data.get("version") != _STATE_VERSION:
    return _empty_state()
```
JSON 파싱 실패(`data = None`), 최상위가 dict가 아님, version 불일치
— 이 모든 경우가 이 한 줄로 뭉뚱그려져 "그냥 빈 상태로 치자"는
판정으로 이어졌다. `_poll_ticket()`은 이 빈 상태(`grants=[]`)를
받아 `len(grants) < max_calls`가 항상 참이 되므로, 호출자가 즉시
`granted=True`를 받아 **실제 Gemini HTTP 요청을 곧바로 진행**할 수
있었다 — 상태 파일이 어떤 이유로든(디스크 오류로 인한 부분 쓰기,
동시 프로세스 충돌, 수동 조작 등) 손상되기만 하면, 그 순간부터 RPM
제한이 사실상 무력화되고 429가 재발할 수 있는 경로였다.

## 신규 파일 / legacy 상태 / 손상 상태의 처리 규칙

| 상태 | 판정 | 결과 |
|---|---|---|
| 파일이 아예 없어서 `open(path, "a+")`가 새로 생성(내용 완전히 빈 문자열) | 정상 신규 | `{"version":1,"grants":[],"pending":[]}`로 초기화, 즉시 permit 발급 가능 |
| 순수 숫자로만 구성된 `list`(PR #311 이전 legacy 포맷, 빈 리스트 포함) | 정상 legacy | `{"version":1,"grants":<그 리스트>,"pending":[]}`로 1회 변환 후 저장 |
| 숫자가 아닌 값이 섞인 `list` | 손상 | `state_file_error=True`, HTTP 요청 금지 |
| JSON 파싱 실패 | 손상 | 〃 |
| 최상위가 dict도 list도 아님(예: 문자열, 숫자) | 손상 | 〃 |
| 지원하지 않는 `version`(예: 999, 또는 아예 없음이면서 dict인 경우) | 손상 | 〃 |
| `grants` 또는 `pending`이 list가 아님 | 손상 | 〃 |

"손상"으로 판정된 모든 경우는 `_CorruptStateFileError`(`OSError`
서브클래스)를 던져, 기존 `wait_for_fdc_slot()`의
`except OSError as exc:` 경로(`granted=False, state_file_error=True`,
HTTP 요청 금지, 상위에서 `provider_limiter_unavailable`로 fallback)
를 그대로 재사용한다 — 새로운 예외 처리 분기를 추가하지 않고 기존
계약을 확장하는 방식을 택했다.

## legacy `list[float]` 변환 정책과 근거

**채택**: 프롬프트가 제시한 권장안 그대로 채택했다 — 숫자만으로
구성된 legacy `list[float]`는 `{"version": 1, "grants": <그 리스트>,
"pending": []}`로 `flock` 임계구역 안에서 1회 변환하고, 같은
`_poll_ticket()` 호출이 끝나기 전에 `_write_state()`로 v1 구조를
다시 저장한다(별도 코드 불필요 — `_poll_ticket()`이 항상 끝에
`_write_state()`를 호출하므로 자동으로 지속된다). legacy grant도
기존 `_trim_grants()`가 그대로 60초 기준으로 트림한다(추가 로직
불필요).

**근거**: 배포 직후(컨테이너 재기동 직후) 상태 파일에 PR #311 이전
포맷의 잔여 데이터가 남아있을 가능성은 낮지만(상태 파일은
`tempfile.gettempdir()` 아래 ephemeral 캐시이고 컨테이너 재기동 시
보통 초기화됨), 만에 하나 남아있는 경우 그 안의 60초 grant 기록을
그냥 버리면 배포 직후 첫 몇 초 동안 RPM 한도가 일시적으로 무력화될
수 있다 — 변환을 통해 이 위험을 원천 차단한다. 반대로 숫자가 아닌
값이 섞인 리스트는 애초에 이 시스템이 만든 적 없는 형태이므로
마이그레이션을 시도하지 않고 손상으로 fail-closed 처리한다(권장안
그대로).

## 재대기 후 실제 성공 테스트 결과

`TestRequeueToTail::test_requeued_ticket_eventually_succeeds_after_c_and_d`
— O 3명이 `max_calls=3`을 정확히 채우고 거의 동시에 grant/만료되도록
구성한 뒤, Z가 1차 대기(0.3초, `window_seconds=0.4`보다 짧게 설정해
확정적으로 실패하도록)에서 timeout돼 tail로 재등록되고, 이미 대기
중이던 patient한 C, D보다 뒤에서 2차 대기 끝에 실제로 permit을
받는지 검증했다. 결과: `c_result.granted=True`, `d_result.granted=
True`, `z_result.granted=True`, `z_result.requeue_count=1`,
`z_result.queue_deadline_exceeded=False`, 완료 순서 `C → D → Z`
확인, `z_result.waited_seconds > 0`(1차+2차 누적 대기 반영).

**설계 노트**: `max_calls=1`(단순히 "O 1명이 슬롯 점유")로는 이
성공 시나리오를 구성하는 것이 **수학적으로 불가능**함을 검증
과정에서 확인했다 — C와 D가 각자 전체 window를 순차 점유해야 하므로
Z의 2차 attempt에 필요한 대기(≈2×window)가 항상 1차 attempt의 실패
판정 시간(<window)보다 커야 하는데, 동일한 `max_wait_seconds`
예산으로는 "1차 실패 + 2차 성공"을 동시에 만족시킬 수 없다(1차가
빨리 실패하려면 예산이 작아야 하고, 2차가 성공하려면 예산이 그보다
2배 이상 커야 하는 모순). `max_calls=3`으로 O 3명이 "한 세대"를
이루고 만료도 동시에 일어나게 하면, 그 뒤를 잇는 C/D/Z도 capacity
여유 안에서 거의 동시에(순서대로) grant를 받을 수 있어 이 모순이
해소된다. 실무적으로도 이는 타당하다 — 운영 환경의
`DEFAULT_MAX_CALLS_PER_WINDOW=10`은 1이 아니라 10이므로, 실제로는
여러 요청이 "한 세대" 안에서 함께 처리되는 이 테스트의 구조가 운영
조건에 더 가깝다.

## 변경 파일

- `src/agent_trading/services/ai_agents/fdc_rate_limiter.py` —
  `_CorruptStateFileError` 신설, `_read_state()` 전면 재작성(신규
  빈 파일/legacy list 마이그레이션/손상 판정을 명확히 분리), 모듈
  docstring에 "설계(2026-08-21, 3차)" 절 추가.
- `tests/services/ai_agents/test_fdc_rate_limiter.py` — `TestState
  FileCorruption`(손상 JSON/버전/타입별 fail-closed 5건 + 신규 빈
  파일/legacy 마이그레이션 3건) 신설, `TestRequeueToTail`에 재대기
  후 실제 성공 테스트 1건 추가.

`provider_client.py`, 주문 정책, EV gate, sell guard, sizing,
decision orchestrator, DB schema/migration은 수정하지 않았다(요청
범위 밖 — git diff로 확인 가능).

## 검증

- `bash scripts/harness/run.sh test-file tests/services/ai_agents/test_fdc_rate_limiter.py` — 31 passed(연속 6회 재실행으로 timing flake 없음 확인)
- `bash scripts/harness/run.sh test-file tests/scripts/test_fdc_skip.py` — 38 passed(무관 회귀 없음)
- `bash scripts/harness/run.sh test-file tests/services/ai_agents/test_agent_subprocess.py` — 29 passed(무관 회귀 없음)
- `bash scripts/harness/run.sh test-file tests/services/test_subprocess_helpers.py` — 6 passed(무관 회귀 없음)
- `bash scripts/harness/run.sh accept backend-file src/agent_trading/services/ai_agents/fdc_rate_limiter.py` — PASS
- `bash scripts/harness/run.sh accept backend-runtime` / `accept architecture`(violation=0) / `accept no-bypass`(hard_bypass_count=0, review_bypass_count=0) / `accept style` / `accept docs` — 전부 PASS
- 명시적으로 실행하지 않음(요청에 따라 스코프 밖): 전체 pytest, smoke/integration/broker/KIS 테스트, 외부 API 호출, DB write, 컨테이너 재기동.

## 미검증 운영 가정

- 실제 운영 컨테이너의 상태 파일이 지금까지(PR #311/#313 배포 이후)
  손상된 사례가 있었는지는 확인하지 않았다(read-only 조사가 아니라
  코드 구현 턴이므로 DB/컨테이너 조회를 하지 않음) — 배포 후
  `provider_limiter_unavailable` 발생 빈도로 간접 확인 필요.
- legacy `list[float]` 마이그레이션 경로는 실제 운영 환경에서 아직
  한 번도 트리거되지 않았을 가능성이 높다(컨테이너가 이미 PR #311
  이후로 재기동돼 상태 파일이 초기화됐을 것이므로) — 이 경로의 실제
  운영 발동 여부는 관측되지 않을 수 있다.

## 배포 후 확인 항목

```sql
-- 1개 사이클: reason_codes/final_status 분포 확인
SELECT td.symbol, td.source_type,
       ar.structured_output_json->'reason_codes' AS fdc_reason_codes,
       ar.structured_output_json->'__provider_observability__' AS obs
FROM trade_decisions td
JOIN agent_runs ar ON ar.agent_run_id = td.agent_run_id
WHERE td.created_at > now() - interval '10 minutes'
  AND (td.decision_json->'ai_call_path'->>'fdc_skipped') = 'false'
ORDER BY td.created_at;

-- 3~5 사이클: 핵심 지표 집계
SELECT
  ar.structured_output_json->'__provider_observability__'->>'provider_final_status' AS final_status,
  count(*) AS n,
  count(*) FILTER (
    WHERE (ar.structured_output_json->'__provider_observability__'->>'rate_limiter_requeue_count')::int >= 1
      AND ar.structured_output_json->'__provider_observability__'->>'provider_final_status' = 'success'
  ) AS requeued_then_succeeded_n
FROM trade_decisions td
JOIN agent_runs ar ON ar.agent_run_id = td.agent_run_id
WHERE td.created_at > now() - interval '30 minutes'
  AND (td.decision_json->'ai_call_path'->>'fdc_skipped') = 'false'
GROUP BY 1
ORDER BY n DESC;
```

확인할 항목(요청사항 그대로): (1) `provider_rate_limit`/HTTP 429
건수 — 이번 수정과 무관하게 계속 0에 가까운지. (2)
`provider_limiter_unavailable` 발생 여부/빈도 — 0이면 상태 파일
손상이 실제로 발생하지 않았다는 뜻(정상), 0이 아니면 손상이 실제로
일어나고 있고 이번 fail-closed 수정이 그것을 올바르게 차단하고
있다는 증거. (3) `provider_queue_timeout` 비율 — PR #313 배포 전과
비교해 변화가 있는지. (4) `rate_limiter_requeue_count=1` 후
`provider_final_status='success'`가 된 건수 — 재대기가 실제로
효과가 있는지 직접 증거. (5) 상태 파일 오류(`provider_limiter_
unavailable`)가 배포 후 실제로 한 번이라도 관측되는지 — 관측되면
그 시점의 로그(`FDC rate limiter: 상태 파일... 접근 실패`)로 어떤
종류의 손상이었는지 교차 확인.
