# 보고서: snapshot_sync uuid7 런타임 fix 및 risk_limit_snapshot 검증

**작성일**: 2026-05-18
**관련 Phase**: Phase AA → Phase AB

---

## 배경

Phase AA에서 `risk_limit_snapshots`가 0건임을 발견하고, Phase Z의 pipeline 복구에도 불구하고 snapshot sync가 실행되지 않는 근본 원인을 추적했습니다. 원인은 snapshot-sync 시작 직후 `ImportError: cannot import name 'uuid7' from 'agent_trading.repositories.base'`로 인해 snapshot-sync가 시작부터 죽고 있었던 것이었습니다.

---

## 1. Root cause

- `uuid7()` 함수가 이 프로젝트에 **구현된 적 없음**
- [`src/agent_trading/brokers/koreainvestment/snapshot.py:21`](../src/agent_trading/brokers/koreainvestment/snapshot.py:21): `from agent_trading.repositories.base import uuid7` — 존재하지 않는 이름 import
- [`src/agent_trading/repositories/base.py`](../src/agent_trading/repositories/base.py)에는 `uuid7`이 정의되어 있지 않음
- Phase Z에서 `RiskLimitSnapshotEntity(risk_limit_snapshot_id=uuid7(), ...)` 생성 코드를 추가했지만, `uuid7` import source를 검증하지 않음
- Python 3.14+의 표준 라이브러리 `uuid.uuid7()`을 사용해야 했으나, Dockerfile이 `python:3.12-slim`을 사용하고 있어 컨테이너 내부에서도 사용 불가

### 왜 테스트에서 안 터졌는가?
- `tests/` 디렉토리 전체에서 `uuid7` 사용 또는 import 0건
- `snapshot.py`의 `KISSyncSnapshotProvider.fetch_snapshot()`를 호출하는 테스트가 없거나, mock 처리되어 `uuid7()` 호출 자체에 도달하지 않음
- 즉, snapshot import/runtime smoke 테스트가 **존재하지 않음** → 테스트 갭

---

## 2. Import 경로 수정 내용

### 변경 파일 목록

| 파일 | 변경 내용 |
|------|----------|
| [`src/agent_trading/brokers/koreainvestment/snapshot.py`](../src/agent_trading/brokers/koreainvestment/snapshot.py) | `from agent_trading.repositories.base import uuid7` **삭제**, `from uuid import UUID, uuid4` → `from uuid import UUID, uuid4, uuid7` **확장** |
| [`Dockerfile`](../Dockerfile) | Python base image: `python:3.12-slim` → `python:3.14-slim` (uuid7 표준 라이브러리 지원) |

### 수정 전
```python
# snapshot.py L12
from uuid import UUID, uuid4
# snapshot.py L21
from agent_trading.repositories.base import uuid7  # ← 존재하지 않는 이름
```

### 수정 후
```python
# snapshot.py L12
from uuid import UUID, uuid4, uuid7
# (L21 삭제)
```

### 유사 dead import 점검 결과
- `grep -rn "from agent_trading.repositories.base import" src/`
- `snapshot.py:21` — **수정 완료** ✅
- `container.py:5` — `UnitOfWork` import, 정상 참조 ✅
- `postgres_uow.py:6` — `UnitOfWork` import, 정상 참조 ✅
- 다른 dead import 없음 ✅

---

## 3. snapshot-sync 런타임 검증 결과

### Docker Python 버전 문제
- **문제**: Dockerfile이 `python:3.12-slim` 사용 → `uuid.uuid7()` 미지원 → `ImportError`
- **해결**: [`Dockerfile`](../Dockerfile) base image를 `python:3.14-slim`으로 변경

### snapshot-sync 1 cycle 실행 결과
```bash
docker compose exec app python3 -m scripts.run_snapshot_sync_loop --max-cycles 1
```
- **결과: 성공** ✅
- `accounts=1 (ok=1 partial=0 fail=0 skip=0)`
- `positions=12 (skipped=0)`
- `cash=1`
- `errors=0`
- 소요 시간: **12.2초**
- KIS 모의투자 API 정상 인증 및 데이터 조회 완료

