from fastapi import APIRouter,Request
from app.backend.domain.feedback import save_feedback,adjust,apply_adjustment,reconcile
from app.backend.domain.reports import report
from app.backend.domain.food import day
from .records import mutation
router=APIRouter(prefix='/api')
@router.get('/feedback/{date}')
def read(date:str,request:Request):
    s=request.app.state.store;d=day(date);reconcile(s)
    return {'feedback':s.get('feedback',d),'adjustment':s.get('adjustment',d)}
@router.put('/feedback/{date}')
def save(date:str,request:Request,body:dict):
    s=request.app.state.store
    return mutation(s,body,lambda:save_feedback(s,date,body),'feedback-'+date)
@router.post('/adjustments/{date}')
def apply(date:str,request:Request,body:dict):
    s=request.app.state.store
    return mutation(s,body,lambda:apply_adjustment(s,date,body),'adjustment-'+date)
@router.get('/reports')
def reports(request:Request,end:str):
    s=request.app.state.store;reconcile(s);return report(s,end)
