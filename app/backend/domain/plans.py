import copy
from datetime import date,timedelta
import hashlib
import json
from pathlib import Path
from app.backend.errors import AppError,conflict
from .food import Foods,aggregate,day,number
from .profile import targets
from .records import save_record,MEALS

RECIPES=json.loads((Path(__file__).resolve().parents[2]/'resources/recipes.json').read_text(encoding='utf-8'))
ALIASES={'大豆':{'大豆','豆'},'牛奶':{'牛奶','奶','乳'},'海鲜':{'海鲜','鱼','贝类','虾','蟹'},'贝类':{'贝类','虾','蟹','海鲜'},'坚果':{'坚果','杏仁','核桃','腰果'},'鸡蛋':{'鸡蛋','蛋'},'小麦':{'小麦','面粉','麸质'},'花生':{'花生'},'芝麻':{'芝麻'},'芒果':{'芒果'}}


def profile_gate(p):
    if not p:return '请先完成个人档案'
    if p['allergy_status']=='未填写':return '请先确认过敏信息；未填写不能当作无过敏'
    if p['health_status']=='未填写':return '请先确认健康状况；未填写不能当作健康'
    text=' '.join(p['conditions'])
    complex_words=['肾','糖尿病','高血糖','术后','肝脏','心血管','甲状腺','其他']
    if p['age']<18 or p.get('physiology')!='普通' or any(x in text for x in complex_words):
        return '当前健康条件需要专业人员确认适用食物与分量；暂不自动生成饮食方案，可继续手动记录和咨询医生'
    if any(x in text for x in ['尿酸','痛风']):return '基础库缺少嘌呤资料，无法核对你的限制；暂不自动安排，请由专业人员确认'
    supported=['高血压','高血脂','脂肪肝','肠胃问题','食物不耐受']
    if any(c not in supported for c in p['conditions']):return '自定义健康状况尚无可靠规则，请先取得专业饮食指导，保留手动记录'
    if any(a not in ALIASES for a in p['allergens']):return '自定义过敏原尚未建立可靠匹配，暂不自动安排，避免漏排风险'
    return None


def food_risks(p,items):
    reasons=[]
    if not p:return ['未建立档案，无法检查个人限制']
    for item in items:
        name=item['name'];tags=set(item.get('allergens',[]))
        if not item.get('ingredients_complete'):reasons.append(name+'：配料不完整，不能确认过敏风险')
        for a in p['allergens']:
            tokens=ALIASES.get(a,{a})
            if tags & tokens or any(t in name for t in tokens):reasons.append(name+'：可能涉及'+a)
        for excluded in p.get('excluded',[])+p.get('intolerances',[])+p.get('restrictions',[]):
            if excluded and excluded in name:reasons.append(name+'：与你填写的限制“'+excluded+'”冲突')
    return list(dict.fromkeys(reasons))


def allowed(p,recipe,items):
    reasons=food_risks(p,items)
    if recipe['method'] in p['excluded_methods']:reasons.append('不接受此烹饪方式')
    if p['methods'] and recipe['method'] not in p['methods']:reasons.append('不在接受的烹饪方式内')
    if p['diet']=='素食' and any(i['category'] in ['meat','fish','seafood'] or i['food_id'] in ['usda-171478','usda-171477','usda-172389','usda-168250','usda-171791','usda-175168','usda-171956','usda-175177','usda-171971'] for i in items):reasons.append('含肉或水产，不符合素食')
    if p['diet']=='清真' and any(i['food_id'] in ['usda-168250','usda-172389','usda-171791','usda-171478','usda-171477'] for i in items):reasons.append('库中肉类无法核实清真来源')
    if p['cooking'] in ['不方便做饭','只能简单加热'] and '即食食品' not in recipe['forms']:reasons.append('当前做饭条件不便执行')
    if p['prep_minutes'] is not None and recipe['minutes']>p['prep_minutes']:reasons.append('超过可用准备时间')
    n=aggregate(items)
    if '高血压' in p['conditions'] and (n['sodium']['total'] is None or n['sodium']['total']>500):reasons.append('钠资料不足或此组合偏高')
    if any(c in p['conditions'] for c in ['高血脂','脂肪肝']) and any(i['food_id'] in ['usda-172389','usda-168250'] for i in items):reasons.append('暂不选红肉组合，优先其他来源')
    if '肠胃问题' in p['conditions'] and recipe['method']=='凉拌':reasons.append('肠胃情况未明确，暂不选择凉拌')
    if p['diet'] not in ['普通饮食','低碳饮食','素食','清真']:reasons.append('自定义饮食类型需先核对')
    return reasons


