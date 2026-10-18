from datetime import date
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator
from app.backend.errors import AppError


class Profile(BaseModel):
    model_config = ConfigDict(extra='forbid',allow_inf_nan=False)
    sex: Literal['男','女','未说明']
    age: int = Field(ge=1,le=110)
    height: float = Field(ge=50,le=250)
    weight: float = Field(ge=10,le=350)
    waist: float | None = Field(default=None,ge=20,le=250)
    body_fat: float | None = Field(default=None,ge=2,le=70)
    sleep_hours: float = Field(ge=0,le=24)
    exercise_weekly: int = Field(ge=0,le=21)
    activity: Literal['久坐','轻度','中度','高强度']
    lifestyle: str = Field(min_length=1,max_length=100)
    goals: list[str] = Field(min_length=1,max_length=30)
    primary_goal: str = Field(min_length=1,max_length=100)
    health_status: Literal['未填写','明确无','有']
    conditions: list[str] = Field(default_factory=list,max_length=40)
    allergy_status: Literal['未填写','明确无','有']
    allergens: list[str] = Field(default_factory=list,max_length=40)
    allergy_notes: str = Field(default='',max_length=1500)
    intolerances: list[str] = Field(default_factory=list,max_length=30)
    physiology: Literal['普通','孕期','哺乳期','待确认'] = '普通'
    professional_notes: str = Field(default='',max_length=3000)
    professional_energy_min: float | None = Field(default=None,ge=500,le=6000)
    professional_energy_max: float | None = Field(default=None,ge=500,le=6000)
    professional_protein: float | None = Field(default=None,ge=10,le=300)
    likes: list[str] = Field(default_factory=list,max_length=50)
    dislikes: list[str] = Field(default_factory=list,max_length=50)
    excluded: list[str] = Field(default_factory=list,max_length=50)
    tastes: list[str] = Field(default_factory=list,max_length=20)
    diet: str = Field(default='普通饮食',max_length=100)
    methods: list[str] = Field(default_factory=list,max_length=20)
    excluded_methods: list[str] = Field(default_factory=list,max_length=20)
    forms: list[str] = Field(default_factory=list,max_length=20)
    budget: float | None = Field(default=None,gt=0,le=2000)
    prep_minutes: int | None = Field(default=None,ge=0,le=240)
    cooking: str = Field(default='方便做饭',max_length=100)
    restrictions: list[str] = Field(default_factory=list,max_length=50)
    measurement_date: date = Field(default_factory=date.today)

    @model_validator(mode='after')
    def check_consistency(self):
        if self.primary_goal not in self.goals:
            raise ValueError('主要目标必须在已选目标中')
        for status,values,label in [(self.health_status,self.conditions,'健康状况'),(self.allergy_status,self.allergens,'过敏原')]:
            if (status=='有') != bool(values):
                raise ValueError(f'{label}的状态与已选标签不一致')
        if self.professional_energy_min is not None and self.professional_energy_max is not None and self.professional_energy_min>self.professional_energy_max:
            raise ValueError('专业能量范围下限不能高于上限')
        for value in self.model_dump().values():
            if isinstance(value,list) and any(not isinstance(s,str) or not s.strip() or len(s)>200 for s in value):
                raise ValueError('标签不可为空，且每项不超过200字')
        return self


def targets(p):
    if not p:
        return {'energy':None,'protein':None,'reason':'请先完成个人档案','source':'nutrition-1'}
    special = p['age']<18 or p['age']>75 or p.get('physiology','普通')!='普通' or bool(p['conditions']) or p['health_status']=='未填写' or p['weight']/(p['height']/100)**2 <18.5
    result = {'energy':None,'protein':None,'reason':'资料或健康条件需要专业确认，未套用普通成人目标；请咨询医生或营养师','source':'nutrition-1'}
    if p.get('professional_energy_min') and p.get('professional_energy_max'):
        result.update(energy=round((p['professional_energy_min']+p['professional_energy_max'])/2),energy_range=[p['professional_energy_min'],p['professional_energy_max']],reason='使用你记录的专业人员能量范围，范围中点仅作展示参考')
    elif not special and p['sex'] in ['男','女']:
        bmr=10*p['weight']+6.25*p['height']-5*p['age']+(5 if p['sex']=='男' else -161)
        factor={'久坐':1.2,'轻度':1.375,'中度':1.55,'高强度':1.725}[p['activity']]
        energy=bmr*factor
        if p['primary_goal'] in ['减脂','控制体脂']:
            energy*=.9
        elif p['primary_goal']=='增肌':
            energy*=1.05
        result.update(energy=round(energy),energy_range=[round(energy*.9),round(energy*1.1)],reason='Mifflin–St Jeor（1990）基础代谢 × 活动系数；减脂参考减10%，增肌加5%。仅适用普通成人，非处方',formula=f'{round(bmr)} × {factor}')
    if p.get('professional_protein'):
        result['protein']=p['professional_protein']
        result['protein_reason']='使用你记录的专业人员蛋白质参考值，非本应用处方'
    elif not special and result['energy']:
        rate=1.2 if p['primary_goal'] in ['增肌','补充蛋白质','健身训练'] else 1.0
        result['protein']=round(p['weight']*rate)
        result['protein_reason']=f'体重 {p["weight"]}kg × {rate}g/kg；普通成人粗略参考1.0，训练目标取ACSM建议范围下沿1.2，非处方，不能根据照片判断是否充足'
    return result


def save_profile(store,body):
    version=body.pop('version',0)
    data=Profile.model_validate(body).model_dump(mode='json')
    with store.atomic():
        saved=store.put('profile','self',data,version=version)
        for field in ['weight','waist','body_fat']:
            if data[field] is not None:
                id=f"{data['measurement_date']}-{field}"
                old=store.get('measurement',id)
                store.put('measurement',id,{'metric':field,'value':data[field]},day=data['measurement_date'],version=old['version'] if old else 0)
        # An unread/unsafe pending plan can never remain executable after changes.
        for plan in store.list('plan'):
            if any(m.get('status')!='recorded' for m in plan.get('meals',[])):
                store.put('plan',plan['id'],{**plan,'needs_review':True},day=plan['day'],version=plan['version'])
    return {'profile':saved,'targets':targets(saved)}
