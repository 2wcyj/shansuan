import pytest
from pydantic import ValidationError
from app.tests.helpers import profile
from app.backend.storage.database import Store
from app.backend.domain.profile import Profile,save_profile,targets
def test_profile_custom_multiselect_measurement_history_and_pending_plans(tmp_path):
    s=Store(tmp_path);p=profile(allergy_status='有',allergens=['花生','自定义敏感食材'],likes=['白菜'],forms=['外卖'])
    s.put('plan','today',{'meals':[{'status':'pending'}]});save_profile(s,p)
    assert s.require('plan','today')['needs_review']
    p.update(version=1,weight=61,measurement_date='2026-10-17');save_profile(s,p)
    s.close();s=Store(tmp_path)
    assert s.require('profile','self')['allergens']==['花生','自定义敏感食材']
    assert len(s.list('measurement'))==2 and s.history('profile','self')[0]['weight']==60
    s.close()
@pytest.mark.parametrize('change',[{'age':-1},{'height':300},{'weight':0},{'primary_goal':'增肌'},{'allergy_status':'有'},{'allergy_status':'明确无','allergens':['花生']}])
def test_profile_validation(change):
    p=profile();p.update(change)
    with pytest.raises(ValidationError):Profile.model_validate(p)
def test_targets_healthy_formula_and_special_groups():
    assert targets(profile())['energy']==round((10*60+6.25*165-5*30-161)*1.375)
    for change in [{'age':16},{'physiology':'孕期'},{'conditions':['肾脏问题'],'health_status':'有'},{'conditions':['高血糖或糖尿病'],'health_status':'有'},{'health_status':'未填写'},{'sex':'未说明'}]:
        assert targets(profile(**change))['energy'] is None
    assert targets(profile(physiology='孕期',professional_energy_min=1800,professional_energy_max=2000))['energy']==1900
def test_draft_persists_without_official_profile(tmp_path):
    s=Store(tmp_path);s.put('draft','onboarding',{'values':{'age':30},'step':2});s.close();s=Store(tmp_path)
    assert s.get('profile','self') is None and s.require('draft','onboarding')['step']==2
    s.close()
