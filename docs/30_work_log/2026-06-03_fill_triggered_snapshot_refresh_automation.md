# 2026-06-03 fill 발생 후 snapshot refresh 자동화

## 목적

- `plans/[PRIORITY_MAP] remaining_work_priority_map.md`의 P0 항목
  `Fill 발생 후 position/cash refresh 자동화`를 1차 구현한다.
- 체결 확정 직후 실행되는 `snapshot_refresh_cb` 경로를
  KIS 전용 legacy sync에서 broker-agnostic snapshot runner로 전환한다.
- 같은 sync cycle 안에서 동일 계좌에 대한 refresh가 여러 번 발생할 때
  중복 호출을 묶어 quota 소모를 줄인다.

## 배경

기존 `scripts/run_post_submit_sync_loop.py`의 `_build_refresh_callback()`은
다음 한계를 갖고 있었다.

1. `sync_kis_account_snapshots()` 직접 호출
   - KIS 전용 legacy 경로였다.
   - `risk_limit_snapshot`까지 한 번에 맞추는 broker-agnostic 경로가 아니었다.
2. 동일 계좌 dedupe 부재
   - 같은 cycle에서 여러 주문이 `FILLED` 판정되면 같은 계좌 snapshot refresh를
     반복 호출할 수 있었다.
3. runtime coupling이 약함
   - adapter에서 실제 REST client 속성명이 `_rest`인데
     callback은 `_rest_client`만 찾고 있었다.

즉, “fill 발생 후 position/cash refresh 자동화”는 부분적으로만 구현된 상태였고,
실제 운영에서는 동일 cycle 중복 refresh와 refresh 경로 일관성 문제가 남아 있었다.

## 변경 내용

### 1. refresh callback을 broker-agnostic runner로 전환

파일:
- `scripts/run_post_submit_sync_loop.py`

변경:
- `sync_kis_account_snapshots()` 직접 호출 제거
- `sync_account_snapshots()` 사용으로 전환
- `KISSyncSnapshotProvider`를 callback 내부에서 생성하여 주입

주입 repository:
- `instruments`
- `position_snapshots`
- `cash_balance_snapshots`
- `risk_limit_snapshots`

효과:
- fill 확정 직후 refresh가
  `positions + cash balance + risk limit snapshot`까지 한 경로로 수렴한다.

### 2. 동일 계좌 refresh dedupe 추가

파일:
- `scripts/run_post_submit_sync_loop.py`

변경:
- callback closure 내부에 `refresh_tasks: dict[UUID, asyncio.Task[None]]` 추가
- 같은 계좌에 대한 두 번째 refresh 요청은
  새 sync를 실행하지 않고 기존 task를 await 하도록 변경

효과:
- 같은 sync cycle 안에서 동일 계좌 refresh가 1회로 묶인다.
- 연속 fill / multi-order fill 상황에서 inquiry budget 낭비를 줄인다.

### 3. adapter REST client 속성명 호환 보강

파일:
- `scripts/run_post_submit_sync_loop.py`

변경:
- callback이 adapter에서 REST client를 찾을 때
  `_rest_client` → 없으면 `_rest` 순으로 확인

배경:
- `KoreaInvestmentAdapter` 실제 속성은 `_rest`
- 이전 구현은 `_rest_client`만 찾다가 runtime에서 refresh를 skip했다.

### 4. after-hours cycle에서도 full refresh 강제

파일:
- `scripts/run_post_submit_sync_loop.py`

변경:
- callback에서 `sync_account_snapshots(..., after_hours=False, fetch_positions=True)`
  로 호출

의도:
- after-hours recovery cycle라도 fill 확정 직후에는
  cash-only 최적화보다 `positions` 수렴이 더 중요하다.
- 따라서 snapshot refresh는 항상 full refresh를 수행하도록 강제했다.

## 테스트

파일:
- `tests/scripts/test_run_post_submit_sync_loop.py`

추가/보강:
1. refresh callback이 broker-agnostic sync를 호출하는지 검증
2. 동일 계좌 2회 호출 시 dedupe되어 1회만 sync 되는지 검증
3. adapter에 REST client 속성이 없으면 warning 후 skip 되는지 검증

## 검증 결과

### 테스트

```bash
pytest -q tests/scripts/test_run_post_submit_sync_loop.py tests/services/test_snapshot_sync.py \
  -k 'refresh_callback or parse_args_after_hours or risk_limit_snapshot'
```

결과:
- `8 passed`

### 정적 검증

```bash
python3 -m py_compile scripts/run_post_submit_sync_loop.py tests/scripts/test_run_post_submit_sync_loop.py
```

결과:
- 통과

### 컨테이너 내부 1회 실행

```bash
docker compose exec -T app python3 scripts/run_post_submit_sync_loop.py --once --after-hours
```

결과:
- script 정상 종료
- 현재 시점 active order가 없어 `orders=0`
- callback 자체는 실주행되지 않았지만, runtime import/초기화 문제 없이 루프 정상 종료 확인

## 한계

1. 실제 refresh callback 실주행은 active filled order가 있는 cycle에서 다시 확인 필요
   - 현재 실행 시점에는 active order가 없어서 dedupe/info 로그까지는 직접 보지 못했다.
2. `sync_account_snapshots()`의 `fetch_positions` 인자는 존재하지만,
   provider protocol 전달은 아직 전면 정리되지 않았다.
   - 이번 작업에서는 callback에서 `after_hours=False, fetch_positions=True`를 강제해
     full refresh 경로를 확보했다.

## 다음 작업

1. 장중/장후 실제 fill 발생 시 refresh callback 실주행 로그 검증
2. `sync_account_snapshots()`의 provider-level `fetch_positions` 전달 경로 정리
3. fill-triggered refresh 후 orderable amount / risk_limit snapshot 수렴 시간 측정
