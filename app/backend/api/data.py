from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi.responses import Response
from app.backend.errors import AppError

router = APIRouter(prefix='/api/data')


@router.get('/backups')
def backups(request:Request):
    return {'items':request.app.state.backups.listing(),'warning':request.app.state.backups.warning}


@router.post('/backup')
def backup(request:Request,body:dict):
    blob = request.app.state.backups.portable(body.get('password',''),body.get('confirmation',''))
    return Response(blob,media_type='application/octet-stream')


@router.post('/restore/check')
async def check(request:Request,file:UploadFile=File(...),password:str=Form(...)):
    blob = await file.read(512*1024*1024+1)
    return request.app.state.backups.stage(blob,password)


@router.post('/restore/local')
def local(request:Request,body:dict):
    b = request.app.state.backups
    name = body.get('name','')
    if name not in {r['name'] for r in b.listing()}:
        raise AppError('本机备份不存在','not_found',404)
    return b.stage((b.directory / name).read_bytes(),local=True)


@router.post('/restore/commit')
def commit(request:Request,body:dict):
    result=request.app.state.backups.commit(body.get('ticket'),body.get('confirmation'))
    request.app.state.tasks.interrupt_pending()
    return result


@router.get('/export/{format}')
def export(request:Request,format:str):
    return Response(request.app.state.backups.export(format),media_type='application/json' if format=='json' else 'text/csv; charset=utf-8')


@router.post('/delete')
def erase(request:Request,body:dict):
    return request.app.state.backups.erase(body.get('confirmation'),body.get('include_backups') is True)
