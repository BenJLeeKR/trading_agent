# KIS Token Cache Health 운영 관측값 노출

## 배경
- `[PRIORITY_MAP] remaining_work_priority_map.md`의 `6. KIS token/approval cache 공통 모듈화` 항목 중
  `token cache health를 운영 관측값에 직접 노출할지 검토`가 미완료 상태였다.
- 현재 KIS 토큰/승인키 캐시는 공통 모듈(`KisTokenCache`)로 정리되어 있지만,
  운영자가 실제 cache file 상태를 한눈에 볼 수 있는 구조화된 관측값은 없었다.

## 목표
- 캐시 파일을 수정하지 않고 현재 상태를 판별할 수 있는 `inspect()` 경로를 추가한다.
- `ops-scheduler`가 `operations_day_runs.summary_json`에 KIS cache health를 함께 저장하도록 한다.

## 적용 내용

### 1. `KisTokenCache.inspect()` 추가
- 파일: `src/agent_trading/brokers/koreainvestment/token_cache.py`
- 추가 구조:
  - `CacheInspectionResult`
  - `KisTokenCache.inspect()`
- 특징:
  - non-mutating (파일 삭제/수정 없음)
  - 아래 상태를 구조화 반환
    - `disabled`
    - `file_missing`
    - `read_error`
    - `parse_error`
    - `fingerprint_mismatch`
    - `purpose_mismatch`
    - `validator_mismatch`
    - `expired`
    - `ready`

### 2. `operations_day_runs.summary_json.token_cache_health` 추가
- 파일: `scripts/run_ops_scheduler.py`
- 추가 helper:
  - `_build_token_cache_health_summary()`
- 저장 대상:
  - `paper_rest_access_token`
  - `holiday_oauth`
  - `live_approval_key`
  - `live_disclosure_access_token` (credential 존재 시)

### 3. 노출 형식
- `operations_day_runs.summary_json` 예시:

```json
{
  "token_cache_health": {
    "paper_rest_access_token": {
      "status": "ready",
      "enabled": true,
      "exists": true,
      "path": ".cache/kis_token.json"
    }
  }
}
```

## 검증
- `pytest -q tests/brokers/koreainvestment/test_token_cache.py tests/scripts/test_run_ops_scheduler.py -k 'TestInspect or PersistOperationsDayRun or HeartbeatTask or PersistSessionState'`
  - `12 passed`
- `python3 -m py_compile ...`
  - 통과

## 기대 효과
- 운영 중 token/approval cache 파일이
  - 없는지
  - 만료됐는지
  - fingerprint/validator mismatch인지
  - 정상 usable 상태인지
  를 DB 기반 운영 관측값에서 바로 확인할 수 있다.

## 남은 후속
- `[PRIORITY_MAP]` 6번 항목에서 남은 것은
  - `approval key를 REST client 쪽에서도 파일 cache까지 확장할지 검토`
  1개다.
