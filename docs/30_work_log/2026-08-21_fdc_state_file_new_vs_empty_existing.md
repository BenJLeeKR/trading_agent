# FDC strict limiter — 신규 파일 vs "이미 존재하는 빈 파일" 구분

## 배경

앞선 3차 수정(`docs/30_work_log/2026-08-21_fdc_state_file_
corruption_fail_closed.md`)은 JSON 파싱 실패/버전 불일치/타입 이상
등 "내용을 해석할 수 없는" 손상을 fail-closed로 고쳤지만, 여전히
남은 구멍이 있었다: `_read_state()`는 **내용이 비어 있으면**
무조건 "방금 생성된 정상 신규 파일"로 간주했다. 그러나
`open(path, "a+")`는 파일이 이미 존재하든 존재하지 않든 똑같이
성공하므로, 이 방식만으로는 다음 두 상태를 구분할 수 없었다:

1. 상태 파일이 아직 존재하지 않는 정상 최초 실행
2. 이미 존재하던 상태 파일이 프로세스 강제 종료·`truncate()` 직후
   종료·부분 기록 실패·운영자 실수 등으로 비어 버린 비정상 상태

둘 다 "0바이트(또는 공백만 있는) 파일"이라는 점에서 구별 불가능했고,
2번 상태를 1번으로 오인하면 최근 60초 grant 기록을 잃어 strict RPM
한도를 우회할 수 있었다.

## 신규 파일과 기존 빈 파일을 구분하는 정확한 방법

`_ensure_state_file_initialized(state_path)`를 도입해 **"파일이
존재하는 순간, 그 파일은 이미 완전한 유효 JSON을 담고 있다"**는
불변식을 만들었다:

1. `os.path.exists(state_path)`로 파일 존재 여부를 먼저 확인한다.
   이미 존재하면 즉시 반환(아무 것도 하지 않음).
2. 존재하지 않으면, 임시 파일(`{state_path}.init.{uuid4 hex}.tmp`)에
   유효한 빈 v1 JSON(`{"version":1,"grants":[],"pending":[]}`)을
   **전부 먼저 써넣고 flush+fsync**한 뒤, `os.link(tmp_path,
   state_path)`로 최종 경로에 원자적으로 연결한다.
3. `os.link()`는 대상 경로가 이미 존재하면 `FileExistsError`를
   던진다 — 이 성질을 이용해 "여러 프로세스가 동시에 최초 호출해도
   정확히 하나만 실제로 파일을 만든다"를 보장한다. 진 프로세스는
   `FileExistsError`를 조용히 무시하고 자기 임시 파일만 정리한다.
4. `_poll_ticket()`과 `_remove_ticket()` 양쪽 모두 실제
   `open(path, "a+")` 호출 **이전에** 이 함수를 호출한다.

이 설계 덕분에 `open(path, "a+")`가 만드는 "존재하지만 아직 비어
있는" 중간 상태가 공유 경로에 **절대 나타나지 않는다** — 파일은
"존재하지 않음"에서 곧바로 "존재하며 유효한 내용을 담음"으로만
전이한다.

## 왜 기존 `a+` 방식만으로 구분이 불가능했는지

`open(path, "a+")`는 파일이 없으면 즉시(그리고 원자적으로) 빈 파일을
만들고 반환하지만, 그 "빈 파일"이라는 관측 결과 자체는 "내가 방금
만든 파일"인지 "누군가 이미 만들어놨던 파일이 나중에 비워진 것"인지
아무 정보도 담고 있지 않다 — `stat()`으로 생성 시각을 봐도 두 경우
모두 매우 최근 시각일 수 있고, 애초에 "내가 생성했는가" 여부는
파일시스템 API가 별도로 알려주지 않는다(POSIX에는 "생성 여부"를
반환하는 `open()` 플래그가 없다 — `O_EXCL`은 "이미 있으면 실패"는
알려주지만 그 반대(내가 성공적으로 만들었다)의 확증은 되지만, 그
확증과 "내용을 채우는 것"이 원자적으로 묶여 있지 않으면 여전히
경쟁 조건이 생긴다). 그래서 존재 여부 확인과 내용 확정을 하나의
원자적 연산(임시 파일 완성 후 `link`)으로 묶어야 했다.

