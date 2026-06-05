# 2026-06-03 snapshot sync `fetch_positions` 전달 경로 정리

## 목적

- `plans/[PRIORITY_MAP] remaining_work_priority_map.md` 기준
  `fill 발생 후 position/cash refresh 자동화` 후속 작업으로,
  `sync_account_snapshots()`의 `fetch_positions` 의도가 provider까지
  실제로 전달되도록 정리한다.
- cash-only sync / full refresh 의도가 runner 중간에서 손실되지 않도록
  broker-agnostic snapshot sync 경로를 일관화한다.

## 문제

`src/agent_trading/services/snapshot_sync.py`의
`sync_account_snapshots(..., fetch_positions=...)`는
외부에서 `fetch_positions=False`를 받더라도,
실제 provider 호출 시에는 해당 값을 넘기지 않고 있었다.

즉, 기존 코드는 다음과 같은 상태였다.

```python
fetched = await fetch_provider.fetch_snapshot(
    account_id,
    instrument_repo,
    after_hours=after_hours,
)
```

문제점:

1. runner API는 `fetch_positions`를 받는데 provider는 그 정보를 모름
2. cash-only refresh 의도와 full refresh 의도가 중간에서 흐려짐
3. `KISSyncSnapshotProvider.fetch_snapshot(..., fetch_positions=False)`는
   이미 지원하고 있었지만 broker-agnostic runner가 그 기능을 실제로
   사용하지 못하고 있었음

## 변경 내용

### 1. `SnapshotFetchProvider` 프로토콜 확장

파일:
- `src/agent_trading/services/snapshot_sync.py`

변경:
- `fetch_snapshot()` protocol 시그니처에
  `fetch_positions: bool = True` 추가

의미:
- provider 구현체는 cash-only / full refresh 의도를 명시적으로 받을 수 있다.

### 2. runner에서 provider로 `fetch_positions` 전달

파일:
- `src/agent_trading/services/snapshot_sync.py`

변경:
- `sync_account_snapshots()` 내부 provider 호출을 아래처럼 수정

```python
fetched = await fetch_provider.fetch_snapshot(
    account_id,
    instrument_repo,
    after_hours=after_hours,
    fetch_positions=fetch_positions,
)
```

효과:
- `sync_account_snapshots(fetch_positions=False)`가 실제 provider 동작까지
  일관되게 반영된다.

### 3. 테스트 mock/provider 정리

파일:
- `tests/services/test_snapshot_sync.py`

변경:
- `MockSnapshotProvider.fetch_snapshot()`도
  `fetch_positions` 인자를 받도록 수정
- 마지막 호출값을 기록하는
  `last_after_hours`, `last_fetch_positions` 필드 추가

### 4. 회귀 테스트 추가

파일:
- `tests/services/test_snapshot_sync.py`

신규 검증:
- `sync_account_snapshots(..., fetch_positions=False)` 호출 시
  provider가 실제로 `fetch_positions=False`를 받는지 확인
- 이 경우 positions는 sync되지 않고,
  cash snapshot은 정상 저장되는지 확인

### 5. protocol 예제 provider 정리

파일:
- `tests/services/test_snapshot_sync.py`

변경:
- `CustomProvider` 예제도
  `after_hours`, `fetch_positions` kw-only 인자를 받도록 맞춤

## 검증

### 1. snapshot sync 테스트

```bash
pytest -q tests/services/test_snapshot_sync.py \
  -k 'fetch_positions or protocol or risk_limit_snapshot or sync_empty_positions'
```

결과:
- `8 passed`

### 2. refresh callback 연계 확인

```bash
pytest -q tests/services/test_snapshot_sync.py tests/scripts/test_run_post_submit_sync_loop.py \
  -k 'fetch_positions or refresh_callback or protocol'
```

결과:
- `5 passed`

### 3. 정적 검증

```bash
python3 -m py_compile src/agent_trading/services/snapshot_sync.py scripts/run_post_submit_sync_loop.py
```

결과:
- 통과

참고:
- `tests/services/test_snapshot_sync.py`까지 포함한 `py_compile`은
  기존 `tests/services/__pycache__` 권한 문제 때문에 별도 실패할 수 있으나,
  source 파일 자체는 정상 컴파일된다.

## 결과

이제 snapshot sync 계층은 다음처럼 일관된다.

1. caller가 `fetch_positions=False` 또는 `True`를 결정
2. `sync_account_snapshots()`가 그 값을 그대로 provider에 전달
3. provider가 cash-only / full refresh 전략을 실제로 적용

즉, 이후 fill-triggered refresh, startup snapshot sync, after-hours cash-only sync에서
`fetch_positions` 의도가 runner 중간에서 소실되지 않는다.

## 다음 작업

1. 장중 실제 fill 발생 시 refresh callback이 full refresh를 수행하는 로그 검증
2. `fill-triggered refresh` 후 orderable amount / risk-limit 수렴 속도 측정
3. `fill history Phase 3` 다음 항목인 `fill 기반 상태 수렴` 추가 강화
