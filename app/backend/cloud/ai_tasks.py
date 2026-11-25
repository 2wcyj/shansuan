"""Encrypted per-account tasks with leases and authorization checked at commit.

Pending work is resumed on the authenticated owner's next task poll after a
restart. No global tenant bypass or plaintext task payload is required.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import time
import uuid

from app.backend.ai.model import ChatResult, VisionResult
from app.backend.ai.tasks import ask, revise, render_reply
from app.backend.cloud.context import tenant_context
from app.backend.cloud.domain_store import DomainStore, run_domain
from app.backend.domain.food import Foods
from app.backend.domain.profile import targets
from app.backend.errors import AppError


class Submitter:
    def __init__(self,store):self.store=store
    def submit(self,kind,payload):
        return self.store.put('task',uuid.uuid4().hex,{'kind':kind,'status':'queued',
            'payload':payload,'result':None,'error':None,'lease_until':None,'attempts':0})


class CloudAI:
    def __init__(self,repository,photos,model):
        self.repository,self.photos,self.model=repository,photos,model
        self.running={}
        self.slots=asyncio.Semaphore(1)
        self.closed=False

    async def operation(self,account,fn):
        with tenant_context(account):
            async with self.repository.atomic():
                await self.repository.lock_account()
                async with self.repository._tenant_connection() as (_,connection):
                    from app.backend.api.cloud_privacy import NOTICE_VERSION
                    accepted=await connection.fetchval('SELECT EXISTS(SELECT 1 FROM privacy_consents '
                        'WHERE account_id=$1 AND notice_version=$2 AND withdrawn_at IS NULL)',account,NOTICE_VERSION)
                    if not accepted:raise AppError('健康信息授权已撤回，任务未采用','consent_required',428)
                    store=DomainStore(await self.repository.list())
                    result=fn(store)
                    await store.flush(self.repository)
                    return result

    def require_model(self):
        if self.model is None:raise AppError('云端模型尚未配置，可继续手动记录','model_unavailable',503)

    async def submit_chat(self,account,body):
        from app.backend.ai.safety import immediate
        question=body.get('question','')
        if isinstance(question,str) and immediate(question):
            return await self.operation(account,lambda s:ask(s,Submitter(s),body))
        self.require_model()
        def submit(s):
            if sum(t['status'] in {'queued','running'} for t in s.list('task'))>=4:
                raise AppError('任务较多，请先等待或取消','task_quota',429)
            return s.mutate(body.get('request_key'),{'scope':'cloud-chat',**body},lambda:ask(s,Submitter(s),body))
        result=await self.operation(account,submit)
        self.schedule(account,result['task']['id'])
        return result

    async def submit_vision(self,account,analysis_id,body):
        self.require_model()
        if self.photos is None:raise AppError('照片存储未配置','photo_storage',503)
        def submit(s):
            def create():
                a=s.require('analysis',analysis_id)
                if a.get('record_id'):raise AppError('已确认记餐的照片不能重新分析','conflict',409)
                if any(t['status'] in {'queued','running'} and (t['kind']=='vision'
                      and t['payload'].get('analysis_id')==analysis_id) for t in s.list('task')):
                    raise AppError('此照片已有任务，请等待或取消','conflict',409)
                if sum(t['status'] in {'queued','running'} for t in s.list('task'))>=4:
                    raise AppError('任务较多，请先等待或取消','task_quota',429)
                p=s.require('profile','self')
                return Submitter(s).submit('vision',{'analysis_id':analysis_id,
                    'analysis_version':a['version'],'profile_version':p['version']})
            return s.mutate(body.get('request_key'),{'scope':'cloud-vision-'+analysis_id,**body},create)
        task=await self.operation(account,submit)
        self.schedule(account,task['id'])
        return task

    def schedule(self,account,id):
        key=(account,id)
        if self.closed or self.model is None or key in self.running:return
        task=asyncio.create_task(self.work(account,id))
        self.running[key]=task
        task.add_done_callback(lambda _:self.running.pop(key,None))

    async def listing(self,account):
        tasks=await self.operation(account,lambda s:s.list('task')[-20:])
        for task in tasks:
            if task['status'] in {'queued','running'}:self.schedule(account,task['id'])
        return {'items':tasks}

    async def get(self,account,id):
        task=await self.operation(account,lambda s:s.require('task',id))
        if task['status'] in {'queued','running'}:self.schedule(account,id)
        return task

    async def cancel(self,account,id):
        def cancel(s):
            t=s.require('task',id)
            return s.put('task',id,{**t,'status':'cancelled','error':'任务已取消，结果不会写入'},version=t['version']) if t['status'] in {'queued','running'} else t
        return await self.operation(account,cancel)

    async def work(self,account,id):
        async with self.slots:
            claim=uuid.uuid4().hex
            def acquire(s):
                t=s.require('task',id)
                if t['status'] not in {'queued','running'}:return None
                if t['status']=='running' and t.get('lease_until') and datetime.fromisoformat(t['lease_until'])>datetime.now(timezone.utc):return None
                if t.get('attempts',0)>=3:
                    s.put('task',id,{**t,'status':'failed','error':'任务重试次数已达上限，请重新提交'},version=t['version']);return None
                return s.put('task',id,{**t,'status':'running','claim':claim,'attempts':t.get('attempts',0)+1,
                    'lease_until':(datetime.now(timezone.utc)+timedelta(minutes=4)).isoformat()},version=t['version'])
            try:
                t=await self.operation(account,acquire)
                if not t:return
                started=time.monotonic()
                if t['kind']=='vision':
                    with tenant_context(account):content=await self.photos.read(t['payload']['analysis_id'])
                    output=VisionResult.model_validate(await asyncio.wait_for(self.model.vision(content),125)).model_dump()
                else:
                    output=ChatResult.model_validate(await asyncio.wait_for(self.model.chat(t['payload']),125)).model_dump()
                meta={'model':self.model.name,'seconds':round(time.monotonic()-started,2),'prompt_version':'cloud-private-v1'}
                def finish(s):
                    current=s.require('task',id)
                    if current['status']!='running' or current.get('claim')!=claim:return
                    p=s.require('profile','self');payload=t['payload']
                    expected=payload.get('profile_version',payload.get('profile',{}).get('version'))
                    if p['version']!=expected:raise AppError('档案已更新，旧任务结果未采用，请重新分析','conflict',409)
                    if t['kind']=='vision':
                        a=s.require('analysis',payload['analysis_id'])
                        if a['version']!=payload['analysis_version']:raise AppError('照片已有新修订，旧结果未采用','conflict',409)
                        f=Foods(s);items=[]
                        for it in output['foods']:
                            matched=f.match(it['name']);items.append({**it,'food_id':matched['id'] if matched else None})
                        a=revise(s,a['id'],{'version':a['version'],'items':items,
                            'uncertainty':output['uncertainty'],'meta':meta},model_result=True)
                        result={'analysis_id':a['id']}
                    else:
                        choices=payload['candidates']
                        if any(x not in {c['id'] for c in choices} for x in output['recipe_ids']):
                            raise AppError('模型返回未经安全核对的食谱，结果未采用','safety',422)
                        # Refuse an answer computed against records that changed during inference.
                        from app.backend.ai.tasks import context
                        if context(s,payload['context']['range'][-1])!=payload['context']:
                            raise AppError('饮食记录已更新，请重新提问','conflict',409)
                        nut=payload['context']['today_nutrition']['protein'];target=targets(p)['protein']
                        note=f"今天已记录蛋白质估算 {nut['known']}g。" if nut['known'] is not None else '今天尚没有可计算的蛋白质记录。'
                        note+=(f'档案参考 {target}g。' if target else '参考目标待确认。')+'未记录不等于没有进食；资料不完整时不能判断全天是否足够。'
                        result={'reply':render_reply(output,payload,note),'intent':output['intent'],
                            'steps':output['steps'],'record_note':note,'recipes':[c for c in choices if c['id'] in output['recipe_ids']],
                            'citations':payload['context'],'meta':meta}
                        chat=s.require('chat',payload['chat_id'])
                        s.put('chat',chat['id'],{**chat,'turns':chat['turns']+[{'role':'assistant','content':result['reply'],'result':result}]},version=chat['version'])
                    s.put('task',id,{**current,'status':'succeeded','result':result,'lease_until':None},version=current['version'])
                await self.operation(account,finish)
            except asyncio.CancelledError:
                # Durable lease expires; the owner's next poll can resume the task.
                raise
            except Exception as error:
                def fail(s):
                    current=s.get('task',id)
                    if current and current['status']=='running' and current.get('claim')==claim:
                        message=error.message if isinstance(error,AppError) else '云端分析失败，原输入已保留，请重试'
                        s.put('task',id,{**current,'status':'failed','error':message,'lease_until':None},version=current['version'])
                try:await self.operation(account,fail)
                except Exception:pass  # Revoked/deleted accounts never receive a late write.

    async def close(self):
        self.closed=True
        jobs=list(self.running.values())
        for task in jobs:task.cancel()
        await asyncio.gather(*jobs,return_exceptions=True)
