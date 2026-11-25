"""Cloud profile routes reuse the original domain validation and save rules."""
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from app.backend.api.cloud_privacy import require_current_health_consent
from app.backend.cloud.domain_store import run_domain, encode
from app.backend.domain.profile import save_profile, targets
from app.backend.domain.plans import generate, profile_gate

router = APIRouter(prefix='/api', tags=['cloud-profile'])


def repository_for(request):
    repository = getattr(request.app.state, 'tenant_repository', None)
    if repository is None:
        raise HTTPException(status_code=503, detail='云端个人资料服务尚未配置')
    return repository


@router.get('/profile')
async def read_profile(request: Request, principal=Depends(require_current_health_consent)):
    def read(store):
        profile = store.get('profile', 'self')
        return {'profile': profile, 'draft': store.get('draft', 'onboarding'),
                'targets': targets(profile), 'measurements': store.list('measurement')}
    return await run_domain(repository_for(request), principal.account_id, read)


@router.put('/profile')
async def write_profile(request: Request, body: dict, principal=Depends(require_current_health_consent)):
    def save(store):
        first = store.get('profile', 'self') is None
        result = save_profile(store, body.copy())
        if first and not profile_gate(result['profile']):
            generate(store, date.today().isoformat())
        return result
    try:
        return await run_domain(repository_for(request), principal.account_id, save)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail='请检查档案字段：' + error.errors()[0]['msg']) from None


@router.put('/profile/draft')
async def write_draft(request: Request, body: dict, principal=Depends(require_current_health_consent)):
    values, step, version = body.get('values', {}), body.get('step', 0), body.get('version', 0)
    if not isinstance(values, dict) or len(encode(values).encode()) > 40000:
        raise HTTPException(status_code=422, detail='草稿内容格式错误或过长')
    if type(step) is not int or type(version) is not int or version < 0:
        raise HTTPException(status_code=422, detail='草稿版本无效')
    return await run_domain(repository_for(request), principal.account_id,
        lambda store: store.put('draft', 'onboarding', {'values': values, 'step': min(5, max(0, step))}, version=version))
