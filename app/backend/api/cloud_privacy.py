"""Privacy controls for sensitive health information in the cloud runtime."""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import date, datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.backend.api.cloud_auth import _principal, _require_csrf, _service, _auth_error
from app.backend.cloud.auth import AuthError
from app.backend.cloud.domain_store import DomainStore
from app.backend.cloud.context import tenant_context


NOTICE_VERSION = "2026-10-21-v1"
NOTICE_TEXT = (
    "本说明为试用前草案，尚待负责人和法律顾问审阅。膳算云端仅在您明确同意后处理健康档案、"
    "疾病与过敏信息、饮食记录、照片及您提交的问答，用于提供个性化饮食建议、保存记录和生成报告。"
    "这些内容属于敏感个人信息；您可以拒绝或撤回同意，撤回后停止新增健康信息处理，账户登录及数据删除申请仍可使用。"
    "云端计划部署于中国大陆。正式保存期限、云服务商、运维访问范围和权利申请联系渠道尚待确定并补入正式告知。"
    "当前版本不向广告或第三方 AI 服务提供健康信息。您可以申请查阅、复制、更正或删除个人信息；具体处理流程将在正式上线前完成。"
)
router = APIRouter(prefix="/api/privacy", tags=["cloud-privacy"])


class ConsentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notice_version: str = Field(min_length=1, max_length=64)
    confirmed: bool


class PrivacyExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=128)


class AccountDeletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=128)
    confirmation: str = Field(min_length=1, max_length=64)


async def has_current_health_consent(service, account_id) -> bool:
    async with service._connection() as connection:
        async with connection.transaction():
            await service._set_account(connection, account_id)
            return bool(await connection.fetchval(
                "SELECT EXISTS (SELECT 1 FROM privacy_consents "
                "WHERE account_id=$1 AND notice_version=$2 AND withdrawn_at IS NULL)",
                account_id, NOTICE_VERSION,
            ))


async def require_current_health_consent(
    request: Request, principal=Depends(_principal),
):
    service = _service(request)
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        _require_csrf(request, principal, service)
    if not await has_current_health_consent(service, principal.account_id):
        raise HTTPException(
            status_code=428,
            detail="请先阅读并明确同意当前敏感个人信息处理说明",
        )
    return principal


@router.get("/notice")
async def privacy_notice():
    return {"notice_version": NOTICE_VERSION, "draft": True, "text": NOTICE_TEXT}


@router.get("/consent")
async def consent_status(request: Request, principal=Depends(_principal)):
    return {"accepted": await has_current_health_consent(
        _service(request), principal.account_id
    ), "notice_version": NOTICE_VERSION}


@router.post("/consent")
async def accept_consent(
    body: ConsentRequest, request: Request, principal=Depends(_principal),
):
    service = _service(request)
    _require_csrf(request, principal, service)
    if body.notice_version != NOTICE_VERSION:
        raise HTTPException(status_code=409, detail="请刷新并阅读当前版本的隐私说明")
    if not body.confirmed:
        raise HTTPException(status_code=400, detail="需要明确同意后才能启用健康信息功能")

    user_agent = request.headers.get("user-agent", "")[:512]
    digest = hmac.new(
        service.signing_key,
        b"user-agent:" + user_agent.encode("utf-8", errors="replace"),
        hashlib.sha256,
    ).digest()
    async with service._connection() as connection:
        async with connection.transaction():
            await service._set_account(connection, principal.account_id)
            await connection.execute(
                "INSERT INTO privacy_consents "
                "(account_id,id,notice_version,granted_at,user_agent_digest) "
                "VALUES($1,$2,$3,now(),$4)",
                principal.account_id, uuid4(), NOTICE_VERSION, digest,
            )
    return {"accepted": True, "notice_version": NOTICE_VERSION}


@router.post("/consent/withdraw")
async def withdraw_consent(request: Request, principal=Depends(_principal)):
    service = _service(request)
    _require_csrf(request, principal, service)
    async with service._connection() as connection:
        async with connection.transaction():
            await service._set_account(connection, principal.account_id)
            await connection.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',
                                     'domain:' + str(principal.account_id))
            await connection.execute(
                "UPDATE privacy_consents SET withdrawn_at=now() "
                "WHERE account_id=$1 AND notice_version=$2 AND withdrawn_at IS NULL",
                principal.account_id, NOTICE_VERSION,
            )
    return {"accepted": False, "notice_version": NOTICE_VERSION}


