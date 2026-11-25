"""Account and invite endpoints for the public-cloud app only."""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.backend.cloud.auth import (
    AuthError,
    InviteRejected,
    InvalidCredentials,
    LoginRateLimited,
    PermissionDenied,
    RegistrationRejected,
)


router = APIRouter(prefix="/api/auth", tags=["cloud-auth"])
SESSION_COOKIE = "shansuan_session"
CSRF_COOKIE = "shansuan_csrf"


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class Registration(Credentials):
    password: str = Field(min_length=12, max_length=128)
    invite_token: str = Field(min_length=20, max_length=512)


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)


class PasswordResetComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=20, max_length=512)
    new_password: str = Field(min_length=12, max_length=128)


class InviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_uses: int = Field(default=1, ge=1, le=100)
    lifetime_hours: int = Field(default=168, ge=1, le=2160)


class RevokeInviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=20, max_length=512)


def _service(request: Request):
    service = getattr(request.app.state, "auth_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="账户服务暂不可用")
    return service


def _remote_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _cookie_options(request: Request, service) -> dict:
    settings = request.app.state.cloud_settings
    return {
        "path": "/",
        "max_age": service.session_days * 24 * 60 * 60,
        "secure": settings.environment not in {"development", "test"},
        "httponly": True,
        "samesite": "lax",
    }


def _set_session_cookies(response: Response, request: Request, service, issued) -> None:
    options = _cookie_options(request, service)
    response.set_cookie(SESSION_COOKIE, issued.cookie_token, **options)
    response.set_cookie(CSRF_COOKIE, issued.csrf_token, **{**options, "httponly": False})


def _clear_session_cookies(response: Response, request: Request) -> None:
    secure = request.app.state.cloud_settings.environment not in {"development", "test"}
    for name, httponly in ((SESSION_COOKIE, True), (CSRF_COOKIE, False)):
        response.set_cookie(name, "", max_age=0, path="/", secure=secure,
                            httponly=httponly, samesite="lax")


async def _principal(request: Request):
    service = _service(request)
    principal = await service.authenticate(request.cookies.get(SESSION_COOKIE))
    if principal is None:
        raise HTTPException(status_code=401, detail="请先登录")
    return principal


def _require_csrf(request: Request, principal, service) -> None:
    if not service.verify_csrf(principal, request.headers.get("x-csrf-token")):
        raise HTTPException(status_code=403, detail="操作校验失败，请刷新后重试")


def _auth_error(error: AuthError) -> HTTPException:
    if isinstance(error, InvalidCredentials):
        return HTTPException(status_code=401, detail=str(error))
    if isinstance(error, LoginRateLimited):
        return HTTPException(status_code=429, detail=str(error))
    if isinstance(error, PermissionDenied):
        return HTTPException(status_code=403, detail=str(error))
    if isinstance(error, InviteRejected):
        return HTTPException(status_code=400, detail="无法创建账户，请检查邀请码或账户信息")
    if isinstance(error, RegistrationRejected):
        return HTTPException(status_code=400, detail="无法创建账户，请检查邀请码或账户信息")
    return HTTPException(status_code=400, detail="请求无法处理")


@router.post("/register", status_code=201)
async def register(body: Registration, request: Request, response: Response):
    service = _service(request)
    try:
        issued = await service.register(body.email, body.password, body.invite_token,
                                        remote_key=_remote_key(request))
    except AuthError as error:
        raise _auth_error(error) from None
    _set_session_cookies(response, request, service, issued)
    return {"account_id": str(issued.account_id), "csrf": issued.csrf_token}


@router.post("/login")
async def login(body: Credentials, request: Request, response: Response):
    service = _service(request)
    try:
        issued = await service.login(body.email, body.password, remote_key=_remote_key(request))
    except AuthError as error:
        raise _auth_error(error) from None
    _set_session_cookies(response, request, service, issued)
    return {"account_id": str(issued.account_id), "csrf": issued.csrf_token}


@router.get("/session")
async def session(request: Request, response: Response):
    service = _service(request)
    cookie_token = request.cookies.get(SESSION_COOKIE)
    principal = await service.authenticate(cookie_token)
    if principal is None:
        return {"authenticated": False}
    csrf = request.cookies.get(CSRF_COOKIE)
    if not service.verify_csrf(principal, csrf):
        rotated = await service.rotate_csrf(cookie_token)
        if rotated is None:
            _clear_session_cookies(response, request)
            return {"authenticated": False}
        principal, csrf = rotated
        secure = request.app.state.cloud_settings.environment not in {"development", "test"}
        response.set_cookie(CSRF_COOKIE, csrf, path="/", max_age=service.session_days * 86400,
                            secure=secure, httponly=False, samesite="lax")
    return {"authenticated": True, "account_id": str(principal.account_id), "csrf": csrf}


@router.get("/me")
async def me(principal=Depends(_principal)):
    return {"account_id": str(principal.account_id), "is_admin": bool(principal.is_admin)}


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response):
    service = _service(request)
    principal = await service.authenticate(request.cookies.get(SESSION_COOKIE))
    if principal:
        _require_csrf(request, principal, service)
        await service.logout(request.cookies.get(SESSION_COOKIE))
    _clear_session_cookies(response, request)
    response.status_code = 204
    return response


@router.post("/password/change")
async def change_password(body: PasswordChange, request: Request,
                          principal=Depends(_principal)):
    service = _service(request)
    _require_csrf(request, principal, service)
    if not await service.change_password(principal.account_id, body.current_password, body.new_password):
        raise HTTPException(status_code=400, detail="当前密码不正确")
    return {"changed": True, "message": "密码已更新，请重新登录"}


@router.post("/password/forgot", status_code=202)
async def forgot_password(body: PasswordResetRequest, request: Request):
    service = _service(request)
    mailer = getattr(request.app.state, "mailer", None)
    if mailer is None:
        raise HTTPException(status_code=503, detail="密码恢复暂不可用，请联系管理员")
    try:
        await service.request_password_reset(body.email, remote_key=_remote_key(request), mailer=mailer)
    except AuthError:
        pass
    return {"message": "如果账户存在且可以恢复，重置说明将发送至登记邮箱。"}


@router.post("/password/reset")
async def reset_password(body: PasswordResetComplete, request: Request, response: Response):
    service = _service(request)
    if not await service.complete_password_reset(body.token, body.new_password):
        raise HTTPException(status_code=400, detail="重置链接无效或已过期")
    _clear_session_cookies(response, request)
    return {"changed": True, "message": "密码已更新，请重新登录"}


@router.post("/invites", status_code=201)
async def create_invite(body: InviteRequest, request: Request,
                        principal=Depends(_principal)):
    service = _service(request)
    _require_csrf(request, principal, service)
    try:
        token = await service.create_invite(
            principal.account_id, max_uses=body.max_uses,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=body.lifetime_hours),
            remote_key=_remote_key(request),
        )
    except AuthError as error:
        raise _auth_error(error) from None
    return {"token": token, "expires_at": (datetime.now(timezone.utc) + timedelta(hours=body.lifetime_hours)).isoformat()}


@router.post("/invites/revoke")
async def revoke_invite(body: RevokeInviteRequest, request: Request,
                        principal=Depends(_principal)):
    service = _service(request)
    _require_csrf(request, principal, service)
    try:
        revoked = await service.revoke_invite(
            principal.account_id, body.token, remote_key=_remote_key(request)
        )
    except AuthError as error:
        raise _auth_error(error) from None
    if not revoked:
        raise HTTPException(status_code=404, detail="邀请码不存在")
    return {"revoked": True}
