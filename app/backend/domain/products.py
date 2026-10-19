"""Private catalog. Illustration values are deliberately outside usable labels."""
import uuid
from datetime import datetime
from app.backend.errors import AppError,conflict
from .food import NUTRIENTS,number,day,aggregate
from .records import MEALS
from .plans import ALIASES

CORE=['energy','protein','fat','carbs','sodium']

def seed(s):
    with s.atomic():
        if s.get('catalog_meta','seed-v1'):return
        entries=[('干素肉','透明罐装；图示称植物蛋白制品、开罐即食'),('素肉片','自立拉链袋；图示120g，提及大豆蛋白'),('小分子肽口服液','图示30mL礼盒，10mL×3瓶；配方、资质及适用人群未核实'),('低脂蛋白棒','图示300g盒装、5袋装'),('健身蛋白粉','图示35g独立包装，坚果谷物型复合植物蛋白粉'),('多源植物蛋白零食系列礼盒','植物蛋白零食组合方案；数量与内容未核实')]
        for i,(name,note) in enumerate(entries):
            illustration={'note':note,'status':'计划书示意，待核实'}
            if i==3:illustration['nutrients']={'energy_kj':1780,'protein':18.5,'fat':6.2,'carbs':60.1,'fiber':8.3,'sodium':120,'basis':'每100g，计划书示意，待核实'}
            save_product(s,{'name':name,'brand':'千人千植','category':'概念产品','verification':'概念方案','source':'“天食杯”第七届食品研究与开发创新创意大赛计划书带图版','illustration':illustration},'seed-'+str(i+1))
        s.put('catalog_meta','seed-v1',{'done':True})

def save_product(s,body,id=None):
    name=str(body.get('name','')).strip()
    if not name or len(name)>100:raise AppError('请填写100字以内商品名称')
    data={'name':name}
    for k in ['brand','category','description','flavor','packaging','net_content','specification','ingredients','cross_contact','instructions','storage','shelf_life','source','verifier','verified_date','purchase','contact']:
        v=body.get(k,'')
        if not isinstance(v,str) or len(v)>4000:raise AppError('请检查商品文字资料')
        data[k]=v.strip()
    for k in ['allergens','forms','tastes','diet_types']:
        v=body.get(k,[])
        if not isinstance(v,list) or len(v)>50 or any(not isinstance(x,str) or not x.strip() or len(x)>100 for x in v):raise AppError('请检查商品标签')
        data[k]=v
    data['unit']=body.get('unit','g')
    if data['unit'] not in ['g','mL']:raise AppError('请选择g或mL口径')
    data['nutrients']={}
    for field in ['nutrients','serving_nutrients']:
        raw=body.get(field,{})
        if not isinstance(raw,dict):raise AppError('营养标签格式错误')
        data[field]={k:None if raw.get(k) is None else number(raw[k],0,100000,k) for k in NUTRIENTS}
    data['serving_amount']=None if body.get('serving_amount') is None else number(body['serving_amount'],.1,5000,'每份分量')
    data['price']=None if body.get('price') is None else number(body['price'],0,100000,'价格')
    data['verification']=body.get('verification','待补资料')
    if data['verification'] not in ['概念方案','待补资料','待核实','已核实']:raise AppError('无效核实状态')
    data['sale_status']=body.get('sale_status','未确认')
    if data['sale_status'] not in ['未确认','在售','停售']:raise AppError('无效销售状态')
    data.update(allergens_confirmed=body.get('allergens_confirmed') is True,hidden=body.get('hidden') is True,archived=body.get('archived') is True)
    data['illustration']=body.get('illustration',{})
    if not isinstance(data['illustration'],dict):raise AppError('示意资料格式错误')
    if data['verification']=='已核实':
        if any(not data[k] for k in ['ingredients','cross_contact','source','verifier','verified_date']) or not data['allergens_confirmed'] or any(data['nutrients'][k] is None for k in CORE):raise AppError('核实前请补全正式配料、过敏与交叉接触声明、核心营养、来源、核实人与日期')
        day(data['verified_date'])
        if data['verified_date']>datetime.now().date().isoformat():raise AppError('核实日期不能晚于今天')
    with s.atomic():
        return s.put('product',id or uuid.uuid4().hex,data,version=body.get('version',0))

