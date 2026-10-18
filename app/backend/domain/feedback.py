"""Version-bound deterministic next-day adjustments. Never trains a model."""
from datetime import date,timedelta
import hashlib
from typing import Literal
from pydantic import BaseModel,Field,model_validator,ConfigDict,ValidationError
from app.backend.errors import AppError,conflict
from app.backend.storage.database import encode
from .food import day,Foods,NUTRIENTS
from .plans import generate,profile_gate
from .records import summary
from app.backend.ai.safety import immediate

class Feedback(BaseModel):
    model_config=ConfigDict(extra='forbid')
    adherence:Literal['未填','基本按照','部分按照','没有按照']='未填'
    hunger:Literal['未填','合适','经常饿','过饱']='未填'
    taste:Literal['未填','合适','偏淡','偏咸','不喜欢']='未填'
    difficulty:Literal['未填','容易','准备费时','购买不便']='未填'
    discomfort_status:Literal['未填','无','有']='未填'
    symptoms:list[str]=Field(default_factory=list,max_length=15)
    energy:Literal['未填','良好','一般','疲劳']='未填'
    binge:bool|None=None
    special:str=Field(default='',max_length=1500)
    temporary_goal:str=Field(default='',max_length=300)
    suspect_food_ids:list[str]=Field(default_factory=list,max_length=20)
    @model_validator(mode='after')
    def consistency(self):
        if self.discomfort_status!='有' and (self.symptoms or self.suspect_food_ids):raise ValueError('无不适或未填时不能同时选择不适症状/待核对食物')
        if any(not isinstance(x,str) or not x.strip() or len(x)>100 for x in self.symptoms):raise ValueError('请核对不适标签')
        return self

def save_feedback(s,d,body):
    d=day(d)
    try:data=Feedback.model_validate({k:v for k,v in body.items() if k not in ['version','request_key']}).model_dump()
    except ValidationError as e:raise AppError('反馈填写不一致：'+e.errors()[0]['msg'],'fields',422) from e
    for id in data['suspect_food_ids']:Foods(s).get(id)
    with s.atomic():
        p=s.require('profile','self');f=s.put('feedback',d,{**data,'profile_version':p['version']},day=d,version=body.get('version',0))
        result=adjust(s,d)
        return {'feedback':f,'adjustment':result,'emergency':immediate('，'.join(data['symptoms'])+'，'+data['special'])}

def signature(s,d):
    p=s.get('profile','self');f=s.get('feedback',d);records=s.list('record',d);l=s.get('life',d)
    start=(date.fromisoformat(d)-timedelta(days=6)).isoformat()
    measurements=[(x['id'],x['version']) for x in s.list('measurement') if start<=x['day']<=d]
    return hashlib.sha256(encode({'p':p['version'] if p else None,'f':f['version'] if f else None,'r':[(x['id'],x['version']) for x in records],'l':l['version'] if l else None,'m':measurements}).encode()).hexdigest()