## 빈 기존 파일이 fail-closed되는 코드 및 테스트 근거

**코드**: `_read_state()`에서 "내용이 비어 있으면 신규로 간주" 분기를
완전히 제거하고, 무조건 `_CorruptStateFileError`를 던지도록 변경했다
— 이제 이 함수가 호출되는 시점에는 호출자가 이미
`_ensure_state_file_initialized()`를 실행했다는 전제가 있으므로,
내용이 비어 있다면 그것은 예외 없이 "이미 존재하던 파일이 나중에
비워진" 손상 상태다.

**테스트**(`TestNewFileVsExistingEmptyFile`):
- `test_nonexistent_path_initializes_and_grants_first_permit` — 없는
  경로에서 첫 호출 시 유효 v1 상태 생성 + 첫 permit 정상 발급.
- `test_preexisting_zero_byte_file_fails_closed` — `Path.touch()`로
  사전에 0바이트 파일을 만든 뒤 호출 → `granted=False,
  state_file_error=True, queue_timeout=False`.
- `test_preexisting_whitespace_only_file_fails_closed` — 공백만 있는
  기존 파일도 동일하게 fail-closed.
- `test_partial_json_write_fails_closed` — 잘린 JSON(`'{"version":
  1, "grants":'`)도 기존 손상 JSON 테스트와 동일하게 fail-closed.

## 동시 최초 초기화 시 안전성 근거

`test_concurrent_first_initialization_is_race_free`: 존재하지 않는
동일 경로에 5개 호출을 동시에 시작해도 (1) 어느 것도
`state_file_error`가 나지 않고, (2) `max_calls`를 동시 호출 수와
같게 둔 조건에서 5개 전부 정상 grant되며, (3) 최종 상태 파일이
유효한 v1 dict 구조이고 `grants` 개수가 `max_calls`를 넘지 않음을
확인했다. 안전성의 핵심은 `os.link()`의 원자성(POSIX 보장)이다 —
링크 생성은 커널 수준에서 단일 원자 연산이므로, 여러 프로세스가
동시에 시도해도 정확히 하나만 성공하고 나머지는 `FileExistsError`를
받는다는 것이 파일시스템 자체의 보장이지 애플리케이션 레벨의
타이밍에 의존하지 않는다.

**알려진 미세 경쟁(수용된 트레이드오프)**: 이론적으로 승자가
`os.link()`를 마친 직후부터 실제 `_poll_ticket()`의 `flock()`을
획득하기까지의 극히 짧은 시간 동안, 다른 프로세스가 끼어들 여지는
없다 — `os.link()`가 성공한 시점에는 이미 대상 파일에 완전한 내용이
쓰여 있으므로(임시 파일에 먼저 다 쓰고 나서 link했으므로), 그 이후
누가 열어도 항상 유효한 JSON을 보게 된다. 따라서 이번 설계에는
"파일은 존재하지만 아직 비어 있다"는 중간 상태가 구조적으로 존재하지
않는다 — 별도의 트레이드오프를 감수할 필요가 없었다.

## 변경 파일과 검증 결과

- `src/agent_trading/services/ai_agents/fdc_rate_limiter.py` —
  `_ensure_state_file_initialized()` 신설, `_poll_ticket()`/
  `_remove_ticket()`에서 호출, `_read_state()`의 "빈 내용=신규" 분기
  제거, 모듈 docstring에 "설계(2026-08-21, 4차)" 절 추가.
- `tests/services/ai_agents/test_fdc_rate_limiter.py` —
  `TestNewFileVsExistingEmptyFile`(5건) 신설.

`provider_client.py`, 주문 정책, EV gate, sell guard, sizing, DB
schema/migration은 수정하지 않았다.

