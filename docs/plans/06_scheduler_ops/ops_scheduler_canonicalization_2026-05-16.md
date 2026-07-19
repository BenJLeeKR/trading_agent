# Scheduler Naming Canonicalization — 구현 보고서

> **작성일**: 2026-05-16 12:14 KST  
> **목적**: `near_real` 중심 명칭을 환경 중립적인 `ops_scheduler`로 정리  
> **KIS_ENV**: paper/live 공통 (환경 중립)

---

## Canonical Name Table

| 항목 | Canonical | 변경 전 |
|------|-----------|---------|
| Python 식별자/모듈 | `ops_scheduler` | `near_real_ops_scheduler` |
| Docker service명 | `ops-scheduler` | `near-real-scheduler` |
| Logger name | `ops_scheduler` | `near_real_ops_scheduler` |
| Lock key 주석 | `OPS_SCHEDULER` | `NEAR_REAL` |
| 파일명 (entrypoint) | `run_ops_scheduler.py` | `run_near_real_ops_scheduler.py` |
| 테스트 파일명 | `test_run_ops_scheduler.py` | `test_run_near_real_ops_scheduler.py` |

---

## 변경 파일 목록

| # | 파일 | 변경 유형 | 상태 |
|---|------|----------|------|
| 1 | [`scripts/run_ops_scheduler.py`](../scripts/run_ops_scheduler.py) | **신규** — canonical entrypoint (import forwarding) | ✅ |
| 2 | [`scripts/run_near_real_ops_scheduler.py`](../scripts/run_near_real_ops_scheduler.py) | **수정** — deprecation 주석, logger name, 로그 메시지, formatter | ✅ |
| 3 | [`docker-compose.yml`](../docker-compose.yml) | **수정** — service명 `ops-scheduler`, container명, 주석, command | ✅ |
| 4 | [`src/agent_trading/services/market_session.py`](../src/agent_trading/services/market_session.py) | **수정** — lock key 주석 (`OPS_SCHEDULER`), 로그 메시지 (key값 유지) | ✅ |
| 5 | [`tests/scripts/test_run_ops_scheduler.py`](../tests/scripts/test_run_ops_scheduler.py) | **신규** — canonical test entrypoint (re-export) | ✅ |
| 6 | [`tests/scripts/test_run_near_real_ops_scheduler.py`](../tests/scripts/test_run_near_real_ops_scheduler.py) | **수정** — deprecation 주석, docstring | ✅ |
| 7 | [`plans/near_real_scheduler_runbook_2026-05-14.md`](../plans/near_real_scheduler_runbook_2026-05-14.md) | **수정** — `run_ops_scheduler.py` 참조로 업데이트 (9개소) | ✅ |
| 8 | [`plans/near_real_scheduler_docker_service_p3_implementation_2026-05-16.md`](../plans/near_real_scheduler_docker_service_p3_implementation_2026-05-16.md) | **수정** — `run_ops_scheduler.py` 참조로 업데이트 (5개소) | ✅ |
| 9 | [`plans/near_real_internal_scheduler_p0.md`](../plans/near_real_internal_scheduler_p0.md) | **수정** — `run_ops_scheduler.py` 참조로 업데이트 (2개소) | ✅ |

---

## 세부 변경 내역

### 1. `scripts/run_ops_scheduler.py` (신규)

Canonical entrypoint로, 기존 구현 모듈(`scripts.run_near_real_ops_scheduler`)을 import forwarding합니다.

```python
# Usage:
#   python3 scripts/run_ops_scheduler.py [--after-hours]

from scripts.run_near_real_ops_scheduler import (
    NearRealOpsScheduler, main, __main__,
)
```

### 2. `scripts/run_near_real_ops_scheduler.py` (수정)

| 위치 | 변경 전 | 변경 후 |
|------|---------|---------|
| L2 | `Near-real operations scheduler` | `Operations scheduler` |
| L4 | `KIS near-real operating day` | `KIS trading day` |
| L103 | `logger = logging.getLogger("near_real_ops_scheduler")` | `logger = logging.getLogger("ops_scheduler")` |
| L748 | `near-real scheduler summary` | `ops-scheduler summary` |
| L1054 | `🚀 Near-Real Scheduler starting up` | `🚀 Ops Scheduler starting up` |
| L1073 | `Run the near-real operations scheduler.` | `Run the operations scheduler.` |
| L1359 | `near-real-scheduler: %(message)s` | `ops-scheduler: %(message)s` |

파일 상단에 deprecation 주석 추가:
```python
"""
Operations scheduler — KIS market session aware trading scheduler.

NOTE: This module is kept for backward compatibility.
The canonical entrypoint is scripts.run_ops_scheduler.
"""
```

