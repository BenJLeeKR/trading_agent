# Near-Real Ops Scheduler Runbook — 2026-05-14

> **검증 시각**: 2026-05-13 16:49 KST (전일 smoke)
> **KIS_ENV**: paper
> **Python**: 3.14.4
> **스케줄러**: `scripts/run_near_real_ops_scheduler.py`

---

## 목차

1. [스케줄러 개요](#1-스케줄러-개요)
2. [Smoke 검증 결과](#2-smoke-검증-결과)
3. [코드 흐름 분석](#3-코드-흐름-분석)
4. [내일 장전 실행 절차 (tmux)](#4-내일-장전-실행-절차-tmux)
5. [중복 실행 리스크 분석](#5-중복-실행-리스크-분석)
6. [P0 한계](#6-p0-한계)
7. [사람이 확인해야 할 체크포인트](#7-사람이-확인해야-할-체크포인트)
8. [비상 대응](#8-비상-대응)

---

## 1. 스케줄러 개요

[`scripts/run_near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py)는 단일 프로세스로 하루 운영을 관리하는 in-application 스케줄러입니다.

### Phase 전환 시간 (KST)

| Phase | 시작 | 종료 | 설명 |
|-------|------|------|------|
| Pre-Market | 08:00 | 08:50 | 1회 실행: snapshot sync + event ingestion + post-submit sync |
| Intraday | 08:50 | 15:30 | 반복 실행: snapshot/event/decision/post_submit (300s 간격) |
| End-of-Day | 15:30 | 16:30 | 1회 실행: snapshot sync + post-submit sync |

### 실행되는 서브 명령어

| 태스크 | 명령어 | 기본 간격 |
|--------|--------|----------|
| Snapshot Sync | `python3 scripts/run_snapshot_sync_loop.py --max-cycles 1` | 300s |
| Event Ingestion | `python3 -m scripts.run_event_ingestion_loop --count 1 --output json` | 300s |
| Decision | `python3 -m scripts.run_paper_decision_loop --count 1 --output json --submit` | 300s |
| Post-Submit Sync | `python3 scripts/run_post_submit_sync_loop.py --once` | 30s |

### Submit 조건

- `max_submit_per_day=1` (기본값)
- FDC가 `APPROVE`일 때만 submit 실행
- `_is_submit_consuming_result()`가 stdout에서 `SUBMITTED`/`RECONCILE_REQUIRED` 감지 시 `submit_count` 증가
- `submit_count >= max_submit_per_day` 이후에는 모든 decision이 `--dry-run` 모드로 전환

---

## 2. Smoke 검증 결과

### 2.1 `--help` 출력 ✅

```
usage: run_near_real_ops_scheduler.py [-h] [--run-date RUN_DATE]
                                      [--pre-market-start PRE_MARKET_START]
                                      [--intraday-start INTRADAY_START]
                                      [--market-close MARKET_CLOSE]
                                      [--end-of-day-end END_OF_DAY_END]
                                      [--snapshot-interval SNAPSHOT_INTERVAL]
                                      [--event-interval EVENT_INTERVAL]
                                      [--decision-interval DECISION_INTERVAL]
                                      [--post-submit-interval POST_SUBMIT_INTERVAL]
                                      [--tick-seconds TICK_SECONDS]
                                      [--task-timeout TASK_TIMEOUT]
                                      [--max-submit-per-day MAX_SUBMIT_PER_DAY]
                                      [--skip-pre-market] [--once] [--run-eod]
```

### 2.2 `--once --skip-pre-market` 실행 결과 ✅

```
실행 명령어:
  python3 scripts/run_near_real_ops_scheduler.py --once --skip-pre-market

결과:
  task=snapshot_sync        ok=True  duration=0.67s
  task=event_ingestion      ok=True  duration=0.60s
  task=decision_submit_gate ok=True  duration=8.86s  (FDC HOLD → submit_count=0)
  task=post_submit_sync     ok=True  duration=0.39s

  failed_tasks : 0
  submit_count : 0
  exit code    : 0
```

**참고**: `--skip-pre-market`을 줬지만 `snapshot_sync`와 `event_ingestion`이 실행되었습니다. 이는 `--once` 모드에서 intraday tasks가 초기 `next_run_at=now`로 설정되어 `due(now)`를 만족했기 때문입니다. **의도된 동작**이며, 연속 모드에서는 phase 시간 제어가 정상 동작합니다.

### 2.3 Decision 상세

- `decision_submit_gate`가 `--submit` 모드로 실행됨
- FDC decision: `HOLD` (APPROVE 아님)
- `_is_submit_consuming_result()` → `False` → `submit_count` 증가 없음
- **submit 실행되지 않음** ✅ (사용자 규칙 준수)

---

## 3. 코드 흐름 분석

### 3.1 연속 모드 루프 (`_run_scheduler()`)

```
while not stop_event:
    now = datetime.now(KST)
    
    if now >= pre_market_at AND not pre_market_done AND not skip_pre_market:
        _run_pre_market()  # 1회: snapshot + event + post_submit
    
    if intraday_at <= now < market_close_at:
        _run_intraday_due_tasks()  # 반복: due된 태스크 실행
    
    if now >= market_close_at AND not end_of_day_done:
        _run_end_of_day()  # 1회: snapshot + post_submit
    
    if now.date() > run_date OR now >= end_at:
        break  # 16:30 KST 또는 다음 날짜 → 종료
    
    await asyncio.sleep(tick_seconds)  # 기본 5초
```

### 3.2 Intraday 태스크 스케줄링 (`_run_intraday_due_tasks()`)

각 태스크는 `ScheduledTask` 객체로 관리되며, `next_run_at`이 현재 시간보다 이전이면 실행됩니다. 실행 후 `next_run_at = now + interval`로 갱신됩니다.

```
순서:
1. snapshot due? → 실행 (300s 간격)
2. event due? → 실행 (300s 간격)
3. decision due? → 실행 (300s 간격, submit_count에 따라 dry-run/submit 분기)
4. post_submit due? → 실행 (30s 간격)
```

### 3.3 Decision 분기 로직 (DB 기반 budget 조회 통합)

```python
# _run_intraday_due_tasks() — DB 기반 submit budget 조회
db_submit_count = await _get_db_submit_count(state.run_date)
effective_submit_count = max(state.submit_count, db_submit_count)
dry_run = effective_submit_count >= max_submit_per_day  # 기본 max_submit_per_day=1
if not dry_run and _is_submit_consuming_result(result):
    state.submit_count += 1
```

- 첫 번째 decision cycle: `state.submit_count=0`, `db_submit_count=0` → `effective=0 < 1` → `--submit` 모드
- FDC가 APPROVE를 내고 submit 성공 시: `state.submit_count=1`, `db_submit_count=1`
- 이후 모든 decision cycle: `effective=1 >= 1` → `--dry-run` 모드
- **Crash/restart 시**: `state.submit_count=0`이지만 `db_submit_count=1` → `effective=1 >= 1` → `--dry-run` ✅
- **DB 장애 시**: `_get_db_submit_count()`가 `DEFAULT_MAX_SUBMIT_PER_DAY=1` 반환 → conservative dry-run

### 3.4 `_is_submit_consuming_result()` 판정 로직

```python
def _is_submit_consuming_result(result: CommandResult) -> bool:
    if not result.ok:
        return False
    for obj in _extract_json_objects(result.stdout):
        status = str(obj.get("status", "")).upper()
        if status in {"SUBMITTED", "RECONCILE_REQUIRED"}:
            return True
    return False
```

- stdout에서 JSON 객체를 추출하여 `status` 필드 확인
- `SUBMITTED` 또는 `RECONCILE_REQUIRED` 상태만 submit 소비로 간주
- `DRY_RUN`, `SKIPPED`, `ERROR`, `UNKNOWN`, `HOLD` 등은 submit 소비하지 않음

---

## 4. 내일 장전 실행 절차 (tmux)

### 4.1 사전 조건 확인 (07:50 KST)

```bash
# 1. KIS_ENV 확인
echo "KIS_ENV=$KIS_ENV"  # 반드시 paper

# 2. .env 파일 존재 확인
ls -la .env

# 3. token cache 존재 확인
ls -la .cache/kis_token.json

# 4. DB 연결 확인
python3 -c "
import asyncio
from agent_trading.db.connection import health_check, DatabaseConfig
from dotenv import load_dotenv
import os
load_dotenv()
cfg = DatabaseConfig()
result = asyncio.run(health_check(cfg))
print(f'DB health: {result}')
"
```

### 4.2 tmux 세션 생성 및 스케줄러 실행 (07:55 KST)

```bash
# tmux 세션 생성
tmux new-session -d -s near-real-ops-2026-05-14

# 세션 내에서 .env 로드 후 스케줄러 실행
tmux send-keys -t near-real-ops-2026-05-14 'cd /workspace/agent_trading' Enter
tmux send-keys -t near-real-ops-2026-05-14 'set -a; source .env; set +a' Enter
tmux send-keys -t near-real-ops-2026-05-14 'python3 scripts/run_near_real_ops_scheduler.py --run-date 2026-05-14 2>&1 | tee /tmp/near-real-ops-2026-05-14.log' Enter
```

### 4.3 로그 확인

```bash
# 실시간 로그 확인 (tmux attach)
tmux attach -t near-real-ops-2026-05-14

# 분리 (detach): Ctrl+B, D

# 로그 파일 확인
tail -f /tmp/near-real-ops-2026-05-14.log

# 특정 패턴 검색
grep -E '(phase=|failed|submit_count|ERROR)' /tmp/near-real-ops-2026-05-14.log
```

### 4.4 중단 방법

```bash
# 방법 1: SIGTERM (graceful shutdown)
tmux send-keys -t near-real-ops-2026-05-14 'C-c'

# 방법 2: 프로세스 직접 종료
pkill -f "run_near_real_ops_scheduler.py.*2026-05-14"

# 방법 3: tmux 세션 종료
tmux kill-session -t near-real-ops-2026-05-14
```

### 4.5 장중 모니터링 명령어

```bash
# 1. 스케줄러 프로세스 생존 확인
ps aux | grep run_near_real_ops_scheduler

# 2. 최근 sync 상태
python3 -c "
import asyncio, os
from dotenv import load_dotenv
load_dotenv()
from agent_trading.db.connection import DatabaseConfig, create_pool, get_pool, close_pool
cfg = DatabaseConfig()
async def check():
    pool = await create_pool(cfg)
    row = await pool.fetchrow('SELECT started_at, status FROM snapshot_sync_runs ORDER BY started_at DESC LIMIT 1')
    print(f'Last sync: {row[\"started_at\"]} status={row[\"status\"]}')
    await close_pool()
asyncio.run(check())
"

# 3. Submit 발생 여부
python3 -c "
import asyncio, os
from dotenv import load_dotenv
load_dotenv()
from agent_trading.db.connection import DatabaseConfig, create_pool, close_pool
cfg = DatabaseConfig()
async def check():
    pool = await create_pool(cfg)
    row = await pool.fetchrow(\"SELECT COUNT(*) as cnt FROM order_requests WHERE status='pending_submit'\")
    print(f'pending_submit: {row[\"cnt\"]}')
    row = await pool.fetchrow(\"SELECT COUNT(*) as cnt FROM order_requests WHERE created_at::date = '2026-05-14'::date\")
    print(f'today orders: {row[\"cnt\"]}')
    await close_pool()
asyncio.run(check())
"
```

---

## 5. 중복 실행 리스크 분석

### 5.1 동일 run_date 중복 실행

| 시나리오 | 리스크 | 설명 |
|----------|--------|------|
| 같은 날 2번 실행 | 🔴 **높음** | `run_date`가 같으면 중복 실행을 막는 장치가 없음. `submit_count`가 각각 1씩 증가하여 최대 2회 submit 가능 |
| 다른 날짜로 실행 | 🟢 없음 | `run_date`가 다르면 별도 운영일로 처리 |

**영향**: 동일 `run_date`에 두 프로세스가 동시에 실행되면 `max_submit_per_day=1`이 프로세스별로 적용되어 최대 2회 submit될 수 있습니다.

**방어**: `_is_submit_consuming_result()`는 실제 submit 성공 여부를 판단하므로, FDC가 APPROVE를 내지 않으면(HOLD) 실제 submit은 발생하지 않습니다.

### 5.2 기존 sync loop와의 충돌

| 시나리오 | 리스크 | 설명 |
|----------|--------|------|
| `run_snapshot_sync_loop.py` 별도 실행 | 🟢 낮음 | 스케줄러 내부에서도 동일 스크립트를 subprocess로 호출. DB 레벨에서 중복은 무해함 (멱등성) |
| `run_paper_decision_loop.py` 별도 실행 | 🟡 **중간** | 별도 프로세스에서 decision 실행 시 스케줄러의 `submit_count`와 무관하게 submit 가능 |

### 5.3 프로세스 비정상 종료 후 재시작

| 시나리오 | 리스크 | 설명 |
|----------|--------|------|
| Pre-Market 도중 crash → 재시작 | 🟢 낮음 | `pre_market_done=False`이므로 재시작 시 Pre-Market 재실행 (멱등) |
| Intraday 도중 crash → 재시작 | 🟢 **낮음** (2026-05-13 개선) | `submit_count`가 초기화(0)되어도 `_get_db_submit_count()`가 `trading.order_requests`에서 당일 budget 소비 상태 count를 조회하여 `effective = max(0, db_count)`로 dry-run 판정 |
| EOD 도중 crash → 재시작 | 🟢 낮음 | `end_of_day_done=False`이므로 EOD 재실행 (멱등) |

---

## 6. P0 한계

| # | 한계 | 영향 | 해결 방안 (향후) |
|---|------|------|-----------------|
| 1 | **중복 실행 방지 장치 없음** | 동일 run_date에 여러 프로세스 실행 시 submit 중복 | DB 기반 실행 락 (advisory lock) 또는 PID 파일 |
| 2 | ~~**submit_count 인메모리**~~ | ~~프로세스 재시작 시 초기화~~ | **✅ DB 기반 해결 (2026-05-13)** — `_get_db_submit_count()`가 `trading.order_requests`를 조회 |
| 3 | **pre_market_done/end_of_day_done 인메모리** | 프로세스 재시작 시 phase 재실행 | DB에 phase 완료 상태 저장 |
| 4 | **`_is_submit_consuming_result()` stdout 파싱 의존** | JSON 출력 형식 변경 시 오탐 가능 | 구조화된 exit code 또는 별도 상태 파일 |
| 5 | **`run_date` 검증 없음** | 과거 날짜로 실행 가능 | `run_date`가 오늘보다 이전이면 경고 또는 거부 |
| 6 | **`--skip-pre-market` 사용 시 intraday 첫 tick에 snapshot/event 실행** | Pre-Market과 Intraday 경계에서 중복 실행 | `--once` 모드에서 intraday tasks 시작 시간을 `now`가 아닌 `intraday_at`으로 설정 |

---

## 7. 사람이 확인해야 할 체크포인트

### 7.1 실행 전 (07:50 KST)

- [ ] `KIS_ENV=paper` 확인
- [ ] `.env` 파일 존재 및 필수 변수 적재 확인
- [ ] `.cache/kis_token.json` 존재 확인 (없으면 `get_quote()`로 1회 호출)
- [ ] DB 연결 정상 확인 (`health_check()`)
- [ ] 이전 운영일(2026-05-13)의 `reconcile_required` 6건 상태 변화 확인
- [ ] `pending_submit` = 0건 확인

### 7.2 Pre-Market 완료 후 (08:10 KST)

- [ ] 로그에 `phase=pre-market complete` 출력 확인
- [ ] snapshot sync 정상 완료 확인
- [ ] event ingestion 정상 완료 확인
- [ ] post-submit sync 정상 완료 확인

### 7.3 Intraday 첫 decision 후 (08:55 KST)

- [ ] FDC decision 확인 (APPROVE / HOLD)
- [ ] `submit_count` 변화 확인
- [ ] `pending_submit` 발생 여부 확인

### 7.4 장중 모니터링 (30분 간격)

- [ ] 스케줄러 프로세스 생존 확인
- [ ] 로그에 `ERROR` 미발생 확인
- [ ] `failed_tasks` = 0 유지 확인
- [ ] `submit_count` 상태 확인

### 7.5 EOD 완료 후 (15:35 KST)

- [ ] 로그에 `phase=end-of-day complete` 출력 확인
- [ ] 최종 summary에서 `failed_tasks` = 0 확인
- [ ] `submit_count` 최종값 확인
- [ ] 프로세스 정상 종료 확인 (exit code 0)

### 7.6 보고서 작성 (15:40 KST)

- [ ] `plans/paper_daily_ops_report_2026-05-14.md` 업데이트
- [ ] universe / 후보 종목 상태 기록
- [ ] 이벤트 수집 결과 기록
- [ ] AI decision 결과 기록
- [ ] submit 발생 여부 기록
- [ ] post-submit sync / reconciliation 결과 기록

---

## 8. 비상 대응

### 8.1 스케줄러 비정상 종료

```bash
# 1. 프로세스 확인
ps aux | grep run_near_real_ops_scheduler

# 2. 로그 확인
tail -50 /tmp/near-real-ops-2026-05-14.log

# 3. 재시작 (DB 기반 budget 조회로 submit_count=0이어도 안전)
#    _get_db_submit_count()가 trading.order_requests에서 당일 budget 소비 상태를 조회하므로
#    --max-submit-per-day 0 없이 일반 실행 가능
tmux send-keys -t near-real-ops-2026-05-14 'C-c'
tmux send-keys -t near-real-ops-2026-05-14 'python3 scripts/run_near_real_ops_scheduler.py --run-date 2026-05-14 2>&1 | tee -a /tmp/near-real-ops-2026-05-14.log' Enter
```

### 8.2 Submit이 필요하나 FDC가 HOLD

- **강제 APPROVE 금지** (사용자 규칙)
- 원인 분석 후 다음 운영일에 반영
- 수동 submit도 금지

### 8.3 Sync Loop 실패

```bash
# 별도 프로세스로 1회 강제 실행
python3 scripts/run_snapshot_sync_loop.py --max-cycles 1
```

### 8.4 DB 연결 장애

```bash
# DB 재연결 확인
python3 -c "
import asyncio
from agent_trading.db.connection import health_check, DatabaseConfig
from dotenv import load_dotenv
load_dotenv()
cfg = DatabaseConfig()
result = asyncio.run(health_check(cfg))
print(f'DB health: {result}')
"
```

---

## 부록: CLI 옵션 참조

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--run-date` | 오늘 (KST) | 운영일 (YYYY-MM-DD) |
| `--pre-market-start` | 08:00 | Pre-Market 시작 시간 |
| `--intraday-start` | 08:50 | Intraday 시작 시간 |
| `--market-close` | 15:30 | 장 종료 시간 |
| `--end-of-day-end` | 16:30 | EOD 종료 시간 |
| `--snapshot-interval` | 300 | Snapshot sync 간격 (초) |
| `--event-interval` | 300 | Event ingestion 간격 (초) |
| `--decision-interval` | 300 | Decision cycle 간격 (초) |
| `--post-submit-interval` | 30 | Post-submit sync 간격 (초) |
| `--tick-seconds` | 5 | 메인 루프 tick 간격 (초) |
| `--task-timeout` | 240 | 각 태스크 타임아웃 (초) |
| `--max-submit-per-day` | 1 | 일일 최대 submit 횟수 |
| `--skip-pre-market` | False | Pre-Market 생략 |
| `--once` | False | 1회 실행 후 종료 (smoke) |
| `--run-eod` | False | `--once`와 함께 EOD도 실행 |

## 부록: 실행 명령어 모음

```bash
# === 내일 장전 실행 ===
tmux new-session -d -s near-real-ops-2026-05-14
tmux send-keys -t near-real-ops-2026-05-14 'cd /workspace/agent_trading && set -a; source .env; set +a && python3 scripts/run_near_real_ops_scheduler.py --run-date 2026-05-14 2>&1 | tee /tmp/near-real-ops-2026-05-14.log' Enter

# === 로그 확인 ===
tail -f /tmp/near-real-ops-2026-05-14.log

# === 중단 ===
tmux kill-session -t near-real-ops-2026-05-14

# === Smoke 테스트 (재현용) ===
python3 scripts/run_near_real_ops_scheduler.py --once --skip-pre-market

# === Dry-run 전용 실행 (submit 없음) ===
python3 scripts/run_near_real_ops_scheduler.py --run-date 2026-05-14 --max-submit-per-day 0
```
