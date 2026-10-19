from datetime import datetime
import uuid
from app.backend.errors import AppError
from .food import Foods,aggregate,day,number

MEALS=['早餐','午餐','晚餐','加餐']


def save_record(s,body,id=None):
    old=s.get('record',id) if id else None
    if old and old.get('source')=='product':
        from .products import revise_record
        return revise_record(s,old,body)
    d=day(body.get('date')); meal=body.get('meal')
    if meal not in MEALS:raise AppError('请选择早餐、午餐、晚餐或加餐')
    try:datetime.strptime(body.get('time',''),'%H:%M')
    except (TypeError,ValueError):raise AppError('请填写有效用餐时间')
    items=Foods(s).calculate(body.get('items'))
    for key in ['satiety','liking']:
        if body.get(key) is not None:number(body[key],1,5,key)
    for item,raw in zip(items,body['items']):item['ingredients']=[str(x)[:100] for x in raw.get('ingredients',[])][:20]
    notes=str(body.get('discomfort',''))[:1500]
    source=body.get('source','manual')
    if source not in ['manual','plan','photo']:raise AppError('无效的记录来源')
    old=s.get('record',id) if id else None
    if old:
        source=old['source']
        if old.get('plan_id') and (d!=old['day'] or meal!=old['meal']):raise AppError('计划关联记录请保持原日期和餐次；若记错，请删除后重新记录')
        if [(x['food_id'],x['grams']) for x in items]==[(x['food_id'],x['grams']) for x in old['items']]:items=old['items']
    data={k:body.get(k) for k in ['time','satiety','liking']}
    data.update(meal=meal,items=items,nutrition=aggregate(items),source=source,discomfort=notes,
                plan_id=old.get('plan_id') if old else body.get('plan_id'),meal_id=old.get('meal_id') if old else body.get('meal_id'),analysis_id=old.get('analysis_id') if old else body.get('analysis_id'))
    return s.put('record',id or uuid.uuid4().hex,data,day=d,version=body.get('version',0))


def delete_record(s,id,version):
    with s.atomic():
        old=s.require('record',id)
        result=s.delete('record',id,version)
        if old.get('plan_id'):
            plan=s.get('plan',old['plan_id'])
            if plan:
                for m in plan['meals']:
                    if m['id']==old['meal_id']:
                        m['record_ids']=[r['id'] for r in s.list('record',old['day']) if r.get('plan_id')==plan['id'] and r.get('meal_id')==m['id']]
                        m['status']='recorded' if m['record_ids'] else 'pending'
                s.put('plan',plan['id'],plan,day=plan['day'],version=plan['version'])
        if old.get('analysis_id'):
            a=s.get('analysis',old['analysis_id'])
            if a:s.put('analysis',a['id'],{**a,'record_id':None,'status':'revised'},version=a['version'])
        if old.get('product_plan_id'):
            p=s.get('product_plan',old['product_plan_id'])
            if p:s.put('product_plan',p['id'],{**p,'status':'pending','record_id':None},day=p['day'],version=p['version'])
        return result


def life(s,body):
    d=day(body.get('date'))
    data={}
    ranges={'water_ml':(0,12000),'sleep_hours':(0,24),'exercise_minutes':(0,1440),'weight':(10,350),'waist':(20,250),'body_fat':(2,70)}
    for key,(low,high) in ranges.items():
        data[key]=None if body.get(key) is None else number(body[key],low,high,key)
    data['feeling']=str(body.get('feeling',''))[:1500]
    data['food_complete']=body.get('food_complete') is True
    with s.atomic():
        result=s.put('life',d,data,day=d,version=body.get('version',0))
        for key in ['weight','waist','body_fat']:
            if data[key] is not None:
                id=d+'-'+key;old=s.get('measurement',id)
                s.put('measurement',id,{'metric':key,'value':data[key],'source':'life'},day=d,version=old['version'] if old else 0)
            else:
                id=d+'-'+key;old=s.get('measurement',id)
                if old and old.get('source')=='life':s.delete('measurement',id,old['version'])
        return result


def drink(s,body):
    d=day(body.get('date'));amount=number(body.get('amount',200),1,2000,'单次饮水量')
    with s.atomic():
        old=s.get('life',d)
        value=(old or {}).get('water_ml') or 0
        if value+amount>12000:raise AppError('当日饮水记录超过上限，请核对单位')
        data={**(old or {}),'water_ml':value+amount}
        return s.put('life',d,data,day=d,version=old['version'] if old else 0)


def summary(s,d):
    d=day(d);records=s.list('record',d);l=s.get('life',d)
    return {'date':d,'records':records,'nutrition':aggregate([i for r in records for i in r['items']]),'life':l,'record_count':len(records),'food_complete':bool(l and l.get('food_complete')),'coverage':'没有饮食记录' if not records else '用户确认当日记录完整' if l and l.get('food_complete') else '仅代表已记录部分，未确认完整'}
