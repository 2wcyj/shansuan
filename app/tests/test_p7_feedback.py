from datetime import date,timedelta
import pytest
from app.backend.storage.database import Store
from app.backend.domain.profile import save_profile
from app.backend.domain.food import Foods
from app.backend.domain.records import save_record,life,summary,delete_record
from app.backend.domain.plans import generate,change
from app.backend.domain.feedback import save_feedback,adjust,apply_adjustment,reconcile
from app.backend.domain.reports import report
from app.backend.errors import AppError
from app.tests.helpers import profile

def setup(tmp_path,**kwargs):
    s=Store(tmp_path);save_profile(s,profile(**kwargs));return s

def test_feedback_validation_persistence_and_no_inferred_state(tmp_path):
    s=setup(tmp_path);d=date.today().isoformat()
    with pytest.raises(AppError):save_feedback(s,d,{'discomfort_status':'无','symptoms':['胃胀']})
    with pytest.raises(AppError):save_feedback(s,d,{'hunger':'不存在'})
    r=save_feedback(s,d,{});assert r['feedback']['hunger']=='未填';assert r['adjustment']['status']=='unchanged'
    assert not s.list('record');s.close();s=Store(tmp_path);assert s.require('feedback',d)['hunger']=='未填';s.close()

def test_adjustment_quick_hunger_idempotent_and_manual_conflict(tmp_path):
    s=setup(tmp_path);d=date.today().isoformat();n=(date.today()+timedelta(days=1)).isoformat();p=generate(s,d)
    for m in p['meals'][:3]:
        save_record(s,{'date':d,'time':'12:00','meal':m['meal'],'items':m['recommendation']['items']})
    life(s,{'date':d,'food_complete':True,'sleep_hours':5,'weight':60})
    base=generate(s,n);r=save_feedback(s,d,{'hunger':'经常饿','difficulty':'准备费时'});a=r['adjustment'];assert a['status']=='applied'
    assert a['proposal']['adjustment']=={} or a['proposal']['adjustment'].get('hunger')
    assert '10%' in a['reason'] and a['changes'];assert a['impact']['protein']['delta'] is not None
    after=s.require('plan',n);assert adjust(s,d)['version']==a['version'];reconcile(s);assert s.require('plan',n)==after
    assert len(s.list('record'))==3
    # Manual change is never silently overwritten after revised source feedback.
    m=after['meals'][1];edited=change(s,n,m['id'],{'version':after['version'],'action':'portion','factor':.8})['plan']
    r=save_feedback(s,d,{'version':1,'hunger':'合适','difficulty':'容易'});a=r['adjustment'];assert a['status']=='pending_review';assert s.require('plan',n)==edited
    a=apply_adjustment(s,d,{'version':a['version'],'action':'apply'});assert a['status']=='confirmed'
    a=apply_adjustment(s,d,{'version':a['version'],'action':'restore'});assert a['status']=='restored'
    assert s.require('plan',n)['meals']==edited['meals'];s.close()

def test_insufficient_records_weight_and_discomfort_do_not_drive_unsafe_changes(tmp_path):
    s=setup(tmp_path);d=date.today().isoformat();n=(date.today()+timedelta(days=1)).isoformat()
    base=generate(s,n);life(s,{'date':d,'weight':70})
    r=save_feedback(s,d,{'hunger':'经常饿'});assert not r['adjustment']['proposal']['adjustment'].get('hunger');assert '未自动增加' in ' '.join(r['adjustment']['limitations'])
    f=Foods(s).all()[0];r=save_feedback(s,d,{'version':1,'discomfort_status':'有','symptoms':['胃胀'],'suspect_food_ids':[f['id']]})
    for m in s.require('plan',n)['meals']:
        if m['recommendation']:assert f['id'] not in [i['food_id'] for i in m['recommendation']['items']]
    before=s.require('plan',n);r=save_feedback(s,d,{'version':2,'discomfort_status':'有','symptoms':['胸痛']});assert '120' in r['emergency'];assert r['adjustment']['status']=='pending_review';assert s.require('plan',n)==before
    with pytest.raises(AppError):apply_adjustment(s,d,{'version':r['adjustment']['version'],'action':'apply'})
    s.close()

def test_seven_days_gaps_coverage_mean_and_edit_recalculation(tmp_path):
    s=setup(tmp_path);end=date.today();start=end-timedelta(days=6);food=Foods(s).all()[0];records=[]
    for i in [0,1,3,4,6]:
        d=(start+timedelta(days=i)).isoformat();r=save_record(s,{'date':d,'meal':'早餐','time':'08:00','items':[{'food_id':food['id'],'grams':100+i*10}]});records.append(r)
        life(s,{'date':d,'food_complete':True,'water_ml':0 if i==0 else 1000,'sleep_hours':7,'weight':60+i*.1})
        if i in [0,6]:generate(s,d)
    custom=Foods(s).custom({'name':'测试未知营养标签','nutrients':{'protein':5},'ingredients_complete':True})
    r=records[1];save_record(s,{'version':r['version'],'date':r['day'],'meal':r['meal'],'time':r['time'],'items':[{'food_id':custom['id'],'grams':100}]},r['id'])
    result=report(s,end.isoformat());assert len(result['days'])==7 and result['start']==start.isoformat()
    assert result['days'][2]['nutrition']['energy']['known'] is None and result['days'][2]['vegetables_g'] is None
    assert result['days'][-1]['in_progress'] and result['means']['energy']['days']==3
    assert result['days'][1]['nutrition']['energy']['known'] is None and result['days'][1]['nutrition']['protein']['known']==5
    assert result['execution']['total']==3 and result['execution']['done']==0
    assert result['life']['water_ml']['mean']==800 and result['weight']['delta']==.6
    before=result['means']['protein']['value'];r=records[0];save_record(s,{'version':r['version'],'date':r['day'],'meal':r['meal'],'time':r['time'],'items':[{'food_id':food['id'],'grams':200}]},r['id']);assert report(s,end.isoformat())['means']['protein']['value']!=before
    old=records[2];delete_record(s,old['id'],old['version']);assert report(s,end.isoformat())['recorded_days']==4
    assert report(s,(end-timedelta(days=30)).isoformat())['weight']['delta'] is None;s.close()

def test_changed_sources_reconcile_stale_and_special_conditions(tmp_path):
    s=setup(tmp_path);d=date.today().isoformat();a=save_feedback(s,d,{'difficulty':'准备费时'})['adjustment']
    f=Foods(s).all()[0];save_record(s,{'date':d,'meal':'午餐','time':'12:00','items':[{'food_id':f['id'],'grams':100}]});reconcile(s);assert s.require('adjustment',d)['signature']!=a['signature']
    with pytest.raises(AppError):apply_adjustment(s,d,{'version':a['version'],'action':'apply'})
    old=s.require('profile','self');save_profile(s,{**profile(health_status='有',conditions=['肾脏问题']),'version':old['version']});reconcile(s);assert s.require('adjustment',d)['status']=='pending_review'
    past=(date.today()-timedelta(days=20)).isoformat();r=save_feedback(s,past,{'difficulty':'准备费时'});assert r['adjustment']['status']=='pending_review';assert not s.get('plan',(date.fromisoformat(past)+timedelta(days=1)).isoformat());s.close()
