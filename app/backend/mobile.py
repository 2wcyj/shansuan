"""Authenticated HTTPS LAN gateway. Never exposes the Windows API directly."""
import asyncio
from contextlib import asynccontextmanager
import ipaddress
import secrets

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

PRIVATE_NETWORKS = tuple(ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
MAX_BODY = 12 * 1024 * 1024 + 65536


def private_ipv4(value):
    try:
        address = ipaddress.IPv4Address(value)
        return any(address in network for network in PRIVATE_NETWORKS)
    except ipaddress.AddressValueError:
        return False


def create_mobile_app(host, token, *, port=18766, upstream_port=18765, upstream_transport=None):
    if not private_ipv4(host) or len(token) < 64:
        raise ValueError('需要局域网IPv4地址和至少256位访问凭据')
    origin = f'https://{host}:{port}'
    authority = f'{host}:{port}'
    csrf = secrets.token_urlsafe(32)
    session_lock = asyncio.Lock()
    slots = asyncio.Semaphore(8)
    upstream_csrf = ''

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{upstream_port}',
                transport=upstream_transport, trust_env=False, timeout=180, follow_redirects=False) as client:
            app.state.upstream = client
            yield

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    def failure(message, code='mobile', status=403):
        return JSONResponse({'error': {'code': code, 'message': message}}, status_code=status,
                            headers={'Cache-Control': 'no-store'})

    @app.middleware('http')
    async def authorize(request, call_next):
        if request.url.scheme != 'https' or request.headers.get('host') != authority:
            return failure('连接地址不匹配，请重新导入电脑生成的连接文件')
        if request.headers.get('origin') not in (None, origin):
            return failure('仅允许已配对的膳算页面访问')
        client_host = request.client.host if request.client else ''
        if client_host != 'testclient' and client_host != '127.0.0.1' and not private_ipv4(client_host):
            return failure('仅支持同一局域网访问')
        cookie = request.cookies.get('shansuan_mobile', '')
        if not secrets.compare_digest(cookie, token):
            return failure('手机尚未配对或连接已失效，请在应用菜单重新连接', 'pairing')
        path = request.url.path
        if (path.startswith('/api/data') and path != '/api/data/backup/local') or path == '/api/shutdown':
            return failure('请在电脑端进行备份导出、恢复或删除等管理操作', 'desktop_only')
        if request.method not in ('GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE'):
            return failure('不支持此请求', status=405)
        if request.method not in ('GET', 'HEAD') and not secrets.compare_digest(request.headers.get('x-csrf-token', ''), csrf):
            return failure('操作校验失败，请刷新页面后重试', 'csrf')
        try:
            size = int(request.headers.get('content-length', '0'))
        except ValueError:
            return failure('请求大小无效', status=400)
        if size < 0 or size > MAX_BODY:
            return failure('图片过大，请选择12MB以内的图片', status=413)
        response = await call_next(request)
        response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY'})
        return response

    async def refresh_session(client):
        nonlocal upstream_csrf
        async with session_lock:
            result = await client.get('/api/session')
            result.raise_for_status()
            data = result.json()
            if data.get('app') != 'mna':
                raise ValueError('unexpected upstream')
            upstream_csrf = data['csrf']

    @app.get('/api/session')
    async def session():
        return {'app': 'mna', 'version': '0.1.0', 'csrf': csrf, 'mode': 'mobile'}

    @app.get('/api/status')
    async def status():
        return {'app': 'mna', 'mode': 'mobile', 'storage': 'computer', 'connection': 'paired'}

    @app.api_route('/{path:path}', methods=['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE'])
    async def proxy(request: Request, path: str):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BODY:
                return failure('图片过大，请选择12MB以内的图片', status=413)
        # A relative path only, never a client-selected upstream URL.
        url = httpx.URL(f'http://127.0.0.1:{upstream_port}').copy_with(
            raw_path=request.scope['raw_path'] + (b'?' + request.scope['query_string'] if request.scope['query_string'] else b''))
        headers = {key: value for key, value in request.headers.items() if key in ('content-type', 'accept')}
        async with slots:
            client = app.state.upstream
            try:
                if not upstream_csrf:
                    await refresh_session(client)
                for attempt in range(2):
                    result = await client.request(request.method, url, content=bytes(body),
                        headers={**headers, 'x-csrf-token': upstream_csrf})
                    if result.status_code != 403 or attempt:
                        break
                    try:
                        expired = result.json().get('error', {}).get('code') == 'session'
                    except ValueError:
                        expired = False
                    if not expired:
                        break
                    await refresh_session(client)
            except (httpx.HTTPError, ValueError, KeyError):
                return failure('电脑服务暂未连接，请确认电脑已开机并启动膳算，然后重试', 'offline', 503)
        forwarded = {k: v for k, v in result.headers.items()
                     if k in ('content-type', 'content-security-policy', 'content-disposition')}
        # Do not pass upstream cookies, local paths or hop-by-hop headers.
        return Response(result.content, status_code=result.status_code, headers=forwarded)

    return app
