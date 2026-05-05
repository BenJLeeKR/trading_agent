# Plan 53 — Admin UI Static Mount 경로 수정

## 1. 문제

`npm run build` 후 `/admin`이 404를 반환한다.

**원인:** [`src/agent_trading/api/app.py`](../src/agent_trading/api/app.py:207)의 `_admin_ui_dist` 경로 계산에서 상위 디렉토리 이동 횟수가 1회 과다하다.

### 현재 계산 (틀림)

```python
_admin_ui_dist = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "admin_ui", "dist")
)
```

- `__file__` = `/workspace/agent_trading/src/agent_trading/api/app.py`
- `os.path.dirname(__file__)` = `/workspace/agent_trading/src/agent_trading/api`
- `..` x 4 = `/workspace` ← 너무 많이 올라감
- 결과: `/workspace/admin_ui/dist` ← **존재하지 않는 경로**

### 올바른 계산 (수정 후)

```python
_admin_ui_dist = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "admin_ui", "dist")
)
```

- `..` x 3 = `/workspace/agent_trading`
- 결과: `/workspace/agent_trading/admin_ui/dist` ← **올바른 경로**

## 2. 수정 범위

### 2.1 [`src/agent_trading/api/app.py`](../src/agent_trading/api/app.py:208)

| 현재 | 수정 |
|------|------|
| `"..", "..", "..", ".."` (4번) | `"..", "..", ".."` (3번) |

### 2.2 [`tests/api/test_health.py`](../tests/api/test_health.py)

`/admin` mount 존재 여부를 검증하는 smoke test 1개 추가:

```python
def test_admin_ui_static_mount(empty_client: TestClient) -> None:
    """``GET /admin`` returns 200 when admin_ui/dist exists."""
    response = empty_client.get("/admin")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
```

`admin_ui/dist`는 이미 빌드되어 존재하므로 (`index.html` + `assets/`), `empty_client` fixture로 생성한 app에서 `/admin` mount가 정상 동작한다.

**단, `admin_ui/dist`가 없을 경우 mount 자체가 생략되므로 테스트가 skip되어야 한다.** 이를 위해 `os.path.isdir` 체크를 추가하거나, fixture 레벨에서 분기한다. 가장 간단한 방법은 `admin_ui/dist/index.html` 존재 여부를 확인 후 pytest.skip() 하는 것이다.

### 2.3 변경 파일 요약

| 파일 | 변경 유형 | 설명 |
|------|----------|------|
| `src/agent_trading/api/app.py` | 수정 | `..` 횟수 4→3 |
| `tests/api/test_health.py` | 수정 | `/admin` mount smoke test 추가 |

## 3. 검증

1. `cd admin_ui && npm run build` (이미 빌드되어 있다면 skip)
2. `cd .. && pip install -e ".[dev,test]"` (필요시)
3. `pytest tests/api/test_health.py -v` — admin mount test 포함 통과 확인
4. `uvicorn agent_trading.api.app:create_app --factory --reload` (또는 `make run-api`)로 API 실행
5. 브라우저에서 `http://localhost:{PORT}/admin` 접속 → Admin UI 정상 로드
