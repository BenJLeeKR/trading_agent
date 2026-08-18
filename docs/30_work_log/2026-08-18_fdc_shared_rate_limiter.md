# FDC provider 호출 shared rate limiter 도입 + 동시성 완화 rollback

## PR #286 배포 후 실측 결과 요약

PR #286(관측성 개선 + 동시성 5→3 완화) 반영 후 첫 decision loop
사이클(2026-08-18 10:36:15~10:37:12 KST, 36개 종목)을 기준선
(2026-08-18 09:54:37~09:55:07 KST, 동시성 5, 동일 36개 종목)과
같은 크기로 비교한 결과:

| 지표 | 기준선(동시성 5) | PR #286 이후(동시성 3) | 판정 |
|---|---|---|---|
| `reason_codes` 구조화(silent fallback 구분) | 불가(silent 17건, 47.2%) | **가능**(silent 0건, 전부 `["provider_rate_limit"]`) | **개선됨** |
| 429 발생 건수(동일 크기 사이클) | 72건 | 72건 | **변화 없음** |
| fallback 비율 | 47.2%(17/36) | 50.0%(18/36) | **개선 안 됨**(오히려 소폭 상승) |
| cycle wall-clock | 약 30초 | 약 56.7초 | **거의 2배 증가** |

**결론**: `reason_codes` 관측성 개선은 완전히 성공했으나, symbol-level
동시성 완화(5→3)는 429/fallback 비율 감소 효과가 입증되지 않았고
latency만 크게 늘렸다 — 순수 비용만 발생한 변경이었다. 추가로,
`.env.example`에 문서화한 `DECISION_LOOP_MAX_CONCURRENCY`가
`docker-compose.yml`의 `ops-scheduler` `environment:` 블록에 선언돼
있지 않아 애초에 env 파일로 조정도 불가능한 배선 누락이 있었다
(PR #279에서 고쳤던 것과 동일한 패턴의 회귀 — 사용자가 직접 지적).

## 이번 PR 범위

1. PR #286의 동시성 완화(symbol-level `_SEMAPHORE_MAX` 5→3)를
   완전히 rollback.
2. FDC provider 호출 전용 **실제로 프로세스 간 공유되는** rate
   limiter를 신규 도입.
3. PR #286의 `reason_codes`/`summary` fallback 관측성 개선은 그대로
   유지.

## Rollback 내용

`scripts/run_decision_loop.py`:
- `DEFAULT_DECISION_LOOP_MAX_CONCURRENCY`, `ENV_DECISION_LOOP_MAX_
  CONCURRENCY` 상수 제거.
- `_read_max_concurrency()` 헬퍼 함수 제거.
- `_SEMAPHORE_MAX = _read_max_concurrency()` → `_SEMAPHORE_MAX = 5`
  (원래 하드코딩 값, 원래 주석)로 복원.

`.env.example`: `DECISION_LOOP_MAX_CONCURRENCY` 항목 제거(더 이상
사용하지 않는 설정이자, 애초에 `docker-compose.yml`에 배선돼 있지
않아 의미 없는 문서였음).

`tests/scripts/test_run_decision_loop.py`: `TestReadMaxConcurrency`
클래스 및 관련 import 제거.

**최소화 판단**: env var/헬퍼 함수 메커니즘 자체를 남기고 기본값만
5로 되돌리는 방안도 검토했으나, 이 메커니즘의 존재 목적 자체가
"429 완화"였고 이제 그 역할을 shared rate limiter가 대신하므로,
더 이상 쓰이지 않을 설정 표면을 남겨두는 것보다 완전히 제거하는
쪽이 더 깔끔하다고 판단했다(PR #286이 추가한 것을 정확히 원상
복구하는 범위).

## Shared rate limiter 설계

신규 모듈 `src/agent_trading/services/ai_agents/fdc_rate_limiter.py`.

**왜 이전 방식(동시성 완화)은 가짜 shared limiter였는가**: 각 종목이
독립 OS subprocess로 FDC를 호출하는 구조에서, `asyncio.Semaphore`를
부모 프로세스(`run_decision_loop.py`)나 자식 프로세스(`run_agent_
subprocess.py`) 어디에 두든 그건 **단일 프로세스의 이벤트 루프
내에서만 유효**하다 — 서로 다른 OS 프로세스 사이에서는 전혀 공유되지
않는다. PR #286의 동시성 완화는 이 한계를 "동시에 뜨는 프로세스 수
자체를 줄이는" 우회로 대응했으나, 실측 결과 효과가 없었다.

**신규 설계**: 파일 락(`fcntl.flock`) + sliding-window 타임스탬프
기록 방식.

- 모든 subprocess가 같은 상태 파일(기본: `tempfile.gettempdir()`
  아래 `agent_trading_fdc_rate_limiter_state.json`)을 공유한다 —
  같은 호스트/컨테이너 파일시스템을 쓰는 한 프로세스 경계와 무관하게
  **실제로 공유된다**(이게 핵심 차이점).
- `fcntl.flock`으로 원자적 읽기-트림-쓰기를 보장해, 동시에 여러
  프로세스가 접근해도 카운트가 깨지지 않는다.
- 정책: 기본값 60초 윈도우당 최대 10회 호출(`DEFAULT_MAX_CALLS_
  PER_WINDOW=10`, `DEFAULT_WINDOW_SECONDS=60.0`) — Gemini RPM
  limit=15(운영자가 콘솔에서 직접 확인, `.env` 열람 아님)보다
  충분히 낮게 보수적으로 설정.
- 슬롯을 못 얻으면 `asyncio.sleep`으로 짧게(기본 1초 간격) 대기했다가
  재시도한다 — `asyncio.to_thread`로 파일 I/O를 이벤트 루프 밖에서
  수행해 블로킹을 피한다.
- 대기 상한(`DEFAULT_MAX_WAIT_SECONDS=15.0`)을 넘으면 **대기를
  포기하고 즉시 통과**시킨다(fail-open) — per-agent timeout(30초)을
  침범하지 않기 위해서다. 상태 파일 접근 자체가 실패해도(파일시스템
  오류 등) 마찬가지로 즉시 통과시킨다. 두 경우 모두 **경고 로그를
  남긴다** — "조용한 bypass"가 아니다.
- **import-time 부작용 없음**: 모듈을 import하는 것만으로는 파일/
  디렉터리를 만들지 않는다(`subprocess_io.py`와 동일한 설계 원칙) —
  이 harness의 dev-validation 컨테이너(`/workspace` read-only)에서도
  이 모듈 자체는 안전하게 import/단위 테스트할 수 있다.

`scripts/run_agent_subprocess.py`의 FDC 호출 직전(실제 provider_client
가 있을 때만 — `StubFinalDecisionComposerAgent`는 네트워크 호출이
없으므로 대기시키지 않음)에 `wait_for_fdc_slot()`을 호출한다.

## 정책 영향 여부

없음. `decision_type` 정책, `translation.py`, `execution_service.py`,
EV gate, EI/AR/AC wiring, fallback `HOLD` 정책 — 전부 미변경. PR #286의
`reason_codes`/`summary` fallback 분류 개선은 그대로 유지된다.

## 관측성

rate limiter가 대기했거나 bypass했을 때 `_diag()` 파일과 `logger`에
남는다:
- 대기 후 성공: `INFO "FDC rate limiter: X.Xs 대기 후 호출 허용..."`
- 대기 상한 초과 bypass: `WARNING "...제한 없이 통과시킴(bypass,
  max_wait_seconds=... 초과)."`
- 상태 파일 오류 bypass: `WARNING "...상태 파일(...) 접근 실패 —
  제한 없이 통과시킴(bypass). ..."`

사용자 지침에 따라 정상 호출 성공 시(대기 없음)에는 `reason_codes`에
아무것도 추가하지 않는다 — DB schema/저장 필드는 변경하지 않고, 관측은
로그로만 남긴다.

## 검증 명령과 결과

| 명령 | 결과 |
|---|---|
| `test-file tests/services/ai_agents/test_fdc_rate_limiter.py`(신규) | 8 passed |
| `test-file tests/services/ai_agents/test_agents.py` | 124 passed(PR #286 fallback 분류 테스트 그대로 유지) |
| `test-file tests/scripts/test_run_decision_loop.py` | 130 passed(rollback으로 7건 감소, 나머지 전부 통과) |
| `accept backend-file src/agent_trading/services/ai_agents/fdc_rate_limiter.py`(신규 파일) | PASS — 자동 매칭된 신규 테스트 파일 실행, 0 실패 |
| `accept script-file scripts/run_agent_subprocess.py`(선택) | FAIL — `tests/scripts/test_fdc_skip.py`가 `/workspace` read-only 인프라 이슈로 실패. PR #277~#286과 동일한 사전 존재 인프라 이슈(이번 PR과 무관) |
| `accept backend-runtime` / `architecture` / `no-bypass` / `style` / `docs` | 전부 PASS |

**회귀 테스트 유효성 검증**: `fdc_rate_limiter.py`의 상한 체크 로직을
임시로 비활성화한 뒤 재실행해, 신규 테스트 4건이 실제로 실패함을
확인했다(대기/bypass/동시성 관련 테스트들이 정확히 잡아냄). 복구 후
8건 전체 재통과 확인.

## 미검증 사항

- Gemini 실제 계약 RPM 한도(`.env` 열람 금지) — 60초당 10회라는
  기본값이 충분히 안전한지, 혹은 과도하게 보수적인지는 재배포 후
  실측 필요.
- 파일 락 기반 limiter가 실제 운영 부하(수십 개 동시 subprocess)에서
  파일 I/O 경합 자체로 유의미한 오버헤드를 만드는지.
- `docker-compose.yml`에 뭔가 새로 배선해야 할 필요는 없다(이 PR은
  env var를 쓰지 않고 코드 상수로만 정책을 정의하므로) — 단, 이
  사실 자체는 배포 후 재확인 권장.

## 배포 후 실측 항목

- 429 발생 건수(동일 크기 사이클 기준, 기준선 72건 대비).
- `decision_json.reason_codes`의 `provider_rate_limit` fallback
  비율(기준선 47.2%/50.0% 대비).
- cycle wall-clock(기준선 30초 대비 — 동시성은 5로 복원됐으므로
  이론상 30초 근처로 돌아가야 하고, rate limiter 대기가 추가되면
  그만큼만 늘어야 한다).
- `logger`/`_diag()`에서 "FDC rate limiter" 대기/bypass 로그 발생
  빈도 — bypass가 잦으면 정책값(60초당 10회, 대기 상한 15초)을
  재조정해야 한다는 신호.
- HOLD fallback 비율, BUY/APPROVE 전환율 변화(rate limiter 도입이
  판단 분포 자체를 왜곡하지 않는지 확인).
