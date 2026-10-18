from fastapi import APIRouter,Request
from pydantic import ValidationError
from app.backend.domain.profile import save_profile,targets
from app.backend.errors import AppError
router=APIRouter(prefix='/api')


@router.get('/profile')
def read(request:Request):
    s=request.app.state.store
    p=s.get('profile','self')
    return {'profile':p,'draft':s.get('draft','onboarding'),'targets':targets(p),'measurements':s.list('measurement')}


@router.put('/profile')
def save(request:Request,body:dict):
    try:
        s=request.app.state.store
        with s.atomic():
            first=s.get('profile','self') is None
            result=save_profile(s,body.copy())
            if first:
                from datetime import date
                from app.backend.domain.plans import generate,profile_gate
                if not profile_gate(result['profile']):generate(s,date.today().isoformat())
            return result
    except ValidationError as e:
        first=e.errors()[0]
        raise AppError('.'.join(map(str,first['loc']))+'：'+first['msg'],'fields',422) from e


@router.put('/profile/draft')
def draft(request:Request,body:dict):
    from app.backend.storage.database import encode
    if len(encode(body))>40000:
        raise AppError('草稿内容过长')
    return request.app.state.store.put('draft','onboarding',{'values':body.get('values',{}),'step':min(5,max(0,int(body.get('step',0))))},version=body.get('version',0))