def candidate(s,p,recipe,factor=1):
    items=Foods(s).calculate([{**x,'grams':round(x['grams']*factor,1)} for x in recipe['items']])
    return {**copy.deepcopy(recipe),'items':items,'nutrition':aggregate(items),'factor':factor,'risk_notes':['营养为估算；购买时仍需核对标签和交叉接触，照片不能排除隐藏配料'],'cost':round(recipe['cost']*factor,1)}


def candidates(s,p,meal,d,energy=None,quick=False,extra_hunger=False,avoid=None,avoid_foods=None):
    selected=[]
    recent={m.get('recipe_id') for plan in s.list('plan') if d-timedelta(days=7)<=date.fromisoformat(plan['day'])<d for m in plan.get('meals',[])}
    for recipe in RECIPES:
        if meal not in recipe['meals'] or recipe['id'] in (avoid or []):continue
        if any(i['food_id'] in (avoid_foods or []) for i in recipe['items']):continue
        base=candidate(s,p,recipe)
        factor=max(.6,min(1.6,energy/base['nutrition']['energy']['known'])) if energy else 1
        # Extra satiety adds 10% to base portions once, not on top of older adjustments.
        if extra_hunger:factor=min(1.6,factor*1.1)
        c=candidate(s,p,recipe,factor)
        if allowed(p,recipe,c['items']):continue
        text=' '.join(i['name'] for i in c['items'])
        score=(15 if recipe['id'] in recent else 0)+int(hashlib.sha256((d.isoformat()+recipe['id']).encode()).hexdigest()[:4],16)%8
        score+=sum(30 for x in p['dislikes'] if x in text)-sum(12 for x in p['likes'] if x in text)
        score-=8 if set(recipe['forms'])&set(p['forms']) else 0
        score-=5 if recipe['taste'] in p['tastes'] else 0
        score+=recipe['minutes']*(2 if quick else .1)
        if p['budget']:score+=max(0,c['cost']-p['budget']*.3)*2
        if p['primary_goal'] in ['补充蛋白质','增肌','健身训练']:score-=(c['nutrition']['protein']['known'] or 0)*.3
        if p['diet']=='低碳饮食':score+=(c['nutrition']['carbs']['known'] or 0)*.1
        c['score']=round(score,2);selected.append(c)
    return sorted(selected,key=lambda c:c['score'])


def generate(s,d,version=None,adjustment=None,*,preview=False):
    d=day(d);p=s.require('profile','self');blocked=profile_gate(p)
    if blocked:raise AppError(blocked,'health_review',422)
    old=s.get('plan',d)
    if version is not None and (old['version'] if old else 0)!=version:raise conflict()
    t=targets(p);ratios=[.25,.35,.30,.10];meals=[]
    adjustment=adjustment or {}
    for i,meal in enumerate(MEALS):
        prior=next((m for m in (old or {}).get('meals',[]) if m['meal']==meal),None)
        if prior and prior['status']=='recorded':meals.append(prior);continue
        energy=t['energy']*ratios[i] if t['energy'] else None
        cs=candidates(s,p,meal,date.fromisoformat(d),energy,quick=adjustment.get('quick',False),extra_hunger=adjustment.get('hunger',False),avoid=adjustment.get('avoid',[]),avoid_foods=adjustment.get('avoid_foods',[]))
        reason=f"优先核对过敏与健康限制；主要目标：{p['primary_goal']}。准备上限：{p['prep_minutes'] if p['prep_minutes'] is not None else '未设置'}分钟；预算：{p['budget'] or '未设置'}元/天。按口味、食物形态、成本与近期多样性排序。"
        if not cs:
            meals.append({'id':str(i),'meal':meal,'status':'pending','recipe_id':None,'recommendation':None,'alternatives':[],'shortage':'当前资料与限制下没有可验证候选，请手动记录或调整实际条件，不降低过敏限制','reason':reason,'record_ids':[]});continue
        meals.append({'id':str(i),'meal':meal,'status':'pending','recipe_id':cs[0]['id'],'recommendation':cs[0],'alternatives':cs[1:3], 'shortage':'' if len(cs)>=3 else '符合限制的替代不足两种，未强行凑数','reason':reason,'record_ids':[]})
    data={'meals':meals,'profile_version':p['version'],'rule_version':'nutrition-1','needs_review':False,'targets':t,'manual':False,'adjustment':adjustment,'nutrition':aggregate([it for m in meals if m['recommendation'] for it in m['recommendation']['items']])}
    if preview:return data
    return s.put('plan',d,data,day=d,version=old['version'] if old else 0)


