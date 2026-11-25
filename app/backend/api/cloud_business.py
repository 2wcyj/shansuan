"""Cloud routes execute the existing domain rules in a tenant transaction."""
from fastapi import APIRouter, Depends, Request
from app.backend.api.cloud_privacy import require_current_health_consent
from app.backend.api.cloud_profile import repository_for
from app.backend.cloud.domain_store import run_domain
from app.backend.domain.plans import ensure_current_plan, profile_gate, change
from app.backend.domain.records import summary, save_record, delete_record
from app.backend.domain.records import drink, life
from app.backend.domain.records import save_vital, delete_vital, list_vitals
from app.backend.domain.feedback import save_feedback, reconcile
from app.backend.domain.reports import report
from app.backend.domain.food import day, Foods, aggregate
from app.backend.domain.profile import targets

router = APIRouter(prefix='/api', tags=['cloud-business'])


@router.get('/home/{date}')
async def home(date: str, request: Request, principal=Depends(require_current_health_consent)):
    def read(store):
        reconcile(store)
        profile = store.get('profile', 'self')
        return {**summary(store, date), 'plan': ensure_current_plan(store, date),
                'profile': profile, 'targets': targets(profile),
                'feedback': store.get('feedback', date), 'blocked': profile_gate(profile)}
    return await run_domain(repository_for(request), principal.account_id, read)


@router.get('/foods')
async def foods(request: Request, q: str = '', principal=Depends(require_current_health_consent)):
    return await run_domain(repository_for(request), principal.account_id,
                            lambda store: {'items': Foods(store).search(q)})


@router.post('/nutrition/calculate')
async def calculate(body: dict, request: Request, principal=Depends(require_current_health_consent)):
    def run(store):
        items = Foods(store).calculate(body.get('items'))
        return {'items': items, 'nutrition': aggregate(items)}
    return await run_domain(repository_for(request), principal.account_id, run)


@router.put('/life')
async def write_life(body: dict, request: Request, principal=Depends(require_current_health_consent)):
    return await run_domain(repository_for(request), principal.account_id,
        lambda store: store.mutate(body.get('request_key'), {'scope': 'life', **body},
                                   lambda: life(store, body)))


@router.post('/life/water')
async def record_water(body: dict, request: Request, principal=Depends(require_current_health_consent)):
    return await run_domain(repository_for(request), principal.account_id,
        lambda store: store.mutate(body.get('request_key'), {'scope': 'water', **body},
                                   lambda: drink(store, body)))


@router.get('/vitals')
async def read_vitals(date: str, request: Request, principal=Depends(require_current_health_consent)):
    return await run_domain(repository_for(request), principal.account_id,
                            lambda store: {'items': list_vitals(store, date)})


@router.post('/vitals')
async def create_vital(body: dict, request: Request, principal=Depends(require_current_health_consent)):
    return await run_domain(repository_for(request), principal.account_id,
        lambda store: store.mutate(body.get('request_key'), {'scope': 'vital-add', **body},
                                   lambda: save_vital(store, body)))


@router.put('/vitals/{id}')
async def edit_vital(id: str, body: dict, request: Request,
                     principal=Depends(require_current_health_consent)):
    def edit(store):
        store.require('vital', id)
        return store.mutate(body.get('request_key'), {'scope': 'vital-' + id, **body},
                            lambda: save_vital(store, body, id))
    return await run_domain(repository_for(request), principal.account_id, edit)


@router.post('/vitals/{id}/delete')
async def remove_vital(id: str, body: dict, request: Request,
                       principal=Depends(require_current_health_consent)):
    return await run_domain(repository_for(request), principal.account_id,
        lambda store: store.mutate(body.get('request_key'), {'scope': 'vital-delete-' + id, **body},
            lambda: delete_vital(store, id, body.get('version'))))


@router.get('/feedback/{date}')
async def read_feedback(date: str, request: Request, principal=Depends(require_current_health_consent)):
    def read(store):
        value = day(date)
        reconcile(store)
        return {'feedback': store.get('feedback', value), 'adjustment': store.get('adjustment', value)}
    return await run_domain(repository_for(request), principal.account_id, read)


@router.put('/feedback/{date}')
async def write_feedback(date: str, body: dict, request: Request,
                         principal=Depends(require_current_health_consent)):
    return await run_domain(repository_for(request), principal.account_id,
        lambda store: store.mutate(body.get('request_key'), {'scope': 'feedback-' + date, **body},
            lambda: save_feedback(store, date, body)))


@router.get('/reports')
async def read_report(end: str, request: Request, days: int = 7,
                      principal=Depends(require_current_health_consent)):
    def read(store):
        reconcile(store)
        return report(store, end, days)
    return await run_domain(repository_for(request), principal.account_id, read)


@router.post('/plans/{date}/meals/{id}')
async def change_meal(date: str, id: str, body: dict, request: Request,
                      principal=Depends(require_current_health_consent)):
    return await run_domain(repository_for(request), principal.account_id,
        lambda store: store.mutate(body.get('request_key'),
            {'scope': 'plan-change-' + date + '-' + id, **body},
            lambda: change(store, date, id, body)))


@router.get('/plans/{date}')
async def plan(date: str, request: Request, principal=Depends(require_current_health_consent)):
    def read(store):
        return {'plan': ensure_current_plan(store, date),
                'blocked': profile_gate(store.get('profile', 'self'))}
    return await run_domain(repository_for(request), principal.account_id, read)


@router.get('/records')
async def records(date: str, request: Request, principal=Depends(require_current_health_consent)):
    return await run_domain(repository_for(request), principal.account_id,
                            lambda store: summary(store, date))


@router.post('/records')
async def create_record(body: dict, request: Request, principal=Depends(require_current_health_consent)):
    values = {**body, 'source': 'manual', 'plan_id': None, 'meal_id': None, 'analysis_id': None}
    return await run_domain(repository_for(request), principal.account_id,
        lambda store: store.mutate(body.get('request_key'), {'scope': 'record-add', **values},
                                   lambda: save_record(store, values)))


@router.put('/records/{id}')
async def edit_record(id: str, body: dict, request: Request,
                       principal=Depends(require_current_health_consent)):
    def edit(store):
        store.require('record', id)
        return store.mutate(body.get('request_key'), {'scope': 'record-edit-' + id, **body},
                            lambda: save_record(store, body, id))
    return await run_domain(repository_for(request), principal.account_id, edit)


@router.post('/records/{id}/delete')
async def remove_record(id: str, body: dict, request: Request,
                        principal=Depends(require_current_health_consent)):
    return await run_domain(repository_for(request), principal.account_id,
        lambda store: store.mutate(body.get('request_key'), {'scope': 'record-delete-' + id, **body},
            lambda: delete_record(store, id, body.get('version'))))