@router.post("/export")
async def export_account_data(body: PrivacyExportRequest, request: Request,
                              principal=Depends(_principal)):
    """Download the caller's decrypted account data after password re-authentication."""
    service = _service(request)
    _require_csrf(request, principal, service)
    from app.backend.api.cloud_profile import repository_for
    repository = repository_for(request)
    try:
        async with service.privacy_transaction(
            principal, body.password, request.cookies.get('shansuan_session')
        ) as (connection, email):
            attachment_count = await connection.fetchval(
                "SELECT count(*) FROM attachments WHERE account_id=$1", principal.account_id
            )
            consent_rows = await connection.fetch(
                "SELECT notice_version,granted_at,withdrawn_at FROM privacy_consents "
                "WHERE account_id=$1 ORDER BY granted_at", principal.account_id
            )
            if attachment_count:
                raise HTTPException(status_code=503,
                            detail="账户含云端附件；完整附件导出功能尚未启用，因此未生成不完整导出")
            with tenant_context(principal.account_id):
                async with repository.atomic(connection=connection):
                    rows = await repository.list()
                    store = DomainStore(rows)
                    entities = [
                        {"kind": kind, "id": value["id"], "version": value["version"], "data": value}
                        for (kind, _), value in sorted(store.values.items())
                        if kind != "mutation_request"
                    ]
                    deleted_entities = [row for row in rows if row['body'].get('_deleted') is True]
                    history = await repository.export_history()
    except AuthError as error:
        raise _auth_error(error) from None
    export = {
        "format": "shansuan-account-export-v1",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "account": {"email": email},
        "data": {
            "entities": entities,
            "deleted_entities": deleted_entities,
            "history": history,
            "consents": [{"notice_version": row["notice_version"],
                          "granted_at": row["granted_at"].isoformat(),
                          "withdrawn_at": row["withdrawn_at"].isoformat() if row["withdrawn_at"] else None}
                         for row in consent_rows],
            "attachments": {"count": 0, "status": "no_cloud_attachments"},
        },
    }
    payload = json.dumps(export, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(payload) > 128 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="导出数据超过128MB上限，请联系管理员获取帮助")
    today = date.today().isoformat()
    return Response(payload, media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="shansuan-export-{today}.json"'})


@router.delete("/account")
async def delete_account(body: AccountDeletionRequest, request: Request,
                         principal=Depends(_principal)):
    """Permanently delete the authenticated account and all DB-cascaded tenant rows."""
    if body.confirmation != "删除我的云端账户及全部数据":
        raise HTTPException(status_code=400, detail="请输入“删除我的云端账户及全部数据”确认操作")
    service = _service(request)
    _require_csrf(request, principal, service)
    try:
        async with service.privacy_transaction(
            principal, body.password, request.cookies.get('shansuan_session')
        ) as (connection, _):
            attachment_count = await connection.fetchval(
                "SELECT count(*) FROM attachments WHERE account_id=$1", principal.account_id
            )
            if attachment_count:
                raise HTTPException(status_code=503,
                                    detail="账户仍有关联附件；附件清理服务未启用，因此未删除账户")
            deleted = await connection.fetchval("SELECT cloud_delete_account($1)", principal.account_id)
    except AuthError as error:
        raise _auth_error(error) from None
    if not deleted:
        raise HTTPException(status_code=409,
                            detail="账户未删除；最后一个管理员账户需先移交管理权限")
    response = Response(content=json.dumps({
        "deleted": True,
        "retention_note": "主数据库账户数据已删除；云端备份尚未配置。正式上线前需明确备份保留期限。",
    }, ensure_ascii=False), media_type="application/json")
    secure = request.app.state.cloud_settings.environment not in {"development", "test"}
    response.delete_cookie("shansuan_session", path="/", secure=secure,
                           httponly=True, samesite="lax")
    response.delete_cookie("shansuan_csrf", path="/", secure=secure,
                           httponly=False, samesite="lax")
    return response
