# KIS REST approval key 파일 cache 확장

## 배경
- `[PRIORITY_MAP] remaining_work_priority_map.md`의 `6. KIS token/approval cache 공통 모듈화` 항목 중
  마지막 남은 작업은 `approval key를 REST client 쪽에서도 파일 cache까지 확장할지 검토`였다.
- 기존에는 `KISRestClient.get_approval_key()`가 메모리 cache만 사용했다.
- 그래서 프로세스 재시작 후에는 동일한 trading credential이라도 항상 `/oauth2/Approval` HTTP 호출이 다시 발생했다.

## 판단
- **확장하는 것이 맞다**고 결정했다.
- 단, 아래 두 조건을 함께 적용했다.
  1. 기본값은 `disabled`
  2. live-info websocket approval cache와 **별도 파일 / 별도 cache purpose** 사용

이렇게 하면 운영자가 원할 때만 켤 수 있고,
기존 `KisMarketStateClient`의 approval key cache와 충돌하지 않는다.

## 적용 내용

### 1. 공통 builder 추가
- 파일: `src/agent_trading/brokers/koreainvestment/token_cache.py`
- 추가:
  - `CachePurpose.TRADING_APPROVAL_KEY`
  - `build_rest_approval_key_cache_config(...)`

validator 구조:
- `cache_type=approval_key`
- `kis_env`
- `base_url`

### 2. `KISRestClient` approval file cache 추가
- 파일: `src/agent_trading/brokers/koreainvestment/rest_client.py`
- 추가 필드:
  - `approval_cache_enabled`
  - `approval_cache_path`
  - `_approval_cache`
- `get_approval_key()` 흐름:
  1. in-memory hit 확인
  2. file cache load 확인
  3. miss면 `/oauth2/Approval` HTTP 호출
  4. 성공 시 file cache 저장

### 3. 설정 추가
- 파일: `src/agent_trading/config/settings.py`
- 추가 설정:
  - `KIS_APPROVAL_KEY_CACHE_ENABLED`
  - `KIS_APPROVAL_KEY_CACHE_PATH`
- 기본값:
  - `false`
  - `.cache/kis_rest_approval_key.json`

### 4. 운영 경로 주입
- `runtime/bootstrap.py`
- `scripts/run_fill_sync_loop.py`
- `scripts/run_post_submit_sync_loop.py`
- `scripts/run_decision_loop.py`
- `scripts/sync_kis_snapshots.py`
- `scripts/verify_order_truth.py`
- `src/agent_trading/brokers/snapshot_factory.py`
- `src/agent_trading/services/reconciliation_worker.py`

위 경로에서 `AppSettings` 기반으로 `approval_cache_enabled/path`를 함께 넘기도록 맞췄다.

### 5. 환경 템플릿 반영
- 파일: `.env.example`
- 추가:
  - `KIS_APPROVAL_KEY_CACHE_ENABLED=false`
  - `KIS_APPROVAL_KEY_CACHE_PATH=.cache/kis_rest_approval_key.json`

## 검증
- `tests/brokers/test_kis_auth_strict_cap.py`
  - file cache hit 시 HTTP 호출 없이 반환
  - HTTP 성공 후 file cache 저장
- `tests/brokers/koreainvestment/test_token_cache.py`
  - `build_rest_approval_key_cache_config()` shape 검증

## 기대 효과
- trading REST client가 재기동돼도 approval key 재사용이 가능하다.
- `/oauth2/Approval` 호출 빈도를 줄여 auth/approval 쿨다운 부담을 완화한다.
- live-info websocket approval cache와 충돌하지 않는다.
