"""``GET /auth/me`` — 현재 Bearer 토큰의 role 조회.

이 시스템은 사용자별 계정 관리가 아니라, 프로세스 시작 시 설정된 토큰 1개와
고정 role 1개로 동작한다(``security.configure_security()``). 이 엔드포인트는
"누가 로그인했는지"를 알려주는 것이 아니라 "지금 이 요청에 쓰인 토큰이 어떤
권한(viewer/admin)을 갖는지"만 알려준다 — Admin UI가 발행/조치 버튼을
노출하기 전에 403을 기능 오류로 오해하지 않도록 하기 위한 최소 정보다.

``require_viewer``를 최소 권한으로 둔다 — viewer/admin 모두 자기 role을
확인할 수 있어야 한다(더 낮은 권한을 요구할 이유가 없다).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from agent_trading.api.schemas import AuthMeResponse
from agent_trading.api.security import Principal, require_viewer

router = APIRouter(tags=["auth"])


@router.get("/auth/me", response_model=AuthMeResponse)
async def get_auth_me(
    request: Request,
    principal: Principal = Depends(require_viewer),
) -> AuthMeResponse:
    """현재 토큰의 role과, 이 배포가 인증을 강제하는지 여부를 반환한다.

    ``auth_enabled=False``로 뜬 배포(개발/테스트 전용)에서는 이 라우트도
    다른 보호된 라우트와 동일하게 인증이 강제되지 않는 것이 원칙이지만,
    이 엔드포인트는 응답 자체가 "이 토큰의 role"이라 principal 없이는
    의미 있는 값을 만들 수 없다. 그래서 ``require_viewer``를 라우트에
    직접 선언해 — router 레벨 dependency 여부와 무관하게 — 항상 유효한
    토큰을 요구한다(``config_versions.py``의 admin-only write route와
    동일한 관례: router 레벨 최소 권한 + route별 명시적 Depends).
    토큰이 설정되지 않은 상태(``auth_enabled=False``이고 별도 토큰도
    주입되지 않은 기본 개발 모드)에서는 ``get_current_principal``이 이미
    하던 대로 401(``Authentication not configured``)을 반환한다 — 이
    라우트가 새로 만들어내는 보안 의미는 없다.
    """
    auth_enabled = bool(getattr(request.app.state, "auth_enabled", True))
    return AuthMeResponse(role=principal.role, auth_enabled=auth_enabled)
