from datetime import date
import pytest
from app.backend.storage.database import Store
from app.backend.domain.profile import save_profile
from app.backend.domain.records import summary,save_record
from app.backend.domain.products import seed,save_product,match,add_plan,consume
from app.backend.errors import AppError
from app.tests.helpers import profile
from app.backend.main import create_app
from fastapi.testclient import TestClient
import io
from PIL import Image

def verified(**changes):
    p=dict(name='正式样品',brand='测试品牌',category='零食',ingredients='燕麦、水',allergens=[],cross_contact='无已知交叉接触',allergens_confirmed=True,verification='已核实',source='最终标签 v1',verifier='测试核实人',verified_date=date.today().isoformat(),unit='g',nutrients={'energy':200,'protein':20,'fat':5,'carbs':20,'fiber':3,'sodium':100},forms=['即食食品'],tastes=['清淡'])
    p.update(changes);return p

def test_seed_unverified_and_never_counts(tmp_path):
    s=Store(tmp_path)
    try:
        seed(s);seed(s);assert len(s.list('product'))==6
        p=next(p for p in s.list('product') if p['name']=='低脂蛋白棒')
        assert p['illustration']['nutrients']['energy_kj']==1780
        assert p['nutrients']['energy'] is None
        save_profile(s,profile())
        assert not match(s,p)['eligible']
        with pytest.raises(AppError):add_plan(s,p['id'],{'date':date.today().isoformat(),'meal':'早餐','amount':50,'version':p['version']})
        with pytest.raises(AppError):consume(s,p['id'],{'date':date.today().isoformat(),'meal':'早餐','time':'08:00','amount':50,'confirmed':True,'version':p['version']})
        assert not s.list('record')
    finally:s.close()

def test_verification_requires_provenance_and_formal_core_label(tmp_path):
    s=Store(tmp_path)
    try:
        for changes in [{'ingredients':''},{'source':''},{'verifier':''},{'allergens_confirmed':False},{'cross_contact':''},{'nutrients':{'protein':18}},{'verified_date':'bad'}]:
            with pytest.raises(AppError):save_product(s,verified(**changes))
        p=save_product(s,verified());assert p['verification']=='已核实'
    finally:s.close()

def test_safety_before_preferences_and_medical_claims(tmp_path):
    s=Store(tmp_path)
    try:
        p=save_product(s,verified(ingredients='大豆分离蛋白、燕麦',allergens=['大豆']))
        save_profile(s,profile(allergy_status='有',allergens=['大豆']))
        r=match(s,p);assert not r['eligible'] and '大豆' in ' '.join(r['reasons'])
        s.delete('profile','self',s.require('profile','self')['version']);save_profile(s,profile(excluded=['燕麦']))
        assert not match(s,p)['eligible']
        s.delete('profile','self',s.require('profile','self')['version']);save_profile(s,profile(health_status='有',conditions=['高血压']))
        assert not match(s,p)['eligible'] and '专业' in ' '.join(match(s,p)['reasons'])
        s.delete('profile','self',s.require('profile','self')['version']);save_profile(s,profile(goals=['补充蛋白质'],primary_goal='补充蛋白质'))
        r=match(s,p);assert r['eligible'] and '20' in ' '.join(r['reasons']) and len(r['alternatives'])>=2
    finally:s.close()

def test_plan_actual_snapshot_and_no_generic_record_bypass(tmp_path):
    s=Store(tmp_path)
    try:
        save_profile(s,profile());p=save_product(s,verified());d=date.today().isoformat()
        plan=add_plan(s,p['id'],{'date':d,'meal':'加餐','amount':35,'version':p['version']})
        assert not s.list('record') and not s.list('plan')
        body={'date':d,'meal':'加餐','time':'15:00','amount':35,'version':p['version'],'plan_id':plan['id'],'plan_version':plan['version']}
        with pytest.raises(AppError):consume(s,p['id'],body)
        r=consume(s,p['id'],{**body,'confirmed':True});assert r['nutrition']['protein']['known']==7
        assert summary(s,d)['nutrition']['energy']['known']==70
        assert s.require('product_plan',plan['id'])['status']=='recorded'
        with pytest.raises(AppError):consume(s,p['id'],{**body,'confirmed':True})
        changed=save_product(s,{**p,'nutrients':{**p['nutrients'],'protein':40}},p['id'])
        assert s.require('record',r['id'])['items'][0]['product_snapshot']['nutrients']['protein']==20
        edited=save_record(s,{**r,'date':d,'time':'16:00'},r['id']);assert edited['nutrition']['protein']['known']==7
        with pytest.raises(AppError):save_record(s,{'date':d,'time':'16:00','meal':'加餐','items':[{'food_id':'product-'+changed['id'],'grams':35}]})
    finally:s.close()