검증:
- `bash scripts/harness/run.sh test-file tests/services/ai_agents/test_fdc_rate_limiter.py` — 36 passed(연속 6회 재실행으로 timing flake 없음 확인)
- `bash scripts/harness/run.sh test-file tests/scripts/test_fdc_skip.py` — 38 passed(무관 회귀 없음)
- `bash scripts/harness/run.sh test-file tests/services/ai_agents/test_agent_subprocess.py` — 29 passed(무관 회귀 없음)
- `bash scripts/harness/run.sh test-file tests/services/test_subprocess_helpers.py` — 6 passed(무관 회귀 없음)
- `bash scripts/harness/run.sh accept backend-file src/agent_trading/services/ai_agents/fdc_rate_limiter.py` — PASS
- `bash scripts/harness/run.sh accept backend-runtime` / `accept architecture`(violation=0) / `accept no-bypass`(hard_bypass_count=0, review_bypass_count=0) / `accept style` — 전부 PASS
- 명시적으로 실행하지 않음(요청에 따라 스코프 밖): 전체 pytest, smoke/integration/broker/KIS 테스트, 외부 API 호출, DB write, 컨테이너 재기동.

## 미검증 운영 가정

- 실제 운영 환경(같은 컨테이너의 여러 subprocess)에서 진짜 "최초
  동시 초기화" 순간이 얼마나 자주 발생하는지는 확인하지 않았다 —
  일반적으로 첫 사이클의 첫 FDC 호출들이 동시에 이 경로를 탈 가능성이
  있으나, 컨테이너 재기동 직후를 제외하면 이후에는 상태 파일이 이미
  존재하므로 이 경로 자체가 드물게만 실행될 것으로 예상된다.
- `os.link()`가 상태 파일이 위치한 실제 파일시스템(OS 임시
  디렉터리, 통상 tmpfs 또는 overlay)에서 항상 지원되는지는 코드
  검토로만 확인했고 실제 운영 컨테이너에서 실행해 검증하지 않았다
  (일반적인 Linux tmpfs/ext4/overlay는 hard link를 지원하지만,
  네트워크 파일시스템 등 예외적인 환경에서는 지원되지 않을 수 있다
  — 이 경우 `os.link()`가 `OSError`를 던지고, 이는 `_ensure_state_
  file_initialized()`가 그대로 전파해 뒤이은 `open()`/`flock()`에서
  자연스럽게 `state_file_error`로 이어질 것으로 예상되나 실측하지
  않았다).

## 배포 후 확인 항목

```sql
-- provider_limiter_unavailable 발생 여부/빈도 확인
SELECT
  ar.structured_output_json->'__provider_observability__'->>'provider_final_status' AS final_status,
  count(*) AS n
FROM trade_decisions td
JOIN agent_runs ar ON ar.agent_run_id = td.agent_run_id
WHERE td.created_at > now() - interval '1 hour'
  AND (td.decision_json->'ai_call_path'->>'fdc_skipped') = 'false'
GROUP BY 1
ORDER BY n DESC;
```

확인할 항목(요청사항 그대로): (1) `provider_limiter_unavailable` —
0이면 상태 파일 관련 문제가 없다는 뜻, 0이 아니면 로그(`FDC rate
limiter: 상태 파일... 접근 실패`)로 정확한 원인(신규 초기화 경합
vs 진짜 손상 vs 디스크 오류) 교차 확인. (2) `provider_rate_limit`/
HTTP 429 — 계속 0에 가까운지(이번 수정과 직접 관련 없으나 회귀
확인). (3) `provider_queue_timeout` 비율 — 이번 수정으로 변화가
없어야 정상(순수 안전성 보정이므로 정상 케이스의 동작은 바뀌지
않음). (4) 상태 파일 오류 로그 발생 시점이 컨테이너 재기동 직후에
집중되는지(최초 초기화 관련) 아니면 무작위로 발생하는지(진짜 손상
가능성). (5) permit 없는 HTTP 요청이 없는지 — `provider_http_
attempt_count`가 `provider_limiter_unavailable`/`provider_queue_
timeout` 건에서 항상 0인지 재확인(기존 계약 유지 확인).
