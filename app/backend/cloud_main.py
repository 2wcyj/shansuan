"""Cloud-only FastAPI bootstrap; it never opens the local Windows data store."""
from contextlib import asynccontextmanager
from collections.abc import Callable
import inspect
import asyncio

import asyncpg
from fastapi import Request
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.backend.api.cloud_auth import router as cloud_auth_router
from app.backend.api.cloud_privacy import router as cloud_privacy_router
from app.backend.api.cloud_profile import router as cloud_profile_router
from app.backend.api.cloud_business import router as cloud_business_router
from app.backend.api.cloud_products import router as cloud_products_router
from app.backend.api.cloud_photos import router as cloud_photos_router
from app.backend.api.cloud_ai import router as cloud_ai_router
from app.backend.errors import AppError
from app.backend.cloud.auth import AuthService
from app.backend.cloud.config import CloudSettings
from app.backend.cloud.mailer import mailer_from_env
from app.backend.cloud.kms import key_manager_from_env, KMSUnavailable
from app.backend.cloud.crypto import CloudCrypto
from app.backend.cloud.repository import TenantRepository
from app.backend.cloud.object_store import object_store_from_env, ObjectStoreUnavailable
from app.backend.cloud.photos import CloudPhotos
from app.backend.cloud.redis_store import redis_store_from_env, RedisUnavailable
from app.backend.cloud.model_client import model_client_from_env


def create_cloud_app(settings: CloudSettings, readiness_probe: Callable | None = None,
                     auth_service: AuthService | None = None, mailer=None,
                     tenant_repository=None, key_manager=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        owned_pool = None
        manager = key_manager
        if manager is None and settings.environment != 'test':
            manager = key_manager_from_env(settings.environment)
        app.state.kms_manager = manager
        if manager is not None:
            await asyncio.to_thread(manager.check)
            app.state.kms_ready = True
        else:
            app.state.kms_ready = settings.environment == 'test'
        if app.state.redis_store is None and settings.environment != 'test':
            app.state.redis_store = redis_store_from_env()
        if app.state.redis_store is not None:
            try:
                app.state.redis_ready = bool(await app.state.redis_store.ping())
            except RedisUnavailable:
                # PostgreSQL remains the durable session and rate-limit fallback.
                app.state.redis_ready = False
        if app.state.model_client is None and settings.environment != 'test':
            app.state.model_client = model_client_from_env()
        if app.state.auth_service is None and settings.environment != 'test':
            database_url = settings.database_url.replace('postgresql+asyncpg://', 'postgresql://', 1)
            owned_pool = await asyncpg.create_pool(database_url, min_size=0, max_size=10,
                                                   command_timeout=10)
            app.state.auth_service = AuthService(owned_pool, signing_key=settings.session_signing_key,
                                                 redis=app.state.redis_store)
            if app.state.tenant_repository is None and manager is not None:
                app.state.tenant_repository = TenantRepository(owned_pool, CloudCrypto(manager))
            if app.state.readiness_probe is None:
                async def probe_database():
                    async with owned_pool.acquire() as connection:
                        return await connection.fetchval('SELECT 1') == 1
                app.state.readiness_probe = probe_database
        if app.state.mailer is None and settings.environment != 'test':
            app.state.mailer = mailer_from_env()
        objects = app.state.object_store
        if objects is None and settings.environment != 'test':
            objects = object_store_from_env()
        if objects is not None:
            await asyncio.to_thread(objects.check)
            app.state.object_store = objects
            app.state.object_store_ready = True
            if app.state.tenant_repository is not None:
                app.state.cloud_photos = CloudPhotos(app.state.tenant_repository, objects)
        try:
            yield
        finally:
            if owned_pool is not None:
                await owned_pool.close()

    app = FastAPI(title='膳算 Cloud', version='0.1.0', docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)
    app.state.cloud_settings = settings
    app.state.readiness_probe = readiness_probe
    app.state.auth_service = auth_service
    app.state.mailer = mailer
    app.state.tenant_repository = tenant_repository
    app.state.kms_manager = None
    app.state.object_store = None
    app.state.object_store_ready = False
    app.state.cloud_photos = None
    app.state.redis_store = None
    app.state.redis_ready = False
    app.state.model_client = None

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.frontend_origins),
        allow_credentials=True,
        allow_methods=['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
        allow_headers=['Content-Type', 'X-CSRF-Token'],
        expose_headers=['Content-Disposition'],
        max_age=600,
    )

    @app.middleware('http')
    async def enforce_exact_origin(request: Request, call_next):
        if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            if request.headers.get('origin') not in settings.frontend_origins:
                return JSONResponse({'detail': '请求来源校验失败'}, status_code=403)
        response = await call_next(request)
        response.headers.update({
            'Cache-Control': 'no-store',
            'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'no-referrer',
            'X-Frame-Options': 'DENY',
        })
        return response

    app.include_router(cloud_auth_router)
    app.include_router(cloud_privacy_router)
    app.include_router(cloud_profile_router)
    app.include_router(cloud_business_router)
    app.include_router(cloud_products_router)
    app.include_router(cloud_photos_router)
    app.include_router(cloud_ai_router)

    @app.exception_handler(ObjectStoreUnavailable)
    async def objects_unavailable(request, error):
        request.app.state.object_store_ready = False
        return JSONResponse({'detail':'云端私有照片存储暂不可用，请稍后重试'}, status_code=503)

    @app.exception_handler(AppError)
    async def domain_error(request, error):
        return JSONResponse({'error': {'code': error.code, 'message': error.message}},
                            status_code=error.status)

    @app.exception_handler(KMSUnavailable)
    async def encryption_unavailable(request, error):
        request.app.state.kms_ready = False
        return JSONResponse({'detail': '云端加密服务暂不可用，请稍后重试'}, status_code=503)

    @app.get('/health/live', include_in_schema=False)
    async def live():
        return {'status': 'ok'}

    @app.get('/health/ready', include_in_schema=False)
    async def ready():
        probe = app.state.readiness_probe
        if not probe:
            database_ready = False
        else:
            try:
                result = probe()
                database_ready = bool(await result) if inspect.isawaitable(result) else bool(result)
            except Exception:
                database_ready = False
        dependencies = {'database': database_ready}
        if app.state.kms_manager is not None:
            # The startup probe performs a billable KMS encrypt/decrypt round trip.
            # Do not repeat it on every platform readiness poll.
            dependencies['kms'] = app.state.kms_ready
        if app.state.object_store is not None:
            dependencies['object_store'] = app.state.object_store_ready
        cache = {}
        if app.state.redis_store is not None:
            try:
                cache['redis'] = bool(await app.state.redis_store.ping())
            except RedisUnavailable:
                cache['redis'] = False
        if not all(dependencies.values()):
            return JSONResponse({'status': 'not_ready', 'dependencies': dependencies,
                                 'cache': cache}, status_code=503)
        # Redis is the shared fast path; PostgreSQL still carries sessions when it is down.
        status = 'ready' if all(cache.values()) else 'degraded'
        return {'status': status, 'dependencies': dependencies, 'cache': cache}

    return app


app = create_cloud_app(CloudSettings.from_env())
