"""``POST /config-versions/risk/max-single-position-pct`` API 테스트.

이 endpoint는 Inspection API의 유일한 "쓰기" 경로 중 하나다(``orders.py``의
``PUT /orders/{id}/status``와 동일한 ``require_admin`` 게이팅 패턴).
실제 검증 로직/immutable-append 계약은
``tests/services/test_config_version_admin.py``에서 이미 다뤘으므로,
여기서는 API 계층(인증/권한/HTTP 상태/응답 shape)만 확인한다.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from agent_trading.api.app import create_app
from agent_trading.domain.entities import ConfigVersionEntity
from agent_trading.domain.enums import Environment
from agent_trading.repositories.bootstrap import build_in_memory_repositories

_REQUEST_PATH = "/config-versions/risk/max-single-position-pct"
_ADMIN_HEADERS = {"Authorization": "Bearer test-token"}


class TestUpdateMaxSinglePositionPct:
    def _build(self, *, auth_enabled: bool = True, auth_role: str = "admin"):
        """기본값은 ``auth_enabled=True, auth_role="admin"``이다.

        이 라우트는 ``orders.py``의 ``PUT /orders/{id}/status``와 동일하게
        ``Depends(require_admin)``을 **라우트 함수 시그니처에 직접** 선언한다.
        이 의존성은 항상 ``get_current_principal()``을 호출하는데, 그 함수는
        전역 ``_INSPECTION_TOKEN``만 보고 판단한다 — ``create_app()``은
        ``auth_enabled=False``일 때 ``configure_security()``를 아예 호출하지
        않으므로 ``_INSPECTION_TOKEN``이 계속 ``None``으로 남는다. 그 결과
        ``auth_enabled=False``로 만든 앱에서는 이 endpoint가 **항상 401**을
        반환한다(``require_viewer``만 쓰는 다른 read-only 라우트들과 달리,
        이 라우트는 router 레벨이 아니라 함수 레벨에 인증을 박아뒀기 때문 —
        기존 ``orders.py``의 동일 패턴에도 이미 있는 특성이며 이번 PR에서
        새로 만든 것이 아니다). 그래서 비즈니스 로직 테스트도 실제 사용
        방식과 동일하게 admin 토큰을 발급해 호출한다.
        """
        repos = build_in_memory_repositories()
        app = create_app(
            repos=repos,
            auth_enabled=auth_enabled,
            auth_token="test-token" if auth_enabled else None,
            auth_role=auth_role,
        )
        return repos, app

    def _seed_active_config_version(self, repos, *, client_id, environment=Environment.PAPER):
        version = ConfigVersionEntity(
            config_version_id=uuid4(),
            client_id=client_id,
            environment=environment,
            version_tag="v1.0",
            config_json={
                "risk": {"max_single_position_pct": "10", "min_cash_buffer_pct": "5"},
                "execution": {"max_order_value": "50000000"},
            },
            checksum="seed-checksum",
            activated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            activated_by="seed-script",
        )
        asyncio.run(repos.config_versions.add(version))
        return version

    def test_publishes_new_version_and_returns_before_after(self) -> None:
        repos, app = self._build()
        client_id = uuid4()
        self._seed_active_config_version(repos, client_id=client_id)

        with TestClient(app) as client:
            response = client.post(
                _REQUEST_PATH,
                json={
                    "client_id": str(client_id),
                    "environment": "paper",
                    "max_single_position_pct": "15",
                    "reason": "increase concentration cap",
                },
                headers=_ADMIN_HEADERS,
            )
        assert response.status_code == 200
        data = response.json()
        assert data["previous_max_single_position_pct"] == "10"
        assert data["new_max_single_position_pct"] == "15"
        assert data["client_id"] == str(client_id)
        assert data["environment"] == "paper"
        assert data["config_version_id"] != data["previous_config_version_id"]
        assert data["activated_by"] == "admin_api:admin"

        # get_active()가 새 버전을 가리키는지 API를 다시 호출해 확인하는
        # 대신(별도 GET endpoint가 없음), repos를 직접 조회해 반영을 확인한다.
        active = asyncio.run(repos.config_versions.get_active(client_id, Environment.PAPER))
        assert active is not None
        assert str(active.config_version_id) == data["config_version_id"]

    def test_invalid_value_returns_400(self) -> None:
        repos, app = self._build()
        client_id = uuid4()
        self._seed_active_config_version(repos, client_id=client_id)

        with TestClient(app) as client:
            response = client.post(
                _REQUEST_PATH,
                json={
                    "client_id": str(client_id),
                    "environment": "paper",
                    "max_single_position_pct": "0",
                },
                headers=_ADMIN_HEADERS,
            )
        assert response.status_code == 400

    def test_duplicate_value_returns_400(self) -> None:
        repos, app = self._build()
        client_id = uuid4()
        self._seed_active_config_version(repos, client_id=client_id)

        with TestClient(app) as client:
            response = client.post(
                _REQUEST_PATH,
                json={
                    "client_id": str(client_id),
                    "environment": "paper",
                    "max_single_position_pct": "10",
                },
                headers=_ADMIN_HEADERS,
            )
        assert response.status_code == 400

    def test_no_active_version_returns_400(self) -> None:
        repos, app = self._build()
        with TestClient(app) as client:
            response = client.post(
                _REQUEST_PATH,
                json={
                    "client_id": str(uuid4()),
                    "environment": "paper",
                    "max_single_position_pct": "10",
                },
                headers=_ADMIN_HEADERS,
            )
        assert response.status_code == 400

    def test_invalid_client_id_returns_400(self) -> None:
        repos, app = self._build()
        with TestClient(app) as client:
            response = client.post(
                _REQUEST_PATH,
                json={
                    "client_id": "not-a-uuid",
                    "environment": "paper",
                    "max_single_position_pct": "10",
                },
                headers=_ADMIN_HEADERS,
            )
        assert response.status_code == 400

    def test_invalid_environment_returns_400(self) -> None:
        repos, app = self._build()
        client_id = uuid4()
        self._seed_active_config_version(repos, client_id=client_id)
        with TestClient(app) as client:
            response = client.post(
                _REQUEST_PATH,
                json={
                    "client_id": str(client_id),
                    "environment": "not-a-real-environment",
                    "max_single_position_pct": "10",
                },
                headers=_ADMIN_HEADERS,
            )
        assert response.status_code == 400

    def test_real_environment_is_rejected_with_400_not_500(self) -> None:
        """``environment="real"``은 유효한 ``Environment`` enum 값이라

        ``Environment("real")`` 파싱 자체는 성공한다 — 그래서
        ``test_invalid_environment_returns_400``(완전히 잘못된 문자열)과는
        다른 경로를 탄다. ``trading.config_versions.environment``의 실제 DB
        CHECK 제약이 ``'real'``을 받지 않으므로(운영 Postgres에서 확인),
        이 값은 애플리케이션 레벨에서 명확한 400으로 막혀야 한다 — DB
        INSERT까지 가서 처리되지 않은 예외(500)로 새어나가면 안 된다.
        """
        repos, app = self._build()
        client_id = uuid4()
        self._seed_active_config_version(repos, client_id=client_id)
        with TestClient(app) as client:
            response = client.post(
                _REQUEST_PATH,
                json={
                    "client_id": str(client_id),
                    "environment": "real",
                    "max_single_position_pct": "15",
                },
                headers=_ADMIN_HEADERS,
            )
        assert response.status_code == 400
        assert response.status_code != 500
        body = response.json()
        assert "real" in json.dumps(body).lower()

        # "real"로는 어떤 config_version도 새로 생기지 않았어야 한다.
        active = asyncio.run(repos.config_versions.get_active(client_id, Environment.PAPER))
        assert active is not None
        assert active.config_json["risk"]["max_single_position_pct"] == "10"

    def test_viewer_role_is_forbidden(self) -> None:
        """auth_enabled + viewer role → 403 (require_admin gate)."""
        repos, app = self._build(auth_enabled=True, auth_role="viewer")
        client_id = uuid4()
        self._seed_active_config_version(repos, client_id=client_id)

        with TestClient(app) as client:
            response = client.post(
                _REQUEST_PATH,
                json={
                    "client_id": str(client_id),
                    "environment": "paper",
                    "max_single_position_pct": "15",
                },
                headers={"Authorization": "Bearer test-token"},
            )
        assert response.status_code == 403

    def test_admin_role_succeeds(self) -> None:
        """auth_enabled + admin role → 200 (require_admin gate passes)."""
        repos, app = self._build()
        client_id = uuid4()
        self._seed_active_config_version(repos, client_id=client_id)

        with TestClient(app) as client:
            response = client.post(
                _REQUEST_PATH,
                json={
                    "client_id": str(client_id),
                    "environment": "paper",
                    "max_single_position_pct": "15",
                },
                headers=_ADMIN_HEADERS,
            )
        assert response.status_code == 200

    def test_missing_token_returns_401(self) -> None:
        repos, app = self._build()
        client_id = uuid4()
        self._seed_active_config_version(repos, client_id=client_id)

        with TestClient(app) as client:
            response = client.post(
                _REQUEST_PATH,
                json={
                    "client_id": str(client_id),
                    "environment": "paper",
                    "max_single_position_pct": "15",
                },
            )
        assert response.status_code == 401