def adjust(s,d):
    d=day(d);next_day=(date.fromisoformat(d)+timedelta(days=1)).isoformat()
    with s.atomic():
        f=s.get('feedback',d)
        if not f:return None
        sig=signature(s,d);old=s.get('adjustment',d);plan=s.get('plan',next_day)
        if old and old['signature']==sig and old.get('result_plan_version')==(plan['version'] if plan else None):return old
        p=s.require('profile','self');summ=summary(s,d);reasons=[];options={};limitations=[]
        emergency=immediate('，'.join(f['symptoms'])+'，'+f['special'])
        if f['difficulty'] in ['准备费时','购买不便']:options['quick']=True;reasons.append('你反馈准备或购买不方便，优先耗时更短的可行组合')
        if f['hunger']=='经常饿':
            if summ['food_complete'] and len({r['meal'] for r in summ['records']} & {'早餐','午餐','晚餐'})==3 and summ['nutrition']['energy']['complete'] and not p['conditions'] and p.get('physiology')=='普通':
                options['hunger']=True;reasons.append('记录标记完整且至少包含三餐，持续饥饿先尝试在原基础参考上小幅增加分量（最多10%，不累加）')
            else:limitations.append('你反馈经常饿，但饮食记录或健康适用条件不足；请先核对漏餐和餐次安排，未自动增加热量')
        if f['discomfort_status']=='有':
            if f['suspect_food_ids']:options['avoid_foods']=f['suspect_food_ids'];reasons.append('暂避你标注需核对的食物；不据此诊断过敏或确认不适原因')
            else:limitations.append('出现不适但未明确需核对的食物，未推断病因；建议结合进食时间咨询专业人员')
        if f['taste'] in ['偏淡','偏咸','不喜欢']:limitations.append('口味反馈已保留；暂不自动增减盐糖，具体偏好请在档案中修改')
        if f['temporary_goal']:limitations.append('临时目标已保留供参考，涉及目标改变请在档案确认，未据文字直接改动营养限制')
        if f['energy']=='疲劳' or f['binge'] is True:limitations.append('已记录疲劳或暴食感受，先核对休息与漏餐；持续困扰请寻求专业帮助，不据此限制饮食')
        if summ['life'] and summ['life'].get('sleep_hours') is not None and summ['life']['sleep_hours']<6:limitations.append('已记录睡眠偏少，优先关注休息，不据此激进调整能量')
        limitations.append('体重与测量只作趋势参考，不因单日波动调整摄入；未记录的运动或感受不推测')
        blocked=profile_gate(p);before=plan or (generate(s,next_day,preview=True) if not blocked else None)
        proposal=generate(s,next_day,adjustment=options,preview=True) if not blocked else None
        pending=bool(next_day<date.today().isoformat() or blocked or emergency or (plan and (plan.get('manual') or any(m['status']=='recorded' for m in plan['meals']))))
        if next_day<date.today().isoformat():limitations.append('该方案日期已过去，仅提供回顾建议，不自动改写历史计划')
        if blocked:limitations.append(blocked)
        if emergency:limitations.append(emergency)
        if plan and pending and not blocked and not emergency:limitations.append('明日已有手动修改或实际记录，保留原计划；应用调整需要你确认')
        changes=[]
        if before and proposal:
            for b,a in zip(before['meals'],proposal['meals']):
                if b['recommendation']!=a['recommendation']:changes.append({'meal':a['meal'],'before':b['recommendation']['name'] if b['recommendation'] else '无候选','after':a['recommendation']['name'] if a['recommendation'] else '无候选','before_items':b['recommendation']['items'] if b['recommendation'] else [],'after_items':a['recommendation']['items'] if a['recommendation'] else []})
        impact={k:{'before':before['nutrition'][k]['known'] if before else None,'after':proposal['nutrition'][k]['known'] if proposal else None,'delta':round(proposal['nutrition'][k]['total']-before['nutrition'][k]['total'],2) if before and proposal and proposal['nutrition'][k]['total'] is not None and before['nutrition'][k]['total'] is not None else None,'unit':unit} for k,(_,unit) in NUTRIENTS.items()}
        if not pending and proposal:
            proposal['adjustment']={**options,'reason':'；'.join(reasons) or '没有足够依据改变基础安排，保留基础方案'}
            if not plan or changes or plan.get('needs_review'):
                plan=s.put('plan',next_day,proposal,day=next_day,version=plan['version'] if plan else 0)
        result={'signature':sig,'source_date':d,'target_date':next_day,'status':'pending_review' if pending else 'applied' if changes else 'unchanged','reason':'；'.join(reasons) or '没有足够依据改变基础安排，保留基础方案','limitations':limitations,'inputs':{'profile_version':p['version'],'feedback_version':f['version'],'records':len(summ['records']),'food_complete':summ['food_complete'],'life':summ['life'],'measurements':[m for m in s.list('measurement') if (date.fromisoformat(d)-timedelta(days=6)).isoformat()<=m['day']<=d],'execution':[{'meal':m['meal'],'status':m['status']} for m in (s.get('plan',d) or {}).get('meals',[])]},'before':before,'proposal':proposal,'changes':changes,'impact':impact,'result_plan_version':plan['version'] if plan else None,'rule_version':'adjust-1'}
        return s.put('adjustment',d,result,day=d,version=old['version'] if old else 0)

def apply_adjustment(s,d,body):
    with s.atomic():
        a=s.require('adjustment',day(d));p=s.get('plan',a['target_date'])
        if a['version']!=body.get('version') or a['signature']!=signature(s,d) or a['result_plan_version']!=(p['version'] if p else None):raise conflict('调整依据已变化，请刷新预览后再确认')
        if a['target_date']<date.today().isoformat():raise AppError('历史方案只供回顾，不自动改写')
        if profile_gate(s.require('profile','self')) or not a['proposal']:raise AppError('健康条件尚未明确，不能应用此调整')
        if any('120' in x for x in a['limitations']):raise AppError('请先处理紧急健康状况，不应用普通饮食调整')
        if body.get('action')=='restore':data=a['before']
        elif body.get('action')=='apply':data=a['proposal']
        else:raise AppError('请选择应用建议或恢复原方案')
        if not data:raise AppError('没有可恢复的原方案')
        data={**data,'manual':True,'adjustment':{'reason':'你已确认的调整' if body['action']=='apply' else '你已恢复调整前方案'}}
        result=s.put('plan',a['target_date'],data,day=a['target_date'],version=p['version'] if p else 0)
        return s.put('adjustment',d,{**a,'status':'confirmed' if body['action']=='apply' else 'restored','result_plan_version':result['version']},day=d,version=a['version'])

def reconcile(s):
    if not s.get('profile','self'):return
    # Only recompute affected next-day plans, never a cascade or dates already past.
    today=date.today().isoformat()
    for f in s.list('feedback'):
        if (date.fromisoformat(f['day'])+timedelta(days=1)).isoformat()>=today:adjust(s,f['day'])
