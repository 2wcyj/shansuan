import {useEffect,useRef,useState,ReactNode} from 'react';
import {Link,NavLink} from 'react-router-dom';
import {useQuery} from '@tanstack/react-query';
import {Camera,ChevronRight,MessageCircle,MoreHorizontal,Plus,X,ShieldCheck} from 'lucide-react';
import {api,Data,useToday,requestKey} from './api';
import {Notice,useAction,LoadError} from './ui';
import {ManualSave,navigation} from './Navigation';
import {AppearanceControl} from './Appearance';
import './home.css';

function NumberValue({value,unit,decimals=0}:{value:number|null|undefined,unit:string,decimals?:number}){
  const label=value==null?'—':value.toLocaleString('zh-CN',{maximumFractionDigits:decimals,useGrouping:false});
  return <div className={'home-value '+(label.length>5?'home-value-small':label.length>3?'home-value-long':'')}>
    <span className="home-number">{label}</span><span className="home-unit">{unit}</span>
  </div>;
}

function OverviewCard({kind,children}:{kind:string,children:ReactNode}){
  return <section className={'weather-card weather-'+kind} data-testid={'home-'+kind}>{children}</section>;
}

function HomeMenu({modelReady,onClose}:{modelReady:boolean,onClose:()=>void}){
  const ref=useRef<HTMLDialogElement>(null);
  useEffect(()=>{const dialog=ref.current;dialog?.showModal();return()=>dialog?.close()},[]);
  const close=()=>{ref.current?.close();onClose()};
  return <dialog ref={ref} className="home-menu" aria-labelledby="home-menu-title" onCancel={e=>{e.preventDefault();close()}} onClick={e=>{if(e.target===e.currentTarget)close()}}>
    <div className="home-menu-heading"><div><h2 id="home-menu-title">膳算</h2><p>留一点时间，照顾自己。</p></div><button type="button" className="home-icon-button" aria-label="关闭更多菜单" onClick={close}><X size={20}/></button></div>
    <nav aria-label="更多功能">{navigation.map(([to,label,Icon])=><NavLink key={to} to={to} end={to==='/'} onClick={close}><Icon size={19}/>{label}<ChevronRight className="home-nav-arrow" size={16}/></NavLink>)}</nav>
    <div className="home-appearance"><AppearanceControl/></div>
    <div className="home-menu-save"><ManualSave/><p>平时自动保存；手动保存会另外创建本机加密备份。备份与恢复在个人档案中管理。</p></div>
    <div className="home-privacy"><ShieldCheck size={16}/><span>本机私有 · 无需登录<small>{modelReady?'本地模型已就绪':'本地模型未就绪；可手动记录'}</small></span></div>
  </dialog>;
}

