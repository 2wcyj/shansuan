import pytest
from concurrent.futures import ThreadPoolExecutor
from app.backend.storage.database import Store
from app.backend.domain.profile import save_profile
from app.backend.domain.plans import generate,change,allowed,profile_gate,RECIPES
from app.backend.domain.records import summary,delete_record,save_record
from app.backend.errors import AppError
from app.tests.helpers import profile
def setup(tmp_path,**p):
    s=Store(tmp_path);save_profile(s,profile(**p));return s
def test_plans_and_alternatives_obey_hard_filters(tmp_path):
    s=setup(tmp_path,allergy_status='有',allergens=['花生','牛奶','鸡蛋','大豆'],methods=['蒸','煮'],prep_minutes=20,forms=['家庭烹饪'])
    p=s.require('profile','self');plan=generate(s,'2026-10-17')
    assert len(plan['meals'])==4
    for meal in plan['meals']:
        for rec in ([meal['recommendation']] if meal['recommendation'] else [])+meal['alternatives']:
            assert not allowed(p,rec,rec['items'])
            assert not any(a in ['花生','牛奶','鸡蛋','豆'] for i in rec['items'] for a in i['allergens'])
            assert rec['minutes']<=20
        assert len(meal['alternatives'])>=2 or meal['shortage']
    assert summary(s,'2026-10-17')['record_count']==0
    s.close()
def test_confirm_idempotency_skip_replacement_and_history(tmp_path):
    s=setup(tmp_path);plan=generate(s,'2026-10-17');m=plan['meals'][0]
    data={'version':plan['version'],'action':'confirm','items':m['recommendation']['items'],'time':'08:00'}
    def confirm(_):return s.mutate('confirm-meal-key',data,lambda:change(s,plan['day'],m['id'],data))
    with ThreadPoolExecutor(max_workers=5) as pool:results=list(pool.map(confirm,range(10)))
    assert len(s.list('record'))==1 and all(r==results[0] for r in results)
    p=results[0]['plan'];assert p['meals'][0]['status']=='recorded'
    oldrecord=s.list('record')[0];p=generate(s,plan['day'],p['version'])
    assert p['meals'][0]['record_ids']==[oldrecord['id']]
    res=change(s,p['day'],'1',{'version':p['version'],'action':'skip'})
    assert len(s.list('record'))==1
    save_record(s,{'date':p['day'],'meal':'午餐','time':'12:00','items':[{'food_id':'usda-168878','grams':100}]})
    assert len(s.list('record'))==2
    delete_record(s,oldrecord['id'],oldrecord['version']);assert s.require('plan',p['day'])['meals'][0]['status']=='pending'
    s.close()
def test_profile_change_blocks_stale_plan_and_preserves_actual(tmp_path):
    s=setup(tmp_path);p=generate(s,'2026-10-17');m=p['meals'][0]
    r=save_record(s,{'date':p['day'],'meal':'早餐','time':'08:00','items':m['recommendation']['items']})
    save_profile(s,{**profile(allergy_status='有',allergens=['鸡蛋']),'version':1})
    p=s.require('plan',p['day']);assert p['needs_review']
    with pytest.raises(AppError):change(s,p['day'],'1',{'version':p['version'],'action':'confirm','items':p['meals'][1]['recommendation']['items'],'time':'12:00'})
    assert s.require('record',r['id'])['items']==r['items']
    s.close()
def test_special_conditions_and_unknown_allergens_never_silently_bypass():
    for p in [profile(allergy_status='未填写'),profile(allergy_status='有',allergens=['未知自定义']),profile(health_status='有',conditions=['肾脏问题']),profile(health_status='有',conditions=['高尿酸或痛风'])]:
        assert profile_gate(p)

def test_replacement_updates_alternatives_and_simple_heating_is_respected(tmp_path):
    s=setup(tmp_path);plan=generate(s,'2026-10-17');m=plan['meals'][0]
    replacement=m['alternatives'][0];updated=change(s,plan['day'],m['id'],{'version':plan['version'],'action':'replace','recipe_id':replacement['id']})['plan'];meal=updated['meals'][0]
    assert all(x['id']!=replacement['id'] for x in meal['alternatives'])
    assert len(meal['alternatives'])>=2 or meal['shortage'];s.close()
    s=setup(tmp_path/'heat-only',cooking='只能简单加热');p=generate(s,'2026-10-17')
    for m in p['meals']:
        for c in ([m['recommendation']] if m['recommendation'] else [])+m['alternatives']:assert '即食食品' in c['forms']
    s.close()

def test_stew_only_profile_has_recommendations_and_alternatives_for_main_meals(tmp_path):
    s=setup(tmp_path,methods=['炖'])
    plan=generate(s,'2026-10-17');meals={m['meal']:m for m in plan['meals']}
    for name in ['早餐','午餐','晚餐']:
        assert meals[name]['recommendation']
        assert meals[name]['recommendation']['method']=='炖'
        assert len(meals[name]['alternatives'])>=2
        assert all(option['method']=='炖' for option in meals[name]['alternatives'])
    s.close()
