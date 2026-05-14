# Near-Real Internal Scheduler P0

## 목적

`crontab` 같은 외부 스케줄러 없이, 단일 Python 프로세스가 KST 운영 시간대에 맞춰 near-real 운영 루틴을 실행한다.

현재 `KIS_ENV=paper`는 live-like near-real 운영 환경으로 취급한다. 실제 live 전환은 운영자가 `.env`를 직접 교체한 뒤 동일 스케줄러를 실행한다.

## 실행 파일

```bash
python3 scripts/run_near_real_ops_scheduler.py --run-date 2026-05-14
```

Smoke 검증:

```bash
python3 scripts/run_near_real_ops_scheduler.py --once --skip-pre-market
```

## 기본 시간표 (KST)

| 구간 | 시간 | 실행 |
|---|---:|---|
| Pre-Market | 08:00 이후 1회 | snapshot sync 1회, event ingestion 1회, post-submit sync 1회 |
| Intraday | 08:50–15:30 | snapshot sync 300초, event ingestion 300초, decision 300초, post-submit sync 30초 |
| End-of-Day | 15:30 이후 1회 | snapshot sync 1회, post-submit sync 1회 |

## Submit 안전장치

| 조건 | 동작 |
|---|---|
| FDC `HOLD`/`WATCH`/`REJECT` | 기존 decision loop가 submit skip |
| FDC `APPROVE` + broker submit 성공 | `SUBMITTED` 또는 `RECONCILE_REQUIRED` 감지 |
| 당일 submit budget 소진 | 이후 decision cycle은 자동 dry-run |
| 기본 한도 | `--max-submit-per-day 1` |
| **DB 기반 budget 조회** (2026-05-13 추가) | 프로세스 crash/restart 후에도 `trading.order_requests`에서 당일 budget 소비 상태(`submitted`, `acknowledged`, `partially_filled`, `filled`, `reconcile_required`) count를 조회하여 `max(state.submit_count, db_submit_count)`로 dry-run 판정 |
| **DB 실패 시 fallback** | DB 쿼리 실패 시 conservative하게 `max_submit_per_day` 반환 → dry-run (submit 차단) |

## 기존 스크립트 재사용

스케줄러는 내부적으로 아래 명령을 shell 없이 `python3` subprocess로 실행한다.

```bash
python3 scripts/run_snapshot_sync_loop.py --max-cycles 1
python3 -m scripts.run_event_ingestion_loop --count 1 --output json
python3 -m scripts.run_paper_decision_loop --count 1 --output json --submit
python3 scripts/run_post_submit_sync_loop.py --once
```

Submit budget 소진 후 decision은 다음 명령으로 낮춰진다.

```bash
python3 -m scripts.run_paper_decision_loop --count 1 --output json --dry-run
```

## P0 한계

| 항목 | 상태 |
|---|---|
| DB 기반 scheduler run table | 미구현 |
| cross-process lock | 미구현 |
| 휴장일 캘린더 | 미구현 |
| Admin UI scheduler 상태 화면 | 미구현 |
| 알림/notification | 미구현 |
| ~~submit_count 인메모리~~ | **✅ DB 기반 해결 (2026-05-13)** — `_get_db_submit_count()`가 `trading.order_requests`를 조회하여 crash/restart survivable |

P0는 내일 supervised 운영을 시작하기 위한 최소 내부 스케줄러다. 1개월 무감시 운영 전에는 P1 하드닝이 필요하다.