def change(s,d,meal_id,body):
    with s.atomic():
        plan=s.require('plan',day(d));p=s.require('profile','self')
        if plan['version']!=body.get('version'):raise conflict()
        meal=next((m for m in plan['meals'] if m['id']==meal_id),None)
        if not meal:raise AppError('餐次不存在','not_found',404)
        action=body.get('action')
        if action=='confirm' and meal['record_ids']:
            return {'plan':plan,'record':s.require('record',meal['record_ids'][0])}
        if meal['status']=='recorded':raise AppError('已食用内容请到饮食记录中修改，计划不会改写实际摄入','conflict',409)
        if action in ['confirm','replace','portion'] and (plan.get('needs_review') or plan['profile_version']!=p['version']):raise AppError('档案已变化，请重新生成未执行计划后再操作','conflict',409)
        if action in ['skip','resume']:
            meal['status']='skipped' if action=='skip' else 'pending'
            plan['manual']=True
        elif action in ['portion','replace','confirm']:
            if profile_gate(p):raise AppError(profile_gate(p),'health_review',422)
            rec=meal['recommendation']
            if not rec:raise AppError('此餐没有可执行推荐，请手动记餐')
            if action=='replace':
                recipe=next((r for r in RECIPES if r['id']==body.get('recipe_id') and meal['meal'] in r['meals']),None)
                if not recipe:raise AppError('请选择有效的替代餐食')
                rec=candidate(s,p,recipe,rec['factor'])
            elif action=='portion':
                recipe=next(r for r in RECIPES if r['id']==rec['id'])
                rec=candidate(s,p,recipe,number(body.get('factor'),.25,2,'分量倍数'))
            actual=Foods(s).calculate(body.get('items')) if action=='confirm' else rec['items']
            errors=allowed(p,rec,actual)
            if errors:raise AppError('；'.join(errors),'health_review',422)
            if action=='confirm':
                r=save_record(s,{'date':d,'meal':meal['meal'],'time':body.get('time'),'items':[{'food_id':it['food_id'],'grams':it['grams']} for it in actual],'source':'plan','plan_id':d,'meal_id':meal_id,'satiety':body.get('satiety'),'liking':body.get('liking')})
                meal['record_ids'].append(r['id']);meal['status']='recorded'
                s.conn.execute('INSERT INTO links VALUES (?,?,?,?)',('plan',d,'record',r['id']))
            else:
                meal['recommendation']=rec;meal['recipe_id']=rec['id'];plan['manual']=True
                choices=[c for c in candidates(s,p,meal['meal'],date.fromisoformat(d),energy=rec['nutrition']['energy']['known']) if c['id']!=rec['id']]
                meal['alternatives']=choices[:2]
                meal['shortage']='' if len(choices)>=2 else '符合限制的替代不足两种，未强行凑数'
        else:raise AppError('不支持此操作')
        plan['nutrition']=aggregate([it for m in plan['meals'] if m['recommendation'] for it in m['recommendation']['items']])
        updated=s.put('plan',d,plan,day=d,version=plan['version'])
        return {'plan':updated,'record':r if action=='confirm' else None}
