from fastapi import APIRouter,Request
from app.backend.domain.food import Foods,aggregate,day
from app.backend.domain.records import save_record,delete_record,life,drink,summary
router=APIRouter(prefix='/api')

def mutation(s,body,fn,scope):
    return s.mutate(body.get('request_key'),{'scope':scope,**body},fn)

@router.get('/foods')
def foods(request:Request,q:str=''):
    return {'items':Foods(request.app.state.store).search(q)}

@router.post('/foods')
def food_add(request:Request,body:dict):
    s=request.app.state.store
    return mutation(s,body,lambda:Foods(s).custom(body),'food-add')

@router.put('/foods/{id}')
def food_edit(id:str,request:Request,body:dict):
    s=request.app.state.store;s.require('food',id)
    return mutation(s,body,lambda:Foods(s).custom(body,id),'food-'+id)

@router.post('/nutrition/calculate')
def calculate(request:Request,body:dict):
    items=Foods(request.app.state.store).calculate(body.get('items'))
    return {'items':items,'nutrition':aggregate(items)}

@router.get('/records')
def records(request:Request,date:str):return summary(request.app.state.store,date)

@router.post('/records')
def create(request:Request,body:dict):
    s=request.app.state.store
    # Source links are minted by plan/photo endpoints, never accepted here.
    body={**body,'source':'manual','plan_id':None,'meal_id':None,'analysis_id':None}
    return mutation(s,body,lambda:save_record(s,body),'record-add')

@router.put('/records/{id}')
def edit(id:str,request:Request,body:dict):
    s=request.app.state.store
    return mutation(s,body,lambda:save_record(s,body,id),'record-edit-'+id)

@router.post('/records/{id}/delete')
def delete(id:str,request:Request,body:dict):
    s=request.app.state.store
    return mutation(s,body,lambda:delete_record(s,id,body.get('version')),'record-delete-'+id)

@router.put('/life')
def put_life(request:Request,body:dict):
    s=request.app.state.store
    return mutation(s,body,lambda:life(s,body),'life')

@router.post('/life/water')
def water(request:Request,body:dict):
    s=request.app.state.store
    return mutation(s,body,lambda:drink(s,body),'water')
