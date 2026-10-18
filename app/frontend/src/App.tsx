import {NavLink,Routes,Route} from 'react-router-dom';
import {useQuery} from '@tanstack/react-query';
import {Leaf,House,Utensils,Camera,MessageCircle,CalendarDays,Heart,ChartNoAxesCombined,UserRound,Save} from 'lucide-react';
import {api} from './api';
import {LoadError,useAction} from './ui';
import Profile from './Profile';
import Records from './Records';
import Meals from './Meals';
import Home from './Home';
import Photo from './Photo';
import Chat from './Chat';
import Feedback from './Feedback';
import Report from './Report';
const navigation=[['/','首页',House],['/meals','今日饮食',Utensils],['/photo','拍照分析',Camera],['/chat','智能问答',MessageCircle],['/records','饮食记录',CalendarDays],['/feedback','每日反馈',Heart],['/report','七天报告',ChartNoAxesCombined],['/profile','个人档案',UserRound]] as const;
function ManualSave(){const a=useAction();return <div className="row"><button type="button" title="创建可在个人档案中恢复的本机加密备份" aria-label="手动保存" disabled={a.busy} onClick={()=>void a.run(()=>api('/data/backup/local','POST',{}),'本机加密备份已保存，可在个人档案中检查或恢复')}><Save size={16}/>手动保存</button>{(a.busy||a.error||a.message)&&<small role={a.error?'alert':'status'} className={a.error?'error':'muted'}>{a.busy?'正在创建本机备份…':a.error?'保存失败：'+a.error:a.message}</small>}</div>}
export default function App(){const model=useQuery({queryKey:['model'],queryFn:()=>api('/model'),refetchInterval:15000});const q=useQuery({queryKey:['profile'],queryFn:()=>api('/profile')});return <div className="layout"><aside><div className="brand"><Leaf size={27}/><span>生活营养助手<small>好好吃饭，慢慢来</small></span></div><nav>{navigation.map(([to,label,Icon])=><NavLink key={to} to={to} end={to==='/'}><Icon size={19}/>{label}</NavLink>)}</nav><div className="local-note"><span className="dot"/>仅在这台电脑保存<br/><small>个人使用 · 离线运行</small><small>{model.data?.ready?'本地模型已就绪':'本地模型未就绪；可手动记录'}</small></div></aside><main><header><span>我的生活营养助手</span><div className="row"><ManualSave/><span className="badge">本机私有 · 无需登录</span></div></header><div className="page">{!q.data?<LoadError error={q.error} retry={()=>q.refetch()}/>:!q.data.profile?<Profile onboarding/>:<Routes><Route path="/" element={<Home/>}/><Route path="/meals" element={<Meals/>}/><Route path="/feedback" element={<Feedback/>}/><Route path="/report" element={<Report/>}/><Route path="/photo" element={<Photo/>}/><Route path="/chat" element={<Chat/>}/><Route path="/records" element={<Records/>}/><Route path="/profile" element={<Profile/>}/><Route path="*" element={<Home/>}/></Routes>}</div></main></div>}


