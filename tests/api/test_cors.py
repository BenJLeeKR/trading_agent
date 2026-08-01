"""CORS 미들웨어 테스트 — 프론트/백엔드 분리(별도 origin) 대비.

프론트(Admin UI)가 nginx 뒤에서 이 API와 같은 origin으로 묶여 서비스되던
예전 구조에서는 CORS가 필요 없었지만, 프론트를 별도 컨테이너/포트로 분리하면
브라우저가 이 API를 cross-origin으로 직접 호출하므로 CORS 헤더가 없으면
브라우저가 응답을 막는다.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from agent_trading.api.app import create_app


def test_default_allows_localhost_3000() -> None:
    """``cors_allowed_origins`` 미지정 시 로컬 개발 프론트(3000)가 기본 허용된다."""
    app = create_app(auth_enabled=False)
    client = TestClient(app)

    response = client.get(
        "/health",
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_unlisted_origin_is_not_allowed() -> None:
    """허용 목록에 없는 origin은 CORS 헤더가 붙지 않는다(브라우저가 차단)."""
    app = create_app(auth_enabled=False)
    client = TestClient(app)

    response = client.get(
        "/health",
        headers={"Origin": "http://evil.example.com"},
    )
    assert "access-control-allow-origin" not in response.headers


def test_custom_allowed_origins() -> None:
    """``cors_allowed_origins``로 운영 도메인을 명시적으로 지정할 수 있다."""
    app = create_app(
        auth_enabled=False,
        cors_allowed_origins=["http://trd.puwa.net", "http://trd.puwa.net:3000"],
    )
    client = TestClient(app)

    response = client.get(
        "/health",
        headers={"Origin": "http://trd.puwa.net:3000"},
    )
    assert response.headers.get("access-control-allow-origin") == "http://trd.puwa.net:3000"


def test_preflight_allows_authorization_header() -> None:
    """Bearer 토큰을 붙이는 실제 요청 전에 브라우저가 보내는 preflight(OPTIONS)가 통과한다."""
    app = create_app(
        auth_enabled=False,
        cors_allowed_origins=["http://trd.puwa.net:3000"],
    )
    client = TestClient(app)

    response = client.options(
        "/orders",
        headers={
            "Origin": "http://trd.puwa.net:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://trd.puwa.net:3000"