### /health 확인
```json
{"status":"ok","database":"connected","runtime_mode":"postgres","scheduler":{"healthy":true}}
```

---

## 4. risk_limit_snapshots DB 생성 결과 ✅

**2개 row 생성됨**

| risk_limit_snapshot_id | account_id | nav | created_at |
|---|---|---|---|
| `019e394d-a6ae-...` | `a44a02d1-...` | 31,035,850.00 | 2026-05-18 04:17:18 |
| `019e394d-ad23-...` | `a44a02d1-...` | 31,044,750.00 | 2026-05-18 04:17:20 |

### cash_balance_snapshots.total_asset과 nav 비교 ✅
**모든 row 일치** — `risk_limit_nav` == `cash_balance_snapshots.total_asset`

---

## 5. Follow-on 경로 점검

### DecisionOrchestrator 경로
- [`_build_sizing_inputs()`](../src/agent_trading/services/decision_orchestrator.py:1178)에는 Phase AA에서 추가한 NAV fallback이 존재
  ```
  priority 1: risk_limit_snapshot.nav (DB row 존재 시)
  priority 2: cash_balance_snapshot.total_asset (fallback)
  priority 3: None (constraint bypass)
  ```
- `risk_limit_snapshot`이 실제 DB에 생성되었으므로, 다음 snapshot-sync 실행 시 `AssembledContext.risk_limit_snapshot`이 채워질 가능성 높음
- 단, `decision_contexts` 테이블에 `risk_limit_snapshot_id` 컬럼이 없으므로 context 연결은 여전히 미해결

### AR/FDC prompt concentration ratio 전달
- 여전히 미해결 (Phase Y layer 2 진단 사항)
- `risk_limit_snapshot`이 살아났으므로 이제 concentration ratio를 prompt에 넣는 작업이 의미를 가짐

---

## 6. 남은 follow-up

1. **`decision_contexts`에 `risk_limit_snapshot_id` 컬럼 추가** — context와 risk_limit_snapshot 연결
2. **AR/FDC prompt에 portfolio concentration ratio 전달** — Phase Y layer 2
3. **snapshot import/runtime smoke 테스트 보강** — uuid7과 유사한 dead import 재발 방지
4. **Python 3.14로 업그레이드된 Dockerfile의 다른 영향도 점검** — `python:3.14-slim`에서 기존 라이브러리/기능이 정상 동작하는지 확인

---

## 7. 전체 변경 파일 목록

| 파일 | 변경 내용 | 영향 범위 |
|------|----------|----------|
| [`src/agent_trading/brokers/koreainvestment/snapshot.py`](../src/agent_trading/brokers/koreainvestment/snapshot.py) | uuid7 import 경로 수정 (L12 확장, L21 삭제) | snapshot-sync 런타임 복구 |
| [`Dockerfile`](../Dockerfile) | Python base image 3.12→3.14 | 컨테이너 내 uuid7 지원 |

---

## 8. Appendix: Phase AA → PhaseAB 연결

Phase AA에서 확인한 cash sync failure의 근본 원인이 Phase AB에서 밝혀졌습니다:

- Phase AA: `risk_limit_snapshots` 0건 — "cash sync 실패"로만 관찰
- Phase AB: 실제 원인은 **snapshot-sync 자체가 시작부터 `uuid7` ImportError로 죽어 있었음**
  - KIS API 호출조차 가기 전에 Python import 단계에서 실패
  - 당연히 `cash_balance_snapshot`도 생성 안 됨 → `risk_limit_snapshot`도 생성 안 됨
- 복구 후: snapshot-sync 정상 기동, cash_balance_snapshot + risk_limit_snapshot 모두 생성 확인
