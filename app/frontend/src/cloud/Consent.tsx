import {FormEvent,useEffect,useState} from 'react';
import type {ReactNode} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {resetApiSession} from '../api';

type Session={authenticated:boolean;account_id?:string;csrf?:string};
type Notice={notice_version:string;draft:boolean;text:string};

const API=(import.meta.env.VITE_API_BASE_URL||'').replace(/\/$/,'')+'/api';

async function request<T>(path:string,init:RequestInit={}):Promise<T>{
  const response=await fetch(API+path,{...init,credentials:'include',cache:'no-store',headers:{...(init.body?{'Content-Type':'application/json'}:{}),...(init.headers||{})}});
  if(!response.ok){let detail='云端请求失败，请检查网络后重试';try{detail=(await response.json()).detail||detail}catch{}throw new Error(detail)}
  return response.status===204?undefined as T:await response.json();
}

export default function CloudPortal({children}:{children?:ReactNode}){
  const queryClient=useQueryClient();
  const [session,setSession]=useState<Session|null>(null);
  const [notice,setNotice]=useState<Notice|null>(null);
  const [accepted,setAccepted]=useState(false);
  const [mode,setMode]=useState<'login'|'register'>('login');
  const [email,setEmail]=useState('');
  const [password,setPassword]=useState('');
  const [invite,setInvite]=useState('');
  const [checked,setChecked]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [reauthPassword,setReauthPassword]=useState('');
  const [deleteConfirmation,setDeleteConfirmation]=useState('');
  const [privacyMessage,setPrivacyMessage]=useState('');
  const [accountPanel,setAccountPanel]=useState(false);

  async function refreshSession(){
    const value=await request<Session>('/auth/session');
    setSession(value);
    if(value.authenticated){
      const [consent,csrfSession]=await Promise.all([
        request<{accepted:boolean}>('/privacy/consent'),
        request<Session>('/auth/session')
      ]);
      setAccepted(consent.accepted);
      if(csrfSession.csrf)setSession(csrfSession);
    }
  }
  useEffect(()=>{let alive=true;Promise.all([request<Session>('/auth/session'),request<Notice>('/privacy/notice')]).then(async([s,n])=>{if(!alive)return;setSession(s);setNotice(n);if(s.authenticated){const [c,full]=await Promise.all([request<{accepted:boolean}>('/privacy/consent'),request<Session>('/auth/session')]);if(alive){setAccepted(c.accepted);setSession(full)}}}).catch(e=>{if(alive)setError(e.message)});return()=>{alive=false}},[]);
  useEffect(()=>{const onAccessRequired=(event:Event)=>{const status=(event as CustomEvent<{status:number}>).detail?.status;if(status!==401&&status!==428)return;setAccepted(false);if(status===401)setSession({authenticated:false});queryClient.clear();resetApiSession();void refreshSession().catch(e=>setError(e.message))};window.addEventListener('shansuan-cloud-access-required',onAccessRequired);return()=>window.removeEventListener('shansuan-cloud-access-required',onAccessRequired)},[queryClient]);

  async function submit(event:FormEvent){
    event.preventDefault();setBusy(true);setError('');
    try{
      await request(mode==='login'?'/auth/login':'/auth/register',{method:'POST',body:JSON.stringify(mode==='login'?{email,password}:{email,password,invite_token:invite})});
      queryClient.clear();resetApiSession();
      await refreshSession();setPassword('');
    }catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  async function accept(){
    if(!checked||!notice||!session?.csrf)return;
    setBusy(true);setError('');
    try{await request('/privacy/consent',{method:'POST',headers:{'X-CSRF-Token':session.csrf},body:JSON.stringify({notice_version:notice.notice_version,confirmed:true})});setAccepted(true);setChecked(false)}catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  async function withdraw(){
    if(!session?.csrf)return;
    setBusy(true);setError('');
    try{await request('/privacy/consent/withdraw',{method:'POST',headers:{'X-CSRF-Token':session.csrf}});queryClient.clear();resetApiSession();setAccountPanel(false);setAccepted(false);setChecked(false)}catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  async function logout(){
    if(!session?.csrf)return;
    setBusy(true);setError('');
    try{await request('/auth/logout',{method:'POST',headers:{'X-CSRF-Token':session.csrf}});queryClient.clear();resetApiSession();setSession({authenticated:false});setAccepted(false);setReauthPassword('');setDeleteConfirmation('');setAccountPanel(false)}catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  async function exportData(){
    if(!session?.csrf||!reauthPassword)return;
    setBusy(true);setError('');setPrivacyMessage('');
    try{
      const response=await fetch(API+'/privacy/export',{method:'POST',credentials:'include',cache:'no-store',headers:{'Content-Type':'application/json','X-CSRF-Token':session.csrf},body:JSON.stringify({password:reauthPassword})});
      if(!response.ok){let detail='数据导出失败，请稍后重试';try{detail=(await response.json()).detail||detail}catch{}throw new Error(detail)}
      const blob=await response.blob();
      const disposition=response.headers.get('Content-Disposition')||'';
      const filename=disposition.match(/filename="?([^";]+)"?/i)?.[1]||'shansuan-account-export.json';
      const url=URL.createObjectURL(blob);const anchor=document.createElement('a');anchor.href=url;anchor.download=filename;anchor.click();URL.revokeObjectURL(url);
      setPrivacyMessage('已生成并下载你的云端数据副本。');
    }catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  async function deleteAccount(){
    if(!session?.csrf||!reauthPassword||deleteConfirmation!=='删除我的云端账户及全部数据')return;
    setBusy(true);setError('');setPrivacyMessage('');
    try{
      const result=await request<{deleted:boolean;retention_note:string}>('/privacy/account',{method:'DELETE',headers:{'X-CSRF-Token':session.csrf},body:JSON.stringify({password:reauthPassword,confirmation:deleteConfirmation})});
      setPrivacyMessage(result.retention_note);queryClient.clear();resetApiSession();setSession({authenticated:false});setAccepted(false);setPassword('');setReauthPassword('');setDeleteConfirmation('');setAccountPanel(false);
    }catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }

  return <div className={accepted&&session?.authenticated?'cloud-portal cloud-workspace-shell':'cloud-portal'}>
    <header className="cloud-portal-header"><img src="/icon-192.png" alt=""/><div><span className="cloud-portal-kicker">SHANSUAN · PRIVATE NUTRITION</span><h1>膳算云端</h1><p>仅通过独立云端账户访问，不读取这台电脑的本地档案。</p></div></header>
    {error&&<p role="alert" className="cloud-portal-error">{error}</p>}
    {privacyMessage&&<p role="status" className="cloud-portal-privacy-message">{privacyMessage}</p>}
    {!session||!notice?<section className="cloud-portal-card" role="status">正在安全连接云端…</section>:!session.authenticated?<section className="cloud-portal-card">
      <h2>{mode==='login'?'登录你的账户':'邀请码注册'}</h2>
      <form onSubmit={submit}>
        <label className="cloud-portal-field">邮箱<input aria-label="邮箱" type="email" autoComplete="email" required value={email} onChange={e=>setEmail(e.target.value)}/></label>
        <label className="cloud-portal-field">密码<input aria-label="密码" type="password" autoComplete={mode==='login'?'current-password':'new-password'} required minLength={mode==='login'?1:12} value={password} onChange={e=>setPassword(e.target.value)}/></label>
        {mode==='register'&&<label className="cloud-portal-field">邀请码<input aria-label="邀请码" autoComplete="off" required value={invite} onChange={e=>setInvite(e.target.value)}/></label>}
        <button className="cloud-portal-primary" disabled={busy}>{busy?'正在处理…':mode==='login'?'登录':'创建账户'}</button>
      </form>
      <button className="cloud-portal-link" type="button" onClick={()=>setMode(mode==='login'?'register':'login')}>{mode==='login'?'已有邀请码？创建账户':'返回登录'}</button>
    </section>:!accepted?<section className="cloud-portal-card">
      <span className="cloud-portal-eyebrow">账户已登录 · 账户资料与本机资料隔离</span>
      <h2>敏感个人信息处理单独同意</h2>
      <p>健康档案、疾病与过敏信息、饮食记录、照片及问答属于敏感个人信息。不同意仍可登录、查看说明或退出；同意后可随时撤回。</p>
      <details><summary>阅读隐私说明{notice.draft?'（开发草案）':''}</summary><div data-testid="privacy-notice" className="cloud-portal-notice">{notice.text}</div></details>
      <label className="cloud-portal-checkbox"><input type="checkbox" checked={checked} onChange={e=>setChecked(e.target.checked)}/>我已阅读当前说明，并单独同意按上述用途处理我的敏感个人信息</label>
      <div className="cloud-portal-actions"><button className="cloud-portal-primary" disabled={!checked||busy} onClick={accept}>{busy?'正在保存…':'同意并继续'}</button><button disabled={busy} onClick={logout}>暂不同意并退出</button></div>
    </section>:<>
      <div className="cloud-workspace-tools"><button type="button" aria-expanded={accountPanel} onClick={()=>setAccountPanel(x=>!x)}>账户与隐私</button></div>
      {accountPanel&&<section className="cloud-portal-card cloud-account-panel"><span className="cloud-portal-eyebrow">账户已登录 · 敏感信息授权已开启</span><h2>账户与隐私</h2><p>撤回后，云端将停止新的健康信息处理；已保存内容仍可通过数据权利功能导出或删除。</p><div className="cloud-portal-actions"><button disabled={busy} onClick={withdraw}>撤回健康信息处理同意</button><button disabled={busy} onClick={logout}>退出登录</button></div></section>}
      {children||<section className="cloud-portal-card" role="status">云端功能尚未加载。</section>}
    </>}
    {session?.authenticated&&(!accepted||accountPanel)&&<section className="cloud-portal-card cloud-portal-privacy-tools" aria-labelledby="cloud-privacy-tools-title">
      <h2 id="cloud-privacy-tools-title">个人数据权利</h2>
      <p>导出或删除账户前需要重新输入账户密码。删除会永久清除主数据库中的账户数据；云端备份尚未配置，备份保留期限与到期清理流程仍需在正式上线前完成并告知。</p>
      <p>导出的 JSON 是含个人资料的未加密副本，请妥善保管。账户含云端附件时，完整附件导出与清理尚未启用，系统会阻止不完整导出或删除。</p>
      <label className="cloud-portal-field">账户密码（复验）<input aria-label="账户密码（复验）" type="password" autoComplete="current-password" value={reauthPassword} onChange={e=>setReauthPassword(e.target.value)}/></label>
      <div className="cloud-portal-actions"><button className="cloud-portal-primary" disabled={busy||!reauthPassword} onClick={exportData}>{busy?'正在处理…':'导出我的云端数据'}</button></div>
      <label className="cloud-portal-field">删除确认语<input aria-label="删除确认语" value={deleteConfirmation} onChange={e=>setDeleteConfirmation(e.target.value)} placeholder="删除我的云端账户及全部数据"/></label>
      <div className="cloud-portal-actions"><button className="cloud-portal-danger" disabled={busy||!reauthPassword||deleteConfirmation!=='删除我的云端账户及全部数据'} onClick={deleteAccount}>永久删除云端账户</button></div>
    </section>}
    {!accepted&&<footer>云端试用未发布 · 本机版资料不会自动迁移到云端</footer>}
  </div>
}
