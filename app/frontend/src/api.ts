import {useEffect,useState} from 'react';
export type Data = Record<string, any>;
let csrf = '';
let connecting: Promise<void> | undefined;
export class ApiError extends Error { fields:Data; status:number; constructor(message:string,status:number,fields:Data={}){super(message);this.status=status;this.fields=fields;} }
export async function connect(){
  if(!connecting) connecting=fetch('/api/session',{cache:'no-store'}).then(async r=>{if(!r.ok)throw new Error('无法连接本机服务，请检查启动窗口');csrf=(await r.json()).csrf;}).catch(e=>{connecting=undefined;throw e;});
  await connecting;
}
export async function api<T=any>(path:string,method='GET',body?:unknown,reconnected=false):Promise<T>{
  await connect();
  const headers:Record<string,string>={'X-CSRF-Token':csrf};
  if(body!==undefined && !(body instanceof FormData)) headers['Content-Type']='application/json';
  const r=await fetch('/api'+path,{method,headers,body:body===undefined?undefined:body instanceof FormData?body:JSON.stringify(body),cache:'no-store'});
  if(!r.ok){let e;try{e=(await r.json()).error;}catch{e={message:'本机服务暂时未响应，请检查启动窗口后重试'};}if(r.status===403&&e.code==='session'&&!reconnected){connecting=undefined;return api<T>(path,method,body,true)}throw new ApiError(e.message,r.status,e.fields);}
  return r.status===204?undefined as T:await r.json();
}
export function today(){const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;}
export function requestKey(){return crypto.randomUUID();}

export function useToday(){const [value,set]=useState(today);useEffect(()=>{const update=()=>set(today());const timer=setInterval(update,1000);window.addEventListener('focus',update);document.addEventListener('visibilitychange',update);return()=>{clearInterval(timer);window.removeEventListener('focus',update);document.removeEventListener('visibilitychange',update)}},[]);return value}

export function useSelectedDate(){const current=useToday();const [date,setDate]=useState(()=>new URLSearchParams(location.search).get('date')||today());const follow=useState(()=>!new URLSearchParams(location.search).has('date'))[0];const [manual,setManual]=useState(false);useEffect(()=>{if(follow&&!manual)setDate(current)},[current,follow,manual]);return [date,(value:string)=>{setManual(value!==current);setDate(value)}] as const}
