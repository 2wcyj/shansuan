"""Cloud AI boundaries against PostgreSQL/RLS; only synthetic accounts and images."""
import asyncio
from datetime import date
import time

from app.tests.cloud.test_cloud_photos import photo_app, image_bytes
from app.tests.helpers import profile


class SyntheticModel:
    name = 'synthetic-evaluation-model'
    ready = True
    async def vision(self, content):
        assert content.startswith(b'\xff\xd8')
        return {'foods':[{'name':'未匹配测试食物','ingredients':[], 'grams':100,
                         'recognition_confidence':'低','portion_confidence':'低'}],
                'uncertainty':'合成模型仅用于测试'}
    async def chat(self, payload):
        return {'intent':'protein','steps':['check_records'],'recipe_ids':[]}


def setup_ai(app, client, headers):
    assert client.put('/api/profile', headers=headers,
                      json={**profile(), 'version':0}).status_code == 200
    app.state.cloud_ai.model = SyntheticModel()


def wait_task(client, task_id):
    for _ in range(100):
        response = client.get('/api/tasks/'+task_id)
        assert response.status_code == 200, response.text
        value = response.json()
        if value['status'] not in ['queued','running']:
            return value
        time.sleep(.03)
    raise AssertionError('synthetic task did not finish')


def test_vision_revises_draft_without_intake_and_remains_tenant_private(photo_app):
    app, clients, headers, accounts, objects, repository = photo_app
    a,b=clients; h=headers[0]; setup_ai(app,a,h)
    photo=a.post('/api/analyses',headers=h,files={'file':('meal.png',image_bytes(),'image/png')}).json()
    response=a.post('/api/analyses/'+photo['id']+'/analyze',headers=h,json={'request_key':'vision-synthetic-1'})
    assert response.status_code==200,response.text
    task=wait_task(a,response.json()['id'])
    assert task['status']=='succeeded',task
    assert b.get('/api/tasks/'+task['id']).status_code==404
    revised=a.get('/api/analyses').json()['items'][0]
    assert revised['status']=='analyzed'
    assert revised['nutrition']['protein']['total'] is None
    assert a.get('/api/records',params={'date':date.today().isoformat()}).json()['record_count']==0


def test_photo_confirmation_reuses_nutrition_rules_and_is_idempotent(photo_app):
    app,clients,headers,*_=photo_app; a=clients[0];h=headers[0];setup_ai(app,a,h)
    photo=a.post('/api/analyses',headers=h,files={'file':('meal.png',image_bytes(),'image/png')}).json()
    food=a.get('/api/foods').json()['items'][0]
    edited=a.put('/api/analyses/'+photo['id'],headers=h,json={'version':photo['version'],
        'items':[{'food_id':food['id'],'name':food['name'],'grams':100,'ingredients':[]}],
        'request_key':'revise-synthetic-1'})
    assert edited.status_code==200,edited.text
    body={'version':edited.json()['version'],'date':date.today().isoformat(),'meal':'午餐',
          'time':'12:00','confirmed_uncertainty':True,'request_key':'confirm-synthetic-1'}
    first=a.post('/api/analyses/'+photo['id']+'/confirm',headers=h,json=body)
    assert first.status_code==200,first.text
    assert a.post('/api/analyses/'+photo['id']+'/confirm',headers=h,json=body).json()['id']==first.json()['id']
    assert a.get('/api/records',params={'date':body['date']}).json()['record_count']==1


def test_chat_requires_model_and_valid_decisions_and_never_adds_intake(photo_app):
    app,clients,headers,*_=photo_app;a=clients[0];h=headers[0];setup_ai(app,a,h)
    body={'question':'今天蛋白质够吗','date':date.today().isoformat(),'request_key':'chat-synthetic-1'}
    response=a.post('/api/chat',headers=h,json=body)
    assert response.status_code==200,response.text
    task=wait_task(a,response.json()['task']['id'])
    assert task['status']=='succeeded',task
    assert task['result']['meta']['model']=='synthetic-evaluation-model'
    assert '未记录' in task['result']['reply'] or '记录' in task['result']['reply']
    assert a.get('/api/records',params={'date':body['date']}).json()['record_count']==0
    assert len(a.get('/api/chats').json()['items'][0]['turns'])==2
    async def bad(payload):
        return {'intent':'meals','steps':['check_label'],'recipe_ids':['injected-recipe']}
    app.state.cloud_ai.model.chat=bad
    response=a.post('/api/chat',headers=h,json={**body,'request_key':'chat-synthetic-2'})
    assert wait_task(a,response.json()['task']['id'])['status']=='failed'


