from fastapi import APIRouter,Request
from app.backend.domain.plans import generate,change,profile_gate
from app.backend.domain.records import summary
from app.backend.domain.food import day
from app.backend.domain.profile import targets
from .records import mutation
router=APIRouter(prefix='/api')

@router.get('/plans/{date}')
def get(date:str,request:Request):
    s=request.app.state.store
    from app.backend.domain.feedback import reconcile
    reconcile(s)
    return {'plan':s.get('plan',day(date)),'blocked':profile_gate(s.get('profile','self'))}

@router.post('/plans/{date}/generate')
def make(date:str,request:Request,body:dict):
    s=request.app.state.store
    return mutation(s,body,lambda:generate(s,date,body.get('version',0)),'plan-generate-'+date)

@router.post('/plans/{date}/meals/{id}')
def meal(date:str,id:str,request:Request,body:dict):
    s=request.app.state.store
    return mutation(s,body,lambda:change(s,date,id,body),'plan-change-'+date+'-'+id)

@router.get('/home/{date}')
def home(date:str,request:Request):
    s=request.app.state.store
    from app.backend.domain.feedback import reconcile
    reconcile(s)
    p=s.get('profile','self')
    return {**summary(s,date),'plan':s.get('plan',date),'profile':p,'targets':targets(p),'feedback':s.get('feedback',date),'blocked':profile_gate(p)}
