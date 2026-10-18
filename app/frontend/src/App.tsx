import {NavLink,Routes,Route,useLocation} from 'react-router-dom';
import {useQuery} from '@tanstack/react-query';
import {Leaf} from 'lucide-react';
import {api} from './api';
import {LoadError} from './ui';
import {navigation,ManualSave} from './Navigation';
import Profile from './Profile';
import Records from './Records';
import Meals from './Meals';
import Home from './Home';
import Photo from './Photo';
import Chat from './Chat';
import Feedback from './Feedback';
import Report from './Report';
export default function App(){const location=useLocation();const model=useQuery({queryKey:['model'],queryFn:()=>api('/model'),refetchInterval:15000});const q=useQuery({queryKey:['profile'],queryFn:()=>api('/profile')});if(location.pathname==='/'&&q.data?.profile)return <Home modelReady={!!model.data?.ready}/>;return <div className="layout"><aside><div className="brand"><Leaf size={27}/><span>膳算<small>好好吃饭，慢慢来</small></span></div><nav>{navigation.map(([to,label,Icon])=><NavLink key={to} to={to} end={to==='/'}><Icon size={19}/>{label}</NavLink>)}</nav><div className="local-note"><span className="dot"/>仅在这台电脑保存<br/><small>个人使用 · 离线运行</small><small>{model.data?.ready?'本地模型已就绪':'本地模型未就绪；可手动记录'}</small></div></aside><main><header><span>膳算</span><div className="row"><ManualSave/><span className="badge">本机私有 · 无需登录</span></div></header><div className="page">{!q.data?<LoadError error={q.error} retry={()=>q.refetch()}/>:!q.data.profile?<Profile onboarding/>:<Routes><Route path="/" element={<Home/>}/><Route path="/meals" element={<Meals/>}/><Route path="/feedback" element={<Feedback/>}/><Route path="/report" element={<Report/>}/><Route path="/photo" element={<Photo/>}/><Route path="/chat" element={<Chat/>}/><Route path="/records" element={<Records/>}/><Route path="/profile" element={<Profile/>}/><Route path="*" element={<Home/>}/></Routes>}</div></main></div>}


