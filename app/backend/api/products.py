from fastapi import APIRouter,Request,UploadFile,File,Form
from fastapi.responses import Response
from app.backend.domain.products import seed,save_product,match,settings,add_plan,consume
from app.backend.domain.food import day
from app.backend.errors import AppError
from .records import mutation

router=APIRouter(prefix='/api')

@router.get('/products')
def listing(request:Request):
    s=request.app.state.store;seed(s);items=s.list('product');config=settings(s)
    matches=[{'product':p,'match':match(s,p)} for p in items]
    return {'items':items,'settings':config,'recommendations':sorted([x for x in matches if x['match']['eligible']],key=lambda x:-x['match']['score']) if config['enabled'] else []}

@router.post('/products/settings')
def configure(request:Request,body:dict):
    s=request.app.state.store
    return mutation(s,body,lambda:settings(s,body),'product-settings')

@router.get('/product-plans')
def plans(request:Request,date:str):
    return {'items':request.app.state.store.list('product_plan',day(date))}

@router.post('/product-plans/{id}/cancel')
def cancel(id:str,request:Request,body:dict):
    s=request.app.state.store
    def op():
        p=s.require('product_plan',id)
        if p['status']!='pending':raise AppError('仅待执行产品计划可取消')
        return s.put('product_plan',id,{**p,'status':'cancelled'},day=p['day'],version=body.get('version'))
    return mutation(s,body,op,'product-plan-cancel-'+id)

@router.get('/products/{id}')
def detail(id:str,request:Request):
    s=request.app.state.store;p=s.require('product',id)
    return {'product':p,'match':match(s,p),'files':[f for f in s.list('product_file') if f['product_id']==id]}

@router.post('/products')
def create(request:Request,body:dict):
    s=request.app.state.store
    return mutation(s,body,lambda:save_product(s,body),'product-create')

@router.put('/products/{id}')
def edit(id:str,request:Request,body:dict):
    s=request.app.state.store;s.require('product',id)
    return mutation(s,body,lambda:save_product(s,body,id),'product-edit-'+id)

@router.post('/products/{id}/plan')
def plan(id:str,request:Request,body:dict):
    s=request.app.state.store
    return mutation(s,body,lambda:add_plan(s,id,body),'product-plan-'+id)

@router.post('/products/{id}/consume')
def actual(id:str,request:Request,body:dict):
    s=request.app.state.store
    return mutation(s,body,lambda:consume(s,id,body),'product-consume-'+id)

@router.post('/products/{id}/files')
async def upload(id:str,request:Request,file:UploadFile=File(...),role:str=Form(...),version:int=Form(...)):
    return request.app.state.photos.product_file(id,await file.read(12*1024*1024+1),file.filename or '',role,version)

@router.get('/product-files/{id}')
def file(id:str,request:Request):
    f=request.app.state.store.require('product_file',id)
    return Response(request.app.state.photos.read(id),media_type=f['mime'],headers={'Content-Disposition':'inline' if f['mime']=='image/jpeg' else 'attachment; filename=label.pdf'})
