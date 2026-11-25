import {useState} from 'react';
import {MoreHorizontal} from 'lucide-react';
import {NavLink,Routes,Route,useLocation} from 'react-router-dom';
import {useQuery} from '@tanstack/react-query';
import {AppearanceControl} from './Appearance';
import {api} from './api';
import {LoadError} from './ui';
import {navigation,ManualSave,MobileNavigation} from './Navigation';
import Profile from './Profile';
import Records from './Records';
import Meals from './Meals';
import Home,{HomeMenu} from './Home';
import Photo from './Photo';
import Chat from './Chat';
import Feedback from './Feedback';
import Report from './Report';
import Products,{ProductDetail} from './Products';
import CloudPortal from './cloud/Consent';
export default function App(){return import.meta.env.VITE_API_BASE_URL?.trim()?<CloudPortal><LocalApp cloud/></CloudPortal>:<LocalApp/>}
function LocalApp({cloud=false}:{cloud?:boolean}){const location=useLocation();const [menu,setMenu]=useState(false);const model=useQuery({queryKey:['model'],queryFn:()=>api('/model'),refetchInterval:15000,enabled:!cloud});const q=useQuery({queryKey:['profile'],queryFn:()=>api('/profile')});const visibleNavigation=cloud?navigation.filter(([to])=>to!=='/photo'&&to!=='/chat'):navigation;if(location.pathname==='/'&&q.data?.profile)return <><Home modelReady={!!model.data?.ready} cloudMode={cloud}/><MobileNavigation/></>;return <div className="layout"><aside><div className="brand"><img className="brand-icon" src="/icon-192.png" alt=""/><span>膳算<small>好好吃饭，慢慢来</small></span></div><nav>{visibleNavigation.map(([to,label,Icon])=><NavLink key={to} to={to} end={to==='/'}><Icon size={19}/>{label}</NavLink>)}</nav><div className="local-note"><span className="dot"/>{cloud?'仅在当前云端账户保存':'仅在这台电脑保存'}<br/><small>{cloud?'云端个人空间':'个人使用 · 离线运行'}</small>{!cloud&&<small>{model.data?.ready?'本地模型已就绪':'本地模型未就绪；可手动记录'}</small>}</div></aside><main><header className="app-header"><span className="app-header-name">膳算</span><button type="button" className="mobile-more" aria-label="更多功能" onClick={()=>setMenu(true)}><MoreHorizontal size={23}/></button><div className="row header-tools"><AppearanceControl/>{!cloud&&<ManualSave/>}<span className="badge">{cloud?'云端账户 · 隔离存储':'本机私有 · 无需登录'}</span></div></header><div className={"page page-"+(location.pathname.split("/")[1]||"onboarding")}>{!q.data?<LoadError error={q.error} retry={()=>q.refetch()}/>:!q.data.profile?<Profile onboarding cloudMode={cloud}/>:<Routes><Route path="/" element={<Home cloudMode={cloud}/>}/><Route path="/products" element={<Products cloudMode={cloud}/>}/><Route path="/products/:id" element={<ProductDetail cloudMode={cloud}/>}/><Route path="/meals" element={<Meals/>}/><Route path="/feedback" element={<Feedback/>}/><Route path="/report" element={<Report/>}/>{cloud?<Route path="/photo" element={<p>云端拍照分析服务尚未启用，请勿在此上传照片。</p>}/>:<Route path="/photo" element={<Photo/>}/ >}{cloud?<Route path="/chat" element={<p>云端智能问答服务尚未启用。</p>}/>:<Route path="/chat" element={<Chat/>}/ >}<Route path="/records" element={<Records/>}/><Route path="/profile" element={<Profile cloudMode={cloud}/>}/><Route path="*" element={<Home cloudMode={cloud}/>}/></Routes>}</div></main>{q.data?.profile&&<MobileNavigation/>}{menu&&<HomeMenu modelReady={!!model.data?.ready} cloudMode={cloud} onClose={()=>setMenu(false)}/>}</div>}


