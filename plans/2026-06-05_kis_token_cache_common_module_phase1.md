# KIS token/approval cache 공통 모듈화 1차

## 배경

`[PRIORITY_MAP] remaining_work_priority_map.md`의 `6. KIS token/approval cache 공통 모듈화`는
구현체 자체보다 **각 클라이언트가 제각각 cache config/fingerprint/expiry 규칙을 만드는 문제**가
핵심 기술부채였다.

현재 구조는 이미 `KisTokenCache`라는 공통 구현체를 갖고 있었지만,

- `KISRestClient`
- `KISHolidayClient`
- `KisMarketStateClient`

가 각각 `KisTokenCacheConfig(...)`를 직접 조립하고 있었다.

그 결과 다음 위험이 있었다.

1. cache purpose는 같아도 extra validator shape가 달라질 수 있음
2. load/save expiry buffer가 조금씩 달라질 수 있음
3. fingerprint 입력 규칙이 클라이언트별로 다시 분기될 수 있음
4. 신규 live/disclosure 경로 추가 시 중복 설정이 다시 생김

## 이번 작업

### 1. 공통 cache config builder 추가

파일:
- [`src/agent_trading/brokers/koreainvestment/token_cache.py`](../src/agent_trading/brokers/koreainvestment/token_cache.py)

추가한 builder:

- `build_rest_access_token_cache_config(...)`
- `build_holiday_oauth_cache_config(...)`
- `build_live_approval_key_cache_config(...)`

정리한 공통 규칙:

- 표준 `load_expiry_buffer = 60s`
- 표준 access token / approval key `save_expiry_buffer = 300s`
- holiday OAuth `save_expiry_buffer = 60s`
- purpose별 extra validator shape 표준화

### 2. 클라이언트 적용

적용 파일:

- [`rest_client.py`](../src/agent_trading/brokers/koreainvestment/rest_client.py)
- [`holiday_client.py`](../src/agent_trading/brokers/koreainvestment/holiday_client.py)
- [`market_state_client.py`](../src/agent_trading/brokers/koreainvestment/market_state_client.py)

적용 내용:

- `KISRestClient`
  - paper/dev trading token cache
  - live disclosure access token cache
  - 모두 `build_rest_access_token_cache_config()` 사용
- `KISHolidayClient`
  - live holiday OAuth cache
  - `build_holiday_oauth_cache_config()` 사용
- `KisMarketStateClient`
  - live approval key cache
  - `build_live_approval_key_cache_config()` 사용

### 3. validator 강화

이번 정리로 다음 validator가 명시적으로 캐시 파일에 남는다.

- REST access token:
  - `kis_env`
  - `base_url`
- Holiday OAuth:
  - `token_purpose=holiday_oauth`
  - `base_url`
- Live approval key:
  - `cache_type=approval_key`
  - `base_ws_url`

즉 잘못된 endpoint/목적의 캐시가 재사용될 가능성을 더 줄였다.

## 검증

실행:

```bash
pytest -q tests/brokers/koreainvestment/test_token_cache.py \
  tests/brokers/koreainvestment/test_holiday_client.py \
  tests/brokers/koreainvestment/test_market_state_client.py \
  -k 'cache or approval_key or token_cache'

python3 -m py_compile \
  src/agent_trading/brokers/koreainvestment/token_cache.py \
  src/agent_trading/brokers/koreainvestment/rest_client.py \
  src/agent_trading/brokers/koreainvestment/holiday_client.py \
  src/agent_trading/brokers/koreainvestment/market_state_client.py \
  tests/brokers/koreainvestment/test_token_cache.py \
  tests/brokers/koreainvestment/test_holiday_client.py
```

결과:

- `41 passed`
- `py_compile` 통과

추가 테스트:

- builder별 config shape 검증
- holiday cache hit 회귀 테스트
- approval key cache 기존 동작 회귀 테스트

## 이번 단계에서 닫힌 범위

- [x] 공통 cache contract 1차 정리
- [x] cache purpose 표준화 1차 정리
- [x] expiry/fingerprint/validator helper 추출
- [x] rest / holiday / market_state client 적용

## 아직 남은 범위

- [ ] approval key를 REST client 쪽에서도 파일 cache까지 쓸지 검토
- [ ] live-info / disclosure 설정명을 더 일관되게 정리할지 검토
- [ ] token cache 상태를 운영 health에 더 직접 노출할지 검토