def test_product_api_privacy_files_backup_and_explicit_consumption(tmp_path):
    from app.backend.storage.backups import Backups
    app=create_app(tmp_path/'source');s=app.state.store
    try:
        with TestClient(app,base_url='http://127.0.0.1:18765') as c:
            h={'X-CSRF-Token':c.get('/api/session').json()['csrf']}
            assert c.get('/api/products').status_code==200
            assert len(c.get('/api/products').json()['items'])==6
            assert c.post('/api/products',json=verified()).status_code==403
            save_profile(s,profile())
            def post(path,b):return c.post('/api'+path,json={**b,'request_key':'test-'+__import__('uuid').uuid4().hex},headers=h)
            p=post('/products',verified()).json();assert p['name']=='正式样品'
            assert c.get('/api/products/'+p['id']).json()['match']['eligible']
            assert c.get('/api/products').json()['recommendations']==[]
            assert post('/products/settings',{'enabled':True,'version':0}).status_code==200
            assert len(c.get('/api/products').json()['recommendations'])==1
            raw=io.BytesIO();Image.new('RGB',(20,20),'green').save(raw,format='PNG')
            image=c.post('/api/products/'+p['id']+'/files',headers=h,data={'version':str(p['version']),'role':'main'},files={'file':('sample.png',raw.getvalue(),'image/png')})
            assert image.status_code==200;f=image.json();assert f['role']=='main'
            pdf=b'%PDF-1.4\nproduct-private-label-marker\n%%EOF'
            doc=c.post('/api/products/'+p['id']+'/files',headers=h,data={'version':str(p['version']),'role':'label'},files={'file':('label.pdf',pdf,'application/pdf')})
            assert doc.status_code==200
            assert c.get('/api/product-files/'+doc.json()['id']).content==pdf
            bad=c.post('/api/products/'+p['id']+'/files',headers=h,data={'version':str(p['version']),'role':'label'},files={'file':('bad.html',b'<script>x</script>','text/html')})
            assert bad.status_code==422
            body={'version':p['version'],'date':date.today().isoformat(),'meal':'午餐','amount':25,'time':'12:00'}
            assert post('/products/'+p['id']+'/consume',body).status_code==422
            body.update(confirmed=True,request_key='same-product-confirmation')
            first=c.post('/api/products/'+p['id']+'/consume',json=body,headers=h)
            assert first.status_code==200
            assert c.post('/api/products/'+p['id']+'/consume',json=body,headers=h).json()['id']==first.json()['id']
            assert len(s.list('record'))==1
            blob=app.state.backups.portable('product-password','product-password')
            other=Store(tmp_path/'restore');b=Backups(other)
            try:
                t=b.stage(blob,'product-password');b.commit(t['ticket'],'整体替换')
                assert other.require('product',p['id'])['name']==p['name']
                from app.backend.storage.photos import Photos
                assert Photos(other).read(doc.json()['id'])==pdf
                assert other.list('record')[0]['nutrition']['protein']['known']==5
            finally:other.close()
            for path in (tmp_path/'source').rglob('*'):
                if path.is_file():assert b'product-private-label-marker' not in path.read_bytes()
    finally:app.state.tasks.close();s.close()

def test_liquid_cross_contact_archive_and_changed_profile(tmp_path):
    s=Store(tmp_path)
    try:
        save_profile(s,profile());p=save_product(s,verified(unit='mL'))
        r=consume(s,p['id'],{'version':p['version'],'date':date.today().isoformat(),'meal':'加餐','time':'14:00','amount':10,'confirmed':True})
        assert r['items'][0]['unit']=='mL' and r['nutrition']['protein']['known']==2
        p=save_product(s,{**p,'cross_contact':'可能含有花生'},p['id'])
        old=s.require('profile','self');save_profile(s,{**profile(allergy_status='有',allergens=['花生']),'version':old['version']})
        assert not match(s,p)['eligible']
        for flag in ['hidden','archived']:
            p=save_product(s,{**p,flag:True},p['id']);assert not match(s,p)['eligible']
        assert len(s.list('record'))==1
    finally:s.close()
