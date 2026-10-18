from pathlib import Path
import secrets
import hashlib
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse
from app.backend.errors import AppError
from app.backend.storage.database import Store
from app.backend.storage.photos import Photos
from app.backend.storage.backups import Backups

ROOT = Path(__file__).resolve().parents[2]


def create_app(data_dir, port=18765):
    app = FastAPI(title='膳算', version='0.1.0', docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = Store(data_dir)
    app.state.photos = Photos(app.state.store)
    app.state.backups = Backups(app.state.store)
    try:app.state.backups.daily()
    except AppError:pass  # Read-only access stays available; writes remain blocked.
    from app.backend.ai.tasks import Tasks
    app.state.tasks = Tasks(app.state.store,app.state.photos)
    app.state.session = secrets.token_urlsafe(32)
    app.state.csrf = secrets.token_urlsafe(32)
    hosts = {f'127.0.0.1:{port}',f'localhost:{port}'}
    origins = {'http://' + host for host in hosts}

    @app.middleware('http')
    async def local_access(request:Request, call_next):
        origin = request.headers.get('origin')
        if request.headers.get('host') not in hosts or (origin is not None and origin not in origins):
            return JSONResponse({'error':{'code':'origin','message':'仅允许本机应用页面访问'}},403)
        if request.url.path.startswith('/api/') and request.url.path != '/api/session':
            if not secrets.compare_digest(request.cookies.get('mna_session',''),app.state.session):
                return JSONResponse({'error':{'code':'session','message':'会话已更新，请刷新页面'}},403)
            if request.method not in {'GET','HEAD','OPTIONS'} and not secrets.compare_digest(request.headers.get('x-csrf-token',''),app.state.csrf):
                return JSONResponse({'error':{'code':'csrf','message':'操作校验失败，请刷新后重试'}},403)
        response = await call_next(request)
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
            'Referrer-Policy':'no-referrer','X-Frame-Options':'DENY',
            'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        return response

    @app.exception_handler(AppError)
    async def app_error(request,error):
        return JSONResponse({'error':{'code':error.code,'message':error.message}},error.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request,error):
        return JSONResponse({'error':{'code':'fields','message':'请检查填写内容','fields':{'.'.join(map(str,e['loc'][1:])):e['msg'] for e in error.errors()}}},422)

    @app.exception_handler(Exception)
    async def unexpected_error(request,error):
        return JSONResponse({'error':{'code':'storage','message':'操作未完成，请检查磁盘空间或文件权限后重试；原有数据已保留'}},503)

    @app.get('/api/session')
    def session():
        response = JSONResponse({'csrf':app.state.csrf,'app':'mna','version':'0.1.0','data_id':hashlib.sha256(str(app.state.store.root).casefold().encode()).hexdigest()})
        response.set_cookie('mna_session',app.state.session,httponly=True,samesite='strict')
        return response

    @app.get('/api/status')
    def status():
        return {'app':'mna','storage':'ready','schema':1,'data_path':str(app.state.store.root)}

    @app.get('/api/photos/{id}')
    def photo(id:str):
        from fastapi.responses import Response
        return Response(app.state.photos.read(id),media_type='image/jpeg')

    from app.backend.api.data import router as data_router
    app.include_router(data_router)
    from app.backend.api.profile import router as profile_router
    app.include_router(profile_router)
    from app.backend.api.records import router as records_router
    app.include_router(records_router)
    from app.backend.api.plans import router as plans_router
    app.include_router(plans_router)
    from app.backend.api.ai import router as ai_router
    app.include_router(ai_router)

    from app.backend.api.feedback import router as feedback_router
    app.include_router(feedback_router)

    @app.get('/{path:path}')
    def frontend(path:str):
        dist = ROOT / 'app/frontend/dist'
        candidate = (dist / path).resolve()
        if path.startswith('api/'):
            raise AppError('接口不存在','not_found',404)
        if candidate.is_relative_to(dist.resolve()) and candidate.is_file():
            return FileResponse(candidate)
        if (dist / 'index.html').is_file():
            return FileResponse(dist / 'index.html')
        raise AppError('界面尚未构建，请按安装说明准备','frontend',503)

    from app.backend.domain.feedback import reconcile
    try:reconcile(app.state.store)
    except AppError:pass
    return app
