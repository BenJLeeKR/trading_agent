"""Bearer token authentication + minimum RBAC for inspection API.

Design
------
Uses module-level globals configured once at startup by ``configure_security()``.
The ``get_current_principal`` dependency extracts and validates the Bearer token.
The ``require_viewer`` dependency enforces the minimum role.

Two access tiers
----------------
* ``auth_enabled=True`` (default) — token validation active; missing / invalid
  token → 401.
* ``auth_enabled=False`` — no auth dependencies are applied at the router level,
  so ``get_current_principal`` / ``require_viewer`` are never invoked.

See :doc:`/plans/46_auth_rbac_inspection_api` for the full design.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(slots=True, frozen=True)
class Principal:
    """Authenticated principal with role.

    Attributes
    ----------
    token:
        The validated Bearer token value.
    role:
        The role assigned to this principal (``"viewer"`` or ``"admin"``).
    """

    token: str
    role: str


_INSPECTION_TOKEN: str | None = None
_INSPECTION_ROLE: str = "viewer"


def configure_security(*, token: str | None, role: str = "viewer") -> None:
    """Configure the global security settings (called once at startup).

    Parameters
    ----------
    token:
        The expected Bearer token value.  ``None`` means the security module
        will deny all requests (defense in depth — this code path should never
        be reached when ``auth_enabled=False``).
    role:
        The role to assign to all authenticated principals.
    """
    global _INSPECTION_TOKEN, _INSPECTION_ROLE
    _INSPECTION_TOKEN = token
    _INSPECTION_ROLE = role


async def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> Principal:
    """Extract and validate the Bearer token from the request.

    Returns
    -------
    Principal
        On success — the authenticated principal.

    Raises
    ------
    HTTPException (401)
        When the token is missing, the scheme is not ``Bearer``, the token
        does not match the configured value, or security is not configured
        (``_INSPECTION_TOKEN is None``).
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization scheme — use Bearer",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if _INSPECTION_TOKEN is None:
        # Security module not configured — deny all (defense in depth).
        # This should never be reached when auth_enabled=False because the
        # require_viewer dependency is not applied to routers in that case.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication not configured",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if credentials.credentials != _INSPECTION_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return Principal(token=credentials.credentials, role=_INSPECTION_ROLE)


async def require_viewer(
    principal: Principal = Depends(get_current_principal),
) -> Principal:
    """Require at least ``viewer`` role.

    Parameters
    ----------
    principal:
        The authenticated principal (injected by ``get_current_principal``).

    Returns
    -------
    Principal
        The same principal on success.

    Raises
    ------
    HTTPException (403)
        When the principal's role is neither ``"viewer"`` nor ``"admin"``.
    """
    if principal.role not in ("viewer", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions — viewer role required",
        )
    return principal


async def require_admin(
    principal: Principal = Depends(get_current_principal),
) -> Principal:
    """Require ``admin`` role.

    Parameters
    ----------
    principal:
        The authenticated principal (injected by ``get_current_principal``).

    Returns
    -------
    Principal
        The same principal on success.

    Raises
    ------
    HTTPException (403)
        When the principal's role is not ``"admin"``.
    """
    if principal.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions — admin role required",
        )
    return principal