def test_unconfigured_model_and_csrf_fail_closed_but_emergency_does_not_wait(photo_app):
    app,clients,headers,*_=photo_app;a=clients[0];h=headers[0]
    response=a.post('/api/chat',headers=h,json={'question':'今天吃什么','request_key':'no-model-1'})
    assert response.status_code==503,response.text
    assert not a.get('/api/model').json()['ready']
    assert a.post('/api/chat',headers={'Origin':h['Origin']},json={'question':'今天吃什么'}).status_code==403
    response=a.post('/api/chat',headers=h,json={'question':'胸痛呼吸困难', 'request_key':'emergency-1'})
    assert response.status_code==200,response.text
    assert '120' in response.json()['immediate']


def test_cancelled_task_cannot_write_late_result(photo_app):
    app,clients,headers,*_=photo_app;a=clients[0];h=headers[0];setup_ai(app,a,h)
    async def delayed(payload):
        await asyncio.sleep(.7)
        return {'intent':'protein','steps':['check_records'],'recipe_ids':[]}
    app.state.cloud_ai.model.chat=delayed
    response=a.post('/api/chat',headers=h,json={'question':'今天吃什么','request_key':'cancel-chat-1'})
    task_id=response.json()['task']['id']
    assert a.post('/api/tasks/'+task_id+'/cancel',headers=h,json={}).status_code==200
    time.sleep(.9)
    assert a.get('/api/tasks/'+task_id).json()['status']=='cancelled'
    assert len(a.get('/api/chats').json()['items'][0]['turns'])==1


def test_consent_withdrawal_discards_in_flight_answer(photo_app):
    app,clients,headers,*_=photo_app;a=clients[0];h=headers[0];setup_ai(app,a,h)
    async def delayed(payload):
        await asyncio.sleep(.7)
        return {'intent':'protein','steps':['check_records'],'recipe_ids':[]}
    app.state.cloud_ai.model.chat=delayed
    response=a.post('/api/chat',headers=h,json={'question':'今天吃什么','request_key':'withdraw-chat-1'})
    assert response.status_code==200,response.text
    assert a.post('/api/privacy/consent/withdraw',headers=h,json={}).status_code==200
    time.sleep(.9)
    assert a.get('/api/tasks/'+response.json()['task']['id']).status_code==428
    from app.backend.cloud.domain_store import run_domain
    rows=asyncio.run(run_domain(app.state.tenant_repository,photo_app[3][0],lambda s:s.list('chat')))
    assert len(rows[0]['turns'])==1


def test_regrant_does_not_revive_a_task_started_before_withdrawal(photo_app):
    from app.backend.api.cloud_privacy import NOTICE_VERSION
    app,clients,headers,*_=photo_app;a=clients[0];h=headers[0];setup_ai(app,a,h)
    async def delayed(payload):
        await asyncio.sleep(.8)
        return {'intent':'protein','steps':['check_records'],'recipe_ids':[]}
    app.state.cloud_ai.model.chat=delayed
    response=a.post('/api/chat',headers=h,json={'question':'今天吃什么','request_key':'regrant-chat-1'})
    task_id=response.json()['task']['id']
    assert a.post('/api/privacy/consent/withdraw',headers=h,json={}).status_code==200
    assert a.post('/api/privacy/consent',headers=h,json={'notice_version':NOTICE_VERSION,'confirmed':True}).status_code==200
    time.sleep(1)
    assert a.get('/api/tasks/'+task_id).json()['status']=='cancelled'
    assert len(a.get('/api/chats').json()['items'][0]['turns'])==1
