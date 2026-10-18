from concurrent.futures import ThreadPoolExecutor
import pytest
from app.backend.storage.database import Store
from app.backend.domain.food import Foods,aggregate
from app.backend.domain.records import save_record,summary,delete_record,drink,life
from app.backend.errors import AppError

def body(date='2026-10-16'):return dict(date=date,meal='午餐',time='12:30',items=[{'food_id':'usda-168878','grams':200}])
def test_scaled_snapshot_unknown_and_food_rematch(tmp_path):
    s=Store(tmp_path);f=Foods(s)
    rice=f.calculate([{'food_id':'usda-168878','grams':200}])[0]
    egg=f.calculate([{'food_id':'usda-173424','grams':200}])[0]
    assert rice['nutrients']['energy']==260 and egg['nutrients']['protein']!=rice['nutrients']['protein']
    n=aggregate([rice]);assert n['purine']['known'] is None and not n['purine']['complete']
    custom=f.custom({'name':'标签缺少部分数据','nutrients':{'energy':100,'sugar':0}})
    mixed=aggregate(f.calculate([{'food_id':custom['id'],'grams':100},{'food_id':'usda-168878','grams':100}]))
    assert mixed['protein']['unknown']==1 and mixed['protein']['known']==2.69 and mixed['protein']['total'] is None
    assert f.calculate([{'food_id':custom['id'],'grams':100}])[0]['nutrients']['sugar']==0
    r=save_record(s,{**body(),'items':[{'food_id':custom['id'],'grams':100}]})
    f.custom({'name':'新标签','nutrients':{'energy':999},'version':1},custom['id'])
    assert s.require('record',r['id'])['nutrition']['energy']['total']==100
    s.close()
def test_record_date_edit_delete_and_transactional_idempotency(tmp_path):
    s=Store(tmp_path)
    r=s.mutate('add-record-key',body(),lambda:save_record(s,body()))
    assert s.mutate('add-record-key',body(),lambda:save_record(s,body()))==r
    assert summary(s,'2026-10-17')['record_count']==0
    edited=save_record(s,{**body(),'version':r['version'],'items':[{'food_id':'usda-173424','grams':100}]},r['id'])
    assert summary(s,'2026-10-16')['nutrition']['energy']['total']==edited['nutrition']['energy']['total']
    with pytest.raises(AppError):save_record(s,{**body(),'version':1},r['id'])
    delete_record(s,r['id'],edited['version']);assert summary(s,'2026-10-16')['nutrition']['energy']['known'] is None
    s.close()
def test_atomic_water_and_unknown_life(tmp_path):
    s=Store(tmp_path)
    def add(i):return s.mutate('water-key-'+str(i),{'i':i},lambda:drink(s,{'date':'2026-10-16','amount':200}))
    with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(add,range(20)))
    assert s.require('life','2026-10-16')['water_ml']==4000
    assert s.require('life','2026-10-16').get('sleep_hours') is None
    l=life(s,{'date':'2026-10-17','sleep_hours':0,'weight':60,'food_complete':True})
    assert l['sleep_hours']==0 and l['water_ml'] is None
    assert s.list('measurement')[0]['day']=='2026-10-17'
    s.close()
