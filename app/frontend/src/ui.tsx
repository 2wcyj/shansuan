import {useRef,useState,useEffect,ReactNode} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {api,apiFetch} from './api';
export function Card({title,children,className='',id}:{title?:string,children:ReactNode,className?:string,id?:string}){return <section id={id} className={'card '+className}>{title&&<h2>{title}</h2>}{children}</section>}
export function Field({label,hint,children}:{label:string,hint?:string,children:ReactNode}){return <label className="field"><span>{label}</span>{children}{hint&&<small className="muted">{hint}</small>}</label>}
export function useAction(){const [busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('');const q=useQueryClient();return {busy,error,message,clear:()=>{setError('');setMessage('')},run:async(fn:()=>Promise<unknown>,success='已保存')=>{setBusy(true);setError('');setMessage('');try{const r=await fn();await q.invalidateQueries();setMessage(success);return r;}catch(e){setError((e as Error).message);return undefined;}finally{setBusy(false)}}};}
export function Notice({action}:{action:ReturnType<typeof useAction>}){return <>{action.busy&&<p role="status">正在处理，请稍候…</p>}{action.error&&<p role="alert" className="error">{action.error}。输入已保留，可重试。</p>}{action.message&&<p role="status" className="success">{action.message}</p>}</>}
export function Dialog({title,children,onClose}:{title:string,children:ReactNode,onClose:()=>void}){const ref=useRef<HTMLDialogElement>(null);useEffect(()=>{ref.current?.showModal();return()=>ref.current?.close()},[]);return <dialog ref={ref} onCancel={onClose} aria-label={title}><div className="row between"><h2>{title}</h2><button type="button" onClick={onClose} aria-label="关闭">×</button></div>{children}</dialog>}
export function LoadError({error,retry}:{error:Error|null,retry:()=>void}){return error?<div role="alert" className="error">{error.message}<button onClick={retry}>重试</button></div>:<p role="status">正在读取本机文件…</p>}
export async function download(path:string,filename:string,method='GET',body?:unknown){
  await api('/status');
  const r=await apiFetch(path,{method,headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined});
  if(!r.ok)throw new Error((await r.json()).error.message);
  const url=URL.createObjectURL(await r.blob());const a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);
}
