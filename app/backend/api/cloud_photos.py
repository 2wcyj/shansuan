"""Cloud photo APIs never fall back to Windows/local storage or public object URLs."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from app.backend.api.cloud_privacy import require_current_health_consent
from app.backend.api.cloud_profile import repository_for
from app.backend.cloud.context import tenant_context
from app.backend.cloud.domain_store import run_domain
from app.backend.cloud.uploads import read_photo_upload

router = APIRouter(prefix='/api', tags=['cloud-photos'])


def photos_for(request):
    service = getattr(request.app.state, 'cloud_photos', None)
    if service is None:
        raise HTTPException(status_code=503, detail='云端私有照片存储尚未配置，未保存照片')
    return service


@router.post('/analyses')
async def upload(request: Request, principal=Depends(require_current_health_consent)):
    service = photos_for(request)
    data, mime = await read_photo_upload(request)
    with tenant_context(principal.account_id):
        return await service.add(data, mime)


@router.get('/analyses')
async def analyses(request: Request, principal=Depends(require_current_health_consent)):
    photos_for(request)
    return await run_domain(repository_for(request), principal.account_id,
                            lambda store: {'items':store.list('analysis')[-20:]})


@router.get('/photos/{id}')
async def read_photo(id: str, request: Request, principal=Depends(require_current_health_consent)):
    with tenant_context(principal.account_id):
        data = await photos_for(request).read(id)
    return Response(data, media_type='image/jpeg', headers={'Content-Disposition':'inline; filename="photo.jpg"'})


@router.delete('/photos/{id}')
async def delete_photo(id: str, request: Request, principal=Depends(require_current_health_consent)):
    with tenant_context(principal.account_id):
        return await photos_for(request).delete(id)
