"""Cloud AI routes: Huawei Cloud model API only, never the local model endpoint."""
from fastapi import APIRouter, Depends, HTTPException, Request

from app.backend.api.cloud_privacy import require_current_health_consent
from app.backend.api.cloud_profile import repository_for
from app.backend.cloud.context import tenant_context
from app.backend.cloud.conversation import (VISION_PROMPT, complete_answer, prepare_context,
                                            vision_result)
from app.backend.cloud.domain_store import run_domain
from app.backend.errors import AppError

router = APIRouter(prefix='/api', tags=['cloud-ai'])


def model_for(request):
    client = getattr(request.app.state, 'model_client', None)
    if client is None:
        raise HTTPException(status_code=503,
                            detail='云端模型尚未配置，问答与照片识别暂不可用；手动记录仍可用')
    return client


def photos_for(request):
    service = getattr(request.app.state, 'cloud_photos', None)
    if service is None:
        raise HTTPException(status_code=503, detail='云端私有照片存储尚未配置，未保存照片')
    return service


@router.post('/chat')
async def chat(body: dict, request: Request, principal=Depends(require_current_health_consent)):
    question = str(body.get('question') or '').strip()
    if not 1 <= len(question) <= 1000:
        raise AppError('请填写 1 至 1000 字的问题', 'fields', 422)
    history = body.get('history') if isinstance(body.get('history'), list) else []
    client = model_for(request)
    account = principal.account_id
    repository = repository_for(request)
    context = await run_domain(repository, account,
                               lambda store: prepare_context(store, question, history))
    return await complete_answer(client, context)


@router.post('/analyses/{id}/recognize')
async def recognize(id: str, request: Request,
                    principal=Depends(require_current_health_consent)):
    client = model_for(request)
    service = photos_for(request)
    account = principal.account_id
    repository = repository_for(request)
    with tenant_context(account):
        content = await service.read(id)
    result = await vision_result(client, content, 'image/jpeg')
    analysis_id = str(id).lower()

    def write(store):
        analysis = store.require('analysis', analysis_id)
        if analysis.get('record_id'):
            raise AppError('照片已确认记餐，请在饮食记录中修改实际内容', 'conflict', 409)
        from app.backend.ai.tasks import revise
        return revise(store, analysis_id, {
            'version': analysis['version'],
            'items': result['items'],
            'status': 'analyzed',
            'uncertainty': result['uncertainty'],
            'meta': result['meta'],
        }, model_result=True)

    return await run_domain(repository, account, write)