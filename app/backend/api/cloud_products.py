"""Per-account product catalogue; existing verification and allergy rules are shared."""
from fastapi import APIRouter, Depends, Request
from app.backend.api.cloud_privacy import require_current_health_consent
from app.backend.api.cloud_profile import repository_for
from app.backend.cloud.domain_store import run_domain
from app.backend.domain.products import seed, settings, save_product, match, consume, add_plan
from app.backend.domain.food import day
from app.backend.errors import AppError

router = APIRouter(prefix='/api', tags=['cloud-products'])


@router.post('/products/settings')
async def configure(body: dict, request: Request, principal=Depends(require_current_health_consent)):
    return await run_domain(repository_for(request), principal.account_id,
        lambda store: store.mutate(body.get('request_key'), {'scope': 'product-settings', **body},
                                   lambda: settings(store, body)))


@router.get('/product-plans')
async def product_plans(date: str, request: Request, principal=Depends(require_current_health_consent)):
    return await run_domain(repository_for(request), principal.account_id,
                            lambda store: {'items': store.list('product_plan', day(date))})


@router.post('/product-plans/{id}/cancel')
async def cancel_plan(id: str, body: dict, request: Request,
                      principal=Depends(require_current_health_consent)):
    def cancel(store):
        def operation():
            plan = store.require('product_plan', id)
            if plan['status'] != 'pending':
                raise AppError('仅待执行产品计划可取消')
            return store.put('product_plan', id, {**plan, 'status': 'cancelled'},
                             day=plan['day'], version=body.get('version'))
        return store.mutate(body.get('request_key'),
                            {'scope': 'product-plan-cancel-' + id, **body}, operation)
    return await run_domain(repository_for(request), principal.account_id, cancel)


@router.put('/products/{id}')
async def edit(id: str, body: dict, request: Request, principal=Depends(require_current_health_consent)):
    def update(store):
        store.require('product', id)
        return store.mutate(body.get('request_key'), {'scope': 'product-edit-' + id, **body},
                            lambda: save_product(store, body, id))
    return await run_domain(repository_for(request), principal.account_id, update)


@router.get('/products')
async def listing(request: Request, principal=Depends(require_current_health_consent)):
    def read(store):
        seed(store)
        items = store.list('product')
        config = settings(store)
        matches = [{'product': item, 'match': match(store, item)} for item in items]
        return {'items': items, 'settings': config, 'recommendations': sorted(
            [item for item in matches if item['match']['eligible']],
            key=lambda item: -item['match']['score']) if config['enabled'] else []}
    return await run_domain(repository_for(request), principal.account_id, read)


@router.get('/products/{id}')
async def detail(id: str, request: Request, principal=Depends(require_current_health_consent)):
    def read(store):
        product = store.require('product', id)
        return {'product': product, 'match': match(store, product),
                'files': [file for file in store.list('product_file') if file['product_id'] == id]}
    return await run_domain(repository_for(request), principal.account_id, read)


@router.post('/products')
async def create(body: dict, request: Request, principal=Depends(require_current_health_consent)):
    return await run_domain(repository_for(request), principal.account_id,
        lambda store: store.mutate(body.get('request_key'), {'scope': 'product-create', **body},
                                   lambda: save_product(store, body)))


@router.post('/products/{id}/consume')
async def actual(id: str, body: dict, request: Request,
                  principal=Depends(require_current_health_consent)):
    return await run_domain(repository_for(request), principal.account_id,
        lambda store: store.mutate(body.get('request_key'), {'scope': 'product-consume-' + id, **body},
                                   lambda: consume(store, id, body)))


@router.post('/products/{id}/plan')
async def plan_product(id: str, body: dict, request: Request,
                       principal=Depends(require_current_health_consent)):
    return await run_domain(repository_for(request), principal.account_id,
        lambda store: store.mutate(body.get('request_key'), {'scope': 'product-plan-' + id, **body},
                                   lambda: add_plan(store, id, body)))
