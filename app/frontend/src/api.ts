import {useEffect,useState} from 'react';
import {apiUrl as buildApiUrl,sessionUrl,withApiCredentials} from './cloudApiConfig';
export type Data = Record<string, any>;
let csrf = '';
let connecting: Promise<void> | undefined;
const apiBase=import.meta.env.VITE_API_BASE_URL??'';
export const apiUrl=(path:string)=>buildApiUrl(path,apiBase);
export class ApiError extends Error { fields:Data; status:number; constructor(message:string,status:number,fields:Data={}){super(message);this.status=status;this.fields=fields;} }
export async function connect(){
  if(!connecting) connecting=fetch(sessionUrl(apiBase),withApiCredentials({cache:'no-store'})).then(async r=>{if(!r.ok)throw new Error(apiBase?'无法连接膳算云端服务，请检查网络后重试':'无法连接本机服务，请检查启动窗口');csrf=(await r.json()).csrf??'';}).catch(e=>{connecting=undefined;throw e;});
  await connecting;
}
export function resetApiSession(){connecting=undefined;csrf='';}
export async function apiFetch(path:string,options:RequestInit={},reconnected=false):Promise<Response>{
  await connect();
  const headers=new Headers(options.headers);
  if(csrf)headers.set('X-CSRF-Token',csrf);
  const response=await fetch(apiUrl(path),withApiCredentials({...options,headers,cache:'no-store'}));
  if(response.status===403&&!reconnected){
    let issue:Data;
    try{issue=(await response.clone().json()).error}catch{issue={}}
    if(issue?.code==='session'){connecting=undefined;csrf='';return apiFetch(path,options,true)}
  }
  if(apiBase&&(response.status===401||response.status===428)){
    window.dispatchEvent(new CustomEvent('shansuan-cloud-access-required',{detail:{status:response.status}}));
  }
  return response;
}
export async function api<T=any>(path:string,method='GET',body?:unknown,reconnected=false):Promise<T>{
  const headers:Record<string,string>={'X-CSRF-Token':csrf};
  if(body!==undefined && !(body instanceof FormData)) headers['Content-Type']='application/json';
  const r=await apiFetch(path,{method,headers,body:body===undefined?undefined:body instanceof FormData?body:JSON.stringify(body)},reconnected);
  if(!r.ok){let e;try{const payload=await r.json();e=payload.error??{message:payload.detail};}catch{e={message:'膳算服务暂时未响应，请检查连接后重试'};}throw new ApiError(e.message||'膳算服务暂时未响应，请检查连接后重试',r.status,e.fields);}
  return r.status===204?undefined as T:await r.json();
}
export function today(){const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;}
export function requestKey(){return crypto.randomUUID();}

export function useToday(){const [value,set]=useState(today);useEffect(()=>{const update=()=>set(today());const timer=setInterval(update,1000);window.addEventListener('focus',update);document.addEventListener('visibilitychange',update);return()=>{clearInterval(timer);window.removeEventListener('focus',update);document.removeEventListener('visibilitychange',update)}},[]);return value}

export function useSelectedDate(){const current=useToday();const [date,setDate]=useState(()=>new URLSearchParams(location.search).get('date')||today());const follow=useState(()=>!new URLSearchParams(location.search).has('date'))[0];const [manual,setManual]=useState(false);useEffect(()=>{if(follow&&!manual)setDate(current)},[current,follow,manual]);return [date,(value:string)=>{setManual(value!==current);setDate(value)}] as const}
