# Paper KIS 전역 REST 예산 공유 적용

## 배경

paper 환경은 KIS 제약상 사실상 1RPS로 움직여야 한다.  
기존에는 `submit_order()` 경로에 1초 pacing을 넣고, `ORDER` bucket refill도 `1.0/s`로 맞췄다.  
하지만 `global_rest` 자체가 프로세스별 메모리 `OperationBucket`으로 남아 있어서 다음 문제가 계속 남아 있었다.

- `app` 프로세스의 quote/조회 호출
- `ops-scheduler` 프로세스의 주문 제출 호출
- `reconciliation-worker` / snapshot / post-submit sync 등의 조회 호출

이들이 서로 다른 메모리 버킷을 쓰면, 각 프로세스는 “나는 아직 1RPS 안 넘었다”고 판단하지만 전체 합계는 1RPS를 초과할 수 있다.  
즉, paper 1RPS 제약을 **프로세스 간 합산 기준으로 강제하지 못하는 상태**였다.

## 확인 결과

컨테이너 내부 확인 기준으로, 수정 전 `app`와 `ops-scheduler` 모두:

- `budget_manager.global_rest` 타입 = `OperationBucket`
- 공유 파일 경로 = 없음

즉, paper 전역 예산이 실제로는 공유되지 않고 있었다.

## 적용한 수정

### 1. 설정 추가

`AppSettings.kis_shared_budget_file` 추가

- 환경변수: `KIS_SHARED_BUDGET_FILE`
- 기본값: `.cache/kis_paper_global_budget.json`

이 파일은 paper 환경에서만 의미가 있다.

### 2. paper KIS budget manager 생성 경로에 shared file 주입

다음 경로에서 `build_kis_budget_manager(..., shared_budget_file=settings.kis_shared_budget_file)`를 사용하도록 수정했다.

- `src/agent_trading/runtime/bootstrap.py`
- `src/agent_trading/brokers/snapshot_factory.py`
- `src/agent_trading/services/reconciliation_worker.py`
- `scripts/run_post_submit_sync_loop.py`
- `scripts/sync_kis_snapshots.py`
- `scripts/verify_order_truth.py`
- `scripts/run_decision_loop.py`

의미:

- 주문 제출
- quote fallback
- snapshot sync
- post-submit sync
- reconciliation truth 조회
- verify/backfill성 진단 스크립트

모두가 같은 paper global REST 버킷 파일을 보게 된다.

### 3. docker-compose 환경 전달

다음 서비스에 `KIS_SHARED_BUDGET_FILE` 전달을 추가했다.

- `app`
- `api`
- `ops-scheduler`
- `reconciliation-worker`

기본값은 `.cache/kis_paper_global_budget.json`이며, `.cache`는 이미 host volume으로 공유되고 있다.

### 4. FileBackedGlobalBucket 호환성 보강

`RateLimitBudgetManager.snapshot()`가 file-backed bucket에서도 동작하도록 아래 속성을 추가했다.

- `refill_rate`
- `utilization`

## 검증

### 테스트

- `pytest -q tests/brokers/test_rate_limit.py tests/brokers/test_kis_adapter_validation.py`
- 결과: `57 passed`

추가 검증 포인트:

- paper runtime wiring 시 `FileBackedGlobalBucket` 사용 테스트 추가

### 런타임 기대 결과

재기동 후 `app`, `ops-scheduler`, `reconciliation-worker`의 paper KIS adapter는 모두:

- `type(global_rest) == FileBackedGlobalBucket`
- `file_path == .cache/kis_paper_global_budget.json`

이어야 한다.

## 기대 효과

이제 paper 환경에서:

- 주문 제출
- quote/조회
- reconciliation성 조회

가 **프로세스 합산 기준으로 동일한 1RPS 전역 예산**을 공유한다.

따라서 이전처럼:

- `ops-scheduler`는 submit pacing을 지켰지만
- 다른 프로세스 quote/조회가 동시에 1RPS를 따로 써버려
- 실제 KIS 기준으로는 초과

하는 구조적 문제가 크게 줄어든다.

## 남은 확인

실서비스 재기동 후 컨테이너 내부에서 아래를 직접 확인해야 한다.

- `app`
- `ops-scheduler`
- `reconciliation-worker`

모두 같은 shared budget file을 가리키는지

## 비고

이번 수정은 **paper global_rest 공유**에 집중한 것이다.  
live 환경에는 적용하지 않는다. live는 `OperationBucket` 기반 in-process global bucket을 계속 사용한다.
