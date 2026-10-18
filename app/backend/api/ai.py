from fastapi import APIRouter,Request,UploadFile,File
from app.backend.ai.tasks import revise,confirm_photo,ask
from .records import mutation
router=APIRouter(prefix='/api')

@router.get('/model')
def model():
    from app.scripts.model_runtime import status,MODEL
    r=status();return {'ready':bool(r and any(m['name']==MODEL for m in r.get('models',[]))),'name':MODEL}

@router.get('/tasks')
def tasks(request:Request):return {'items':[request.app.state.tasks.get(t['id']) for t in request.app.state.store.list('task')[-20:]]}

@router.get('/tasks/{id}')
def task(id:str,request:Request):return request.app.state.tasks.get(id)

@router.post('/tasks/{id}/cancel')
def cancel(id:str,request:Request):return request.app.state.tasks.cancel(id)

@router.get('/analyses')
def analyses(request:Request):return {'items':request.app.state.store.list('analysis')[-20:]}

@router.post('/analyses')
async def upload(request:Request,file:UploadFile=File(...)):
    return request.app.state.photos.add(await file.read(12*1024*1024+1))

@router.post('/analyses/{id}/analyze')
def analyze(id:str,request:Request,body:dict):
    s=request.app.state.store
    a=s.require('analysis',id)
    if a.get('record_id'):
        from app.backend.errors import AppError
        raise AppError('此照片已确认记餐，请在饮食记录中修改','conflict',409)
    if any(t['kind']=='vision' and t['status'] in ['queued','running'] and t['payload'].get('analysis_id')==id for t in s.list('task')):
        from app.backend.errors import AppError
        raise AppError('此照片正在处理中，请等待或取消','conflict',409)
    return mutation(s,body,lambda:request.app.state.tasks.submit('vision',{'analysis_id':id,'analysis_version':a['version']}),'vision-'+id)

@router.put('/analyses/{id}')
def edit(id:str,request:Request,body:dict):
    s=request.app.state.store
    return mutation(s,body,lambda:revise(s,id,body),'revise-'+id)

@router.post('/analyses/{id}/confirm')
def confirm(id:str,request:Request,body:dict):
    s=request.app.state.store
    return mutation(s,body,lambda:confirm_photo(s,id,body),'confirm-photo-'+id)

@router.get('/chats')
def chats(request:Request):return {'items':request.app.state.store.list('chat')}

@router.post('/chat')
def chat(request:Request,body:dict):
    s=request.app.state.store
    return mutation(s,body,lambda:ask(s,request.app.state.tasks,body),'chat-ask')
