import copy
from datetime import date
import json
import math
from pathlib import Path
import uuid
from app.backend.errors import AppError

NUTRIENTS={'energy':('热量','kcal'),'protein':('蛋白质','g'),'fat':('脂肪','g'),'carbs':('碳水','g'),'fiber':('膳食纤维','g'),'sugar':('总糖','g'),'sodium':('钠','mg'),'purine':('嘌呤','mg')}
BASE=json.loads((Path(__file__).resolve().parents[2]/'resources/foods.json').read_text(encoding='utf-8'))


def number(value,minimum=0,maximum=10000,label='数值'):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not minimum<=value<=maximum:
        raise AppError(f'{label}需要在{minimum}至{maximum}之间','fields',422)
    return value


def day(value):
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError,ValueError):
        raise AppError('请选择有效日期','fields',422)


class Foods:
    def __init__(self,store): self.store=store
    def all(self): return copy.deepcopy(BASE)+self.store.list('food')
    def get(self,id):
        value=next((f for f in self.all() if f['id']==id),None)
        if not value: raise AppError('食物不在资料库中，请先添加食品或重新选择','food',422)
        return value
    def search(self,text=''):
        text=text.strip().casefold()
        return [f for f in self.all() if text in (f['name']+' '+' '.join(f.get('aliases',[]))).casefold()]
    def match(self,text):
        text=text.strip()
        exact=[f for f in self.all() if text==f['name'] or text in f.get('aliases',[])]
        return exact[0] if exact else None  # no silently applying wrong food's numbers
    def custom(self,body,id=None):
        name=str(body.get('name','')).strip()
        if not name or len(name)>100: raise AppError('请填写100字以内的食物名称')
        nutrients={k:None if body.get('nutrients',{}).get(k) is None else number(body['nutrients'][k],0,100000,k) for k in NUTRIENTS}
        allergens=body.get('allergens',[])
        if not isinstance(allergens,list) or any(not isinstance(x,str) or len(x)>100 for x in allergens):raise AppError('请检查过敏原标签')
        id=id or 'custom-'+uuid.uuid4().hex
        return self.store.put('food',id,{'name':name,'nutrients':nutrients,'per_grams':100,'source':{'name':str(body.get('source','用户录入包装标签/自定义'))[:300]},'state':str(body.get('state','按标签'))[:100],'category':str(body.get('category','custom'))[:100],'allergens':allergens,'ingredients_complete':body.get('ingredients_complete') is True,'aliases':body.get('aliases',[])},version=body.get('version',0))
    def calculate(self,items):
        if not isinstance(items,list) or not 1<=len(items)<=40: raise AppError('请添加1至40项食物')
        result=[]
        for item in items:
            grams=number(item.get('grams'),.1,5000,'食物重量（g）')
            f=self.get(item.get('food_id'))
            result.append({'food_id':f['id'],'name':f['name'],'grams':grams,'state':f['state'],'source':f['source'],'category':f['category'],'allergens':f['allergens'],'ingredients_complete':f['ingredients_complete'],'nutrients':{k:None if f['nutrients'].get(k) is None else round(f['nutrients'][k]*grams/100,4) for k in NUTRIENTS}})
        return result


def aggregate(items):
    result={}
    for key,(label,unit) in NUTRIENTS.items():
        values=[i['nutrients'].get(key) for i in items]
        unknown=sum(v is None for v in values)
        known=round(sum(v for v in values if v is not None),2) if any(v is not None for v in values) else None
        result[key]={'known':known,'unknown':unknown,'complete':bool(values) and unknown==0,'total':known if values and unknown==0 else None,'unit':unit,'label':label}
    return result
