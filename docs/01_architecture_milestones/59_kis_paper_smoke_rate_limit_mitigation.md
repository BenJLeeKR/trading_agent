# EGW00133 Rate-Limit 대응: Smoke Fixture 레벨 완화

## 문제

`test_kis_paper_smoke.py` suite가 직전 token 발급(디버그/개별 실행) 후 60초 내에 실행되면,
KIS Paper sandbox의 **1-token-per-minute** 제한(EGW00133)으로 인해 suite 전체가 전부 실패한다.
이전에는 `msg_cd=` (빈값)으로 원인 파악이 불가능했지만, 이전 턴에서 `_raise_on_error()` 수정으로
이제 `msg_cd=EGW00133`과 함께 설명이 표시된다.

## 변경 정책

- **장시간 sleep/scheduler는 구현하지 않는다**
- **`pytest.skip()` with explicit reason** 을 기본 정책으로 채택
- 기능 실패(credential/code defect)와 sandbox 제약(rate limit)을 구분해서 표시

## 변경 파일

### 1. `tests/smoke/test_kis_paper_smoke.py`

#### 1a. `kis_rest_client` fixture — eager auth + skip on rate limit

```python
@pytest.fixture(scope="module")
async def kis_rest_client() -> AsyncIterator[KISRestClient]:
    ...
    client = KISRestClient(...)

    # Eager authenticate — catch EGW00133 early and skip the module
    # instead of letting every test fail with opaque 403.
    try:
        await client.authenticate()
    except BrokerError as e:
        msg = str(e)
        if "EGW00133" in msg:
            pytest.skip(
                "KIS Paper token rate limit hit (EGW00133: 1 token/min). "
                "Wait ~60 seconds before rerunning the smoke suite."
            )
        pytest.fail(
            f"KIS authentication failed (not a rate-limit issue): {msg}"
        )

    yield client
    ...
```

**변경 사항**:
- `BrokerError` import 추가
- fixture yield 전에 `authenticate()` 호출 (eager)
- EGW00133 → `pytest.skip()` (모듈 전체 skip)
- 기타 BrokerError → `pytest.fail()` (credential/code defect)
- 성공 → 기존대로 yield

**효과**:
- Rate-limit 시: 7개 FAIL + 1 ERROR → **1개 SKIP (모듈 전체)**
- Credential 문제 시: opaque 403 → **1개 FAIL with diagnostic message**
- 정상 실행 시: 변화 없음

#### 1b. `test_authentication` — token 검증 유지

`test_authentication` 테스트는 eager auth로 이미 token이 발급된 상태에서
`authenticate()`를 호출하지만, 캐시된 token을 반환하므로 네트워크 호출 없이
검증만 수행한다. 변경 불필요.

#### 1c. Docstring 업데이트

`kis_rest_client` fixture docstring에 EGW00133 skip 동작 설명 추가.

### 2. `tests/smoke/test_kis_paper_ai_runtime_smoke.py` — docstring만 보강

`TestGuardedPaperSubmit.test_guarded_paper_submit_with_read_only_guard`는:
- 이미 `@pytest.mark.skipif(not _paper_submit_enabled(), ...)` 로 기본 skip
- Opt-in 시에도 `_raise_on_error()`에서 EGW00133을 명확히 표시 (이전 턴 수정 완료)
- 추가 fixture 변경 불필요

단, EGW00133 가능성과 대응 방법을 docstring에 간단히 추가.

## 변경 금지 확인

- ❌ live/real 경로 사용
- ❌ broker submit semantics 변경
- ❌ KIS credential 처리 로직 변경
- ❌ admin UI 변경
- ❌ 과도한 retry scheduler 구현
- ✅ 오직 fixture 레벨 skip/fail 메시지 개선만 수행

## 검증

1. `python3 -m pytest tests/smoke/test_kis_paper_smoke.py -v --cache-clear`
   - Token quota 있을 때: 전부 PASS (7 passed, 1 error? WS는 slow mark)
   - Token quota 없을 때: 1 skipped (module-level skip, clear message)

2. `python3 -m pytest tests/brokers/test_rate_limit.py tests/brokers/test_kis_adapter_validation.py -v` — 기존 테스트 unaffected

## 실행 가이드

- Smoke suite 실행 전, 직전 token 발급 후 **최소 60초 이상 대기**
- `EGW00133` skip 메시지가 보이면 → 60초 후 재실행
- `authentication failed (not a rate-limit issue)` 가 보이면 → credential 문제
