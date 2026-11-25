"""Cloud AI and manual photo review, reusing local nutrition and safety rules."""
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, Request

from app.backend.api.cloud_privacy import require_current_health_consent
from app.backend.ai.tasks import revise
from app.backend.cloud.domain_store import physical_id
from app.backend.domain.records import save_record
from app.backend.errors import AppError

router=APIRouter(prefix='/api',tags=['cloud-ai'])


def service(request):
    value=getattr(request.app.state,'cloud_ai',None)
    if value is None:raise AppError('云端分析服务尚未配置','cloud_ai',503)
    return value


@router.get('/model')
async def model_status(request:Request,principal=Depends(require_current_health_consent)):
    model=service(request).model
    return {'ready':model is not None,'name':model.name if model else None,'mode':'cloud',
            'note':'已配置私有模型；实际推理失败时显示错误，不产生替代答案'}


@router.get('/tasks')
async def list_tasks(request:Request,principal=Depends(require_current_health_consent)):
    return await service(request).listing(principal.account_id)


@router.get('/tasks/{id}')
async def get_task(id:str,request:Request,principal=Depends(require_current_health_consent)):
    return await service(request).get(principal.account_id,id)


@router.post('/tasks/{id}/cancel')
async def cancel_task(id:str,request:Request,principal=Depends(require_current_health_consent)):
    return await service(request).cancel(principal.account_id,id)


@router.post('/analyses/{id}/analyze')
async def analyze(id:str,request:Request,body:dict,principal=Depends(require_current_health_consent)):
    return await service(request).submit_vision(principal.account_id,id,body)


@router.put('/analyses/{id}')
async def edit(id:str,request:Request,body:dict,principal=Depends(require_current_health_consent)):
    return await service(request).operation(principal.account_id,lambda s:s.mutate(body.get('request_key'),
        {'scope':'cloud-revise-'+id,**body},lambda:revise(s,id,body)))


@router.post('/analyses/{id}/confirm')
async def confirm(id:str,request:Request,body:dict,principal=Depends(require_current_health_consent)):
    ai=service(request)
    def save(s):
        def create():
            a=s.require('analysis',id)
            if a.get('record_id'):return s.require('record',a['record_id'])
            if a['version']!=body.get('version'):raise AppError('照片已修改，请重新核对','conflict',409)
            if not a['items'] or any(not i['food_id'] for i in a['items']):raise AppError('请先核对食物与营养来源')
            if body.get('confirmed_uncertainty') is not True:raise AppError('请确认估算局限和实际食用分量')
            record=save_record(s,{'date':body.get('date'),'meal':body.get('meal'),'time':body.get('time'),
                'items':a['items'],'source':'photo','analysis_id':id})
            s.put('analysis',id,{**a,'status':'confirmed','record_id':record['id']},version=a['version'])
            s.link('analysis',id,'record',record['id'])
            return record
        return s.mutate(body.get('request_key'),{'scope':'cloud-confirm-'+id,**body},create)
    result=await ai.operation(principal.account_id,save)
    # The analysis retains its attachment relationship; records refer to analysis_id.
    # No duplicated attachment is created and repeat confirmations return one record.
    return result


@router.get('/chats')
async def chats(request:Request,principal=Depends(require_current_health_consent)):
    return await service(request).operation(principal.account_id,lambda s:{'items':s.list('chat')})


@router.post('/chat')
async def chat(request:Request,body:dict,principal=Depends(require_current_health_consent)):
    return await service(request).submit_chat(principal.account_id,body)