export default function Home({modelReady=false}:{modelReady?:boolean}){
  const date=useToday(),a=useAction(),[menu,setMenu]=useState(false),moreRef=useRef<HTMLButtonElement>(null);
  const q=useQuery({queryKey:['home',date],queryFn:()=>api('/home/'+date)});
  const recent=useQuery({queryKey:['reports',date],queryFn:()=>api('/reports?end='+date)});
  const d=q.data;
  const pending=d?.plan?.meals.find((m:Data)=>m.status==='pending'&&m.recommendation);
  const recipe=pending?.recommendation;
  const mealLink='/meals?date='+date+(pending?'#meal-'+pending.id:'');
  const recordedMeals=new Set((d?.records??[]).map((r:Data)=>r.meal)).size;
  const energy=d?.nutrition.energy,protein=d?.nutrition.protein;
  const feedbackDays=(recent.data?.days??[]).filter((day:Data)=>day.feedback).reverse();
  const feelings=[['hunger','饱腹感'],['energy','精力'],['taste','口味']] as const;
  const latestFeelings=feelings.map(([key,label])=>{
    const day=feedbackDays.find((day:Data)=>day.feedback[key]&&day.feedback[key]!=='未填');
    return {key,label,value:day?.feedback[key],date:day?.date};
  });
  const hasFeelings=latestFeelings.some(item=>item.value);
  const goals=d?[d.profile.primary_goal,...d.profile.goals.filter((goal:string)=>goal!==d.profile.primary_goal)].join(' · '):'';
  return <div className="nutrition-home">
    <main className="home-content">
      <header className="home-heading"><div><h1>今日营养</h1><p><span className="home-app-name">膳算 · </span><time dateTime={date}>{new Date(date+'T12:00:00').toLocaleDateString('zh-CN',{month:'long',day:'numeric',weekday:'long'})}</time></p></div><button type="button" ref={moreRef} className="home-icon-button home-more" aria-label="更多功能" aria-haspopup="dialog" aria-expanded={menu} onClick={()=>setMenu(true)}><MoreHorizontal size={25}/></button></header>
      {!d?<div className="home-loading" aria-busy={q.isPending}><LoadError error={q.error} retry={()=>q.refetch()}/>{!q.error&&<div className="home-skeletons" aria-hidden="true">{[1,2,3,4,5].map(x=><div key={x}/>)}</div>}</div>:<div className="home-cards"><Link className="home-products-link" to="/products">我的产品 <span>本机私有目录 · 自有产品</span> →</Link>
        <OverviewCard kind="energy"><Link className="home-card-body" to="/records" aria-label="今日摄入，查看饮食记录">
          <div className="home-card-copy"><h2>今日摄入</h2><p className="home-subtitle">{goals}</p></div>
          <NumberValue value={energy.known} unit="kcal"/>
          <p className="home-card-note">{d.record_count?(energy.complete?'每一餐，都在慢慢了解自己':'部分营养资料待补充'):'从记录一餐开始'}</p>
          <p className="home-card-meta">参考 {d.targets.energy??'待确认'}{d.targets.energy!=null?' kcal':''}<span>已记录 {recordedMeals} 餐</span></p>
          <p className="home-coverage">{d.coverage} · 营养估算</p>
        </Link></OverviewCard>

        <OverviewCard kind="meal"><Link className="home-card-body" to={d.blocked?'/profile':mealLink} aria-label={pending&&!d.blocked?`查看${pending.meal}推荐详情`:'查看今日饮食安排'}>
          <div className="home-card-copy"><h2>{pending&&!d.blocked?'下一餐 · '+pending.meal:'下一餐推荐'}</h2><p className="home-subtitle">{d.blocked?'完善档案后安排':d.plan?.needs_review?'档案已更新，请核对计划':recipe?.name??'今天的计划已查看完毕'}</p></div>
          <NumberValue value={!d.blocked&&!d.plan?.needs_review?recipe?.nutrition.protein.known:null} unit="g 蛋白质" decimals={1}/>
          <p className="home-card-note">{d.blocked?d.blocked:d.plan?.needs_review?'查看并更新未执行餐次':recipe?`约 ${recipe.minutes} 分钟 · ${recipe.forms?.join(' / ')||recipe.method}`:d.plan?'按自己的节奏，饿了再看看加餐':'查看计划，安排适合的一餐'}</p>
          <p className="home-card-meta">{recipe&&!d.blocked&&!d.plan?.needs_review?`估算 ${recipe.nutrition.energy.known??'未知'} kcal`:'查看安排'}<ChevronRight size={15}/></p>
        </Link></OverviewCard>

        <OverviewCard kind="protein"><Link className="home-card-body" to="/report" aria-label="蛋白质，查看七天报告">
          <div className="home-card-copy"><h2>蛋白质</h2><p className="home-subtitle">今日已记录摄入{d.record_count&&!protein.complete?' · 已知部分':''}</p></div>
          <NumberValue value={protein.known} unit="g" decimals={1}/>
          <p className="home-card-note">{protein.known==null?'记录后了解摄入情况':d.targets.protein?`已记录约为参考值的 ${Math.round(protein.known/d.targets.protein*100)}%`:'个人参考目标待专业确认'}</p>
          <p className="home-card-meta">参考 {d.targets.protein??'待确认'}{d.targets.protein!=null?' g':''}<span>仅对比已记录部分</span></p>
        </Link></OverviewCard>

        <OverviewCard kind="water"><div className="home-card-body">
          <div className="home-card-copy"><h2>今日饮水</h2><p className="home-subtitle">{d.life?.water_ml==null?'今天还没有记录':'今日累计 · 未记录单次时间'}</p></div>
          <NumberValue value={d.life?.water_ml} unit="ml"/>
          <p className="home-card-note">按自己的需要，记下一杯水。</p>
          <button className="home-water-add" disabled={a.busy} aria-label="添加200ml饮水记录" onClick={()=>void a.run(()=>api('/life/water','POST',{date,amount:200,request_key:requestKey()}),'已增加200ml饮水记录')}><Plus size={14}/>{a.busy?'保存中…':'添加 200 ml'}</button>
        </div><div className="home-water-notice"><Notice action={a}/></div></OverviewCard>

        <OverviewCard kind="feelings"><div className="home-card-body">
          <div className="home-card-copy"><h2>近期状态</h2><p className="home-subtitle">根据最近 7 天的反馈整理</p></div>
          <Link className="home-report-link" to="/report" aria-label="查看七天报告"><ChevronRight size={24}/></Link>
          <div className="home-feelings">{!recent.data?<LoadError error={recent.error} retry={()=>recent.refetch()}/>:hasFeelings?<dl>{latestFeelings.map(item=><div key={item.key} title={item.date?`最近填写：${item.date}`:undefined}><dt>{item.label}</dt><dd>{item.value??'未填写'}</dd></div>)}</dl>:<p><strong>记录后生成</strong><span>{feedbackDays.length?'已保存反馈，饱腹感、精力与口味尚未填写':'记下饱腹感、精力与口味，慢慢发现适合自己的节奏。'}</span></p>}</div>
          <div className="home-feelings-footer"><span>{feedbackDays.length?`近 7 天 · ${feedbackDays.length} 次反馈`:'不打分，只关注真实感受'}</span><Link to="/feedback">{d.feedback?'查看今日反馈':'记下感受'}<ChevronRight size={14}/></Link></div>
        </div></OverviewCard>
      </div>}
      <p className="home-footnote"><ShieldCheck size={13}/>数据保存在本机 · 营养数值均为估算</p>
    </main>
    <div className="home-assistant-dock" aria-label="营养助手快捷入口"><Link className="home-ask" to="/chat"><MessageCircle size={22}/><span>今天吃什么？问问你的营养助手</span></Link><Link className="home-camera" to="/photo" aria-label="拍照分析食物"><Camera size={23}/></Link></div>
    {menu&&<HomeMenu modelReady={modelReady} onClose={()=>{setMenu(false);moreRef.current?.focus({preventScroll:true})}}/>}
  </div>;
}