def match(s,p):
    profile=s.get('profile','self');reasons=[];score=0
    text=' '.join([p.get('ingredients',''),p.get('cross_contact',''),*p.get('allergens',[])])
    if profile:
        for a in profile['allergens']:
            if any(t.casefold() in text.casefold() for t in ALIASES.get(a,{a})):reasons.append('过敏风险冲突：'+a)
        for a in profile.get('excluded',[])+profile.get('intolerances',[])+profile.get('restrictions',[]):
            if a.casefold() in text.casefold():reasons.append('不接受成分冲突：'+a)
    if p['verification']!='已核实' or not p['ingredients'] or not p['allergens_confirmed'] or not p['cross_contact'] or any(p['nutrients'].get(k) is None for k in CORE):reasons.append('信息待核实，不能判断是否适合你')
    if not profile:reasons.append('请先完成个人档案')
    elif profile['health_status']!='明确无' or profile['conditions'] or profile.get('physiology')!='普通' or not 18<=profile['age']<=75:reasons.append('健康情况需要咨询专业人士；不提供医学适用性结论')
    if profile and (profile['allergy_status']=='未填写' or any(a not in ALIASES for a in profile['allergens'])):reasons.append('过敏信息待专业核对')
    if profile and profile.get('diet','普通饮食')!='普通饮食' and profile['diet'] not in p.get('diet_types',[]):reasons.append('未核实是否符合你的饮食类型')
    if p['hidden'] or p['archived'] or p['sale_status']=='停售':reasons.append('商品已隐藏、归档或停售')
    eligible=not reasons
    if eligible:
        reasons=['已核实完整配料与过敏声明；购买时仍需核对最新标签与交叉接触','依据：'+p['source']+'；核实人：'+p['verifier']+'；'+p['verified_date']]
        if profile['primary_goal'] in ['补充蛋白质','增肌','健身训练']:
            reasons.append(f"你的主要目标为{profile['primary_goal']}；正式标签蛋白质 {p['nutrients']['protein']}g/100{p['unit']}，请结合食用分量");score+=p['nutrients']['protein']
        if set(profile.get('forms',[]))&set(p['forms']):reasons.append('食物形态与你的偏好一致');score+=5
        if set(profile.get('tastes',[]))&set(p['tastes']):reasons.append('口味与你的偏好一致');score+=3
    return {'eligible':eligible,'reasons':reasons,'score':score,'commercial':'自有产品推荐 · 推广内容','alternatives':['可查看原有今日饮食中的普通食物方案，继续遵守档案限制','可选择非自有品牌食品，先核对完整配料、过敏声明和标签；必要时请专业人员协助']}

def settings(s,body=None):
    old=s.get('catalog_settings','self')
    if body is None:return old or {'enabled':False,'version':0}
    return s.put('catalog_settings','self',{'enabled':body.get('enabled') is True},version=body.get('version',0))

def checked(s,id,body):
    p=s.require('product',id)
    if p['version']!=body.get('version'):raise conflict('商品资料已变化，请重新查看并确认')
    m=match(s,p)
    if not m['eligible']:raise AppError('；'.join(m['reasons']))
    d=day(body.get('date'));meal=body.get('meal')
    if meal not in MEALS:raise AppError('请选择餐次')
    amount=number(body.get('amount'),.1,5000,'实际/计划分量')
    return p,d,meal,amount

def add_plan(s,id,body):
    with s.atomic():
        p,d,meal,amount=checked(s,id,body)
        return s.put('product_plan',uuid.uuid4().hex,{'product_id':id,'product_version':p['version'],'product_snapshot':p,'meal':meal,'amount':amount,'unit':p['unit'],'status':'pending'},day=d)

def product_item(p,amount):
    return {'food_id':'product-'+p['id'],'name':p['name'],'grams':amount,'amount':amount,'unit':p['unit'],'state':'正式标签计算（估算）','source':{'name':p['source']},'category':'product','allergens':p['allergens'],'ingredients_complete':True,'product_snapshot':p,'nutrients':{k:None if v is None else round(v*amount/100,4) for k,v in p['nutrients'].items()}}

def consume(s,id,body):
    with s.atomic():
        p,d,meal,amount=checked(s,id,body)
        if body.get('confirmed') is not True:raise AppError('请明确确认实际已经食用并核对分量','confirmation',422)
        try:datetime.strptime(body.get('time',''),'%H:%M')
        except (TypeError,ValueError):raise AppError('请填写有效用餐时间')
        plan=None
        if body.get('plan_id'):
            plan=s.require('product_plan',body['plan_id'])
            if plan['version']!=body.get('plan_version') or plan['status']!='pending' or plan['product_id']!=id or plan['day']!=d or plan['meal']!=meal:raise conflict('计划已变化或已记录，请刷新核对')
        item=product_item(p,amount)
        r=s.put('record',uuid.uuid4().hex,{'time':body['time'],'meal':meal,'items':[item],'nutrition':aggregate([item]),'source':'product','product_id':id,'product_plan_id':plan['id'] if plan else None,'plan_id':None,'meal_id':None,'analysis_id':None,'satiety':None,'liking':None,'discomfort':''},day=d)
        if plan:s.put('product_plan',plan['id'],{**plan,'status':'recorded','record_id':r['id']},day=d,version=plan['version'])
        return r

def revise_record(s,old,body):
    """Edits keep the historical verified label, never mutable catalog numbers."""
    if body.get('date')!=old['day'] or body.get('meal')!=old['meal']:raise AppError('产品记录请保持原日期和餐次；记错可删除后重新确认')
    try:datetime.strptime(body.get('time',''),'%H:%M')
    except (TypeError,ValueError):raise AppError('请填写有效用餐时间')
    items=body.get('items',[])
    if len(items)!=1 or items[0].get('food_id')!=old['items'][0]['food_id']:raise AppError('产品记录不能更换食品，请删除后重新确认')
    amount=number(items[0].get('grams'),.1,5000,'食用分量')
    item=product_item(old['items'][0]['product_snapshot'],amount)
    for key in ['satiety','liking']:
        if body.get(key) is not None:number(body[key],1,5,key)
    return s.put('record',old['id'],{**old,'items':[item],'nutrition':aggregate([item]),'time':body['time'],'satiety':body.get('satiety'),'liking':body.get('liking'),'discomfort':str(body.get('discomfort',''))[:1500]},day=old['day'],version=body.get('version',0))