### 3. `docker-compose.yml` (수정)

| 위치 | 변경 전 | 변경 후 |
|------|---------|---------|
| L191 주석 | `near-real-scheduler service` | `ops-scheduler service` |
| L247 주석 | `# ---- Near-Real Ops Scheduler ------` | `# ---- Operations Scheduler ------` |
| L248 주석 | `near-real operating day` | `trading day` |
| L251 서비스명 | `near-real-scheduler:` | `ops-scheduler:` |
| L256 container_name | `agent_trading-scheduler` | `agent_trading-ops-scheduler` |
| L257 command | `scripts/run_near_real_ops_scheduler.py` | `scripts/run_ops_scheduler.py` |

### 4. `src/agent_trading/services/market_session.py` (수정)

| 위치 | 변경 전 | 변경 후 |
|------|---------|---------|
| L38 주석 | `# Encoded "NEAR_REAL" as int64` | `# Encoded "OPS_SCHEDULER" as int64` |
| L49 | `Another scheduler instance holds the lock` | `Another ops-scheduler instance holds the lock` |
| L69 | `Scheduler advisory lock acquired` | `Ops-scheduler advisory lock acquired` |
| L78 | `Scheduler advisory lock released` | `Ops-scheduler advisory lock released` |

**Lock key 숫자값 유지**: `0x4E454152_5245414C` (변경 없음)

### 5. `tests/scripts/test_run_ops_scheduler.py` (신규)

```python
"""Tests for the ops scheduler (canonical entrypoint)."""
from tests.scripts.test_run_near_real_ops_scheduler import *  # re-export
```

### 6. `tests/scripts/test_run_near_real_ops_scheduler.py` (수정)

- Docstring: deprecation 주석 추가, canonical entrypoint 명시

---

## 검증 결과

### Docker Compose Config
```
$ docker compose config -q
Exit code: 0  ✅ (env var warnings only, cosmetic)
```

### Docker Build
```
$ docker compose build ops-scheduler
agent_trading-app:latest Built  ✅
```

### 테스트 결과

| 테스트 스위트 | 통과 | 설명 |
|--------------|------|------|
| `test_run_ops_scheduler.py` | **60/60** ✅ | Canonical entrypoint |
| `test_run_near_real_ops_scheduler.py` | **60/60** ✅ | Legacy wrapper (backward compat) |
| `test_market_session.py` | **65/65** ✅ | Advisory lock |
| `test_market_state_client.py` | **65/65** ✅ | Market state |
| **계** | **185/185** ✅ | Scheduler/session 관련 전면 통과 |

### 사전 존재하는 실패 (변경 무관)

| 테스트 | 사유 |
|-------|------|
| `test_readyz_stale_sync` | Health check timing issue |
| `test_no_workers` | Event ingestion loop worker count test |

### 남은 `near_real` 참조 분석

| 위치 | 남은 참조 | 사유 |
|------|----------|------|
| `scripts/run_ops_scheduler.py` | `run_near_real_ops_scheduler` import | **의도적** — backward compat |
| `tests/scripts/test_run_near_real_ops_scheduler.py` | 모듈 import | **의도적** — backward compat |
| `tests/scripts/test_run_ops_scheduler.py` | re-export from legacy | **의도적** — backward compat |
| `design/*.md` | `near_real` 설명 | 과거 설계 문서 |
| `plans/*.md` (기타) | `near_real` 참조 | 과거 계획 문서 (rename 불필요) |

**소스 코드(`src/`)에 남은 `near_real`/`near-real`/`NEAR_REAL` 참조: 0건** ✅

---

## 완료 조건 점검

| # | 조건 | 상태 |
|---|------|------|
| 1 | `scripts/run_ops_scheduler.py` 생성 (canonical entrypoint) | ✅ |
| 2 | `scripts/run_near_real_ops_scheduler.py` 내부 문자열 정리 + deprecation 주석 | ✅ |
| 3 | `docker-compose.yml` service명 `ops-scheduler`로 변경 | ✅ |
| 4 | `market_session.py` advisory lock 주석/로그 업데이트 (key 유지) | ✅ |
| 5 | `tests/scripts/test_run_ops_scheduler.py` 생성 (canonical test) | ✅ |
| 6 | `tests/scripts/test_run_near_real_ops_scheduler.py` 내부 문자열 정리 | ✅ |
| 7 | plans 내부 참조 업데이트 | ✅ |
| 8 | `docker compose config -q` 통과 | ✅ |
| 9 | 모든 테스트 통과 (회귀 없음) | ✅ (185/185) |
| 10 | 보고서 작성 | ✅ |
