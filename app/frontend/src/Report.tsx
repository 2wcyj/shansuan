import {useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {Link} from 'react-router-dom';
import {api,Data,today,useSelectedDate} from './api';
import {Card,Field,LoadError} from './ui';

function Trend({days,metric,label,unit}:{days:Data[],metric:string,label:string,unit:string}){
  const dense=days.length>7,step=dense?16:76,left=55,right=left+(days.length-1)*step;
  const values=days.map(d=>d.nutrition[metric].known),max=Math.max(1,...values.filter(v=>v!==null))*1.15;
  const x=(i:number)=>left+i*step,y=(v:number)=>180-v/max*145;
  return <Card title={label+'估算趋势'}>
    <svg className="trend" viewBox="0 0 570 245" role="img" aria-label={label+days.length+'天趋势，单位'+unit}>
      <title>{label}估算趋势（{unit}）</title>
      <desc>空白日显示未记；空心圆为未确认完整、当天未结束或含未知营养的部分记录。</desc>
      {[0,.5,1].map(p=><g key={p}><line x1="45" x2={right+20} y1={y(p*max)} y2={y(p*max)} stroke="var(--chart-grid)"/><text x="40" y={y(p*max)+4} textAnchor="end" fontSize="11">{Math.round(p*max)}</text></g>)}
      {values.map((v,i)=>v!==null&&i>0&&values[i-1]!==null?<line key={i} x1={x(i-1)} x2={x(i)} y1={y(values[i-1])} y2={y(v)} stroke="var(--chart-primary)" strokeWidth="2" strokeDasharray={days[i].food_complete&&!days[i].in_progress?'':'4 4'}/>:null)}
      {days.map((d,i)=><g key={d.date}>
        {values[i]===null
          ?dense?<circle cx={x(i)} cy="167" r="2" fill="var(--chart-point)"/>:<text x={x(i)} y="167" textAnchor="middle" fontSize="11">未记</text>
          :<><circle cx={x(i)} cy={y(values[i])} r={dense?3:5} fill={d.food_complete&&!d.in_progress&&d.nutrition[metric].complete?'var(--chart-primary)':'var(--chart-point)'} stroke="var(--chart-primary)" strokeWidth="2"/>{!dense&&<text x={x(i)} y={y(values[i])-11} textAnchor="middle" fontSize="11">{Math.round(values[i])}</text>}</>}
        {(!dense||i%5===0||i===days.length-1)&&<text x={x(i)} y="205" textAnchor="middle" fontSize="11">{d.date.slice(5)}</text>}
        {d.in_progress&&!dense&&<text x={x(i)} y="224" textAnchor="middle" fontSize="10">未结束</text>}
      </g>)}
      <text x="15" y="15" fontSize="11">{unit}</text>
    </svg>
    <p className="muted">实心：已结束且确认完整、指标无缺项。空心：仅部分记录。缺失日不连线、不补零。</p>
  </Card>
}

export default function Report(){
  const [end,setEnd]=useSelectedDate(),[windowDays,setWindowDays]=useState(7);
  const q=useQuery({queryKey:['report',end,windowDays],queryFn:()=>api('/reports?end='+end+'&days='+windowDays)});
  if(!q.data)return <LoadError error={q.error} retry={()=>q.refetch()}/>;
  const r=q.data;
  return <>
    <div className="row between">
      <div>
        <h1>{windowDays===7?'这一周，慢慢了解自己':'这三十天，慢慢了解自己'}</h1>
        <p className="muted">{r.start} 至 {r.end}，连续 {r.window} 个自然日。少一点判断，多一点了解。</p>
      </div>
      <div className="row">
        <Field label="报告窗口"><select value={windowDays} onChange={e=>setWindowDays(Number(e.target.value))}><option value={7}>最近 7 天</option><option value={30}>最近 30 天</option></select></Field>
        <Field label="报告结束日期"><input type="date" max={today()} required value={end} onChange={e=>e.target.value&&setEnd(e.target.value)}/></Field>
      </div>
    </div>
    <div className="grid three">
      <Card title="有饮食记录"><strong className="stat">{r.recorded_days} <small>/ {r.window} 天</small></strong><p className="muted">其中已结束且确认完整 {r.complete_days} 天</p></Card>
      <Card title="主餐按计划记录"><strong className="stat">{r.execution.percent===null?'暂无数据':r.execution.percent+'%'}</strong><p>{r.execution.done} / {r.execution.total} 餐</p><small className="muted">{r.execution.note}</small></Card>
      <Card title="体重测量"><strong className="stat">{r.weight.delta===null?'尚不能比较':(r.weight.delta>0?'+':'')+r.weight.delta+' kg'}</strong><p className="muted">{r.weight.points.length} 次测量；{r.weight.note}</p></Card>
    </div>
    {r.recorded_days===0&&<Card title="从第一条记录开始"><p>当前{r.window}天内没有饮食记录，不据此推断吃得少或营养不足。</p><Link to="/records">记录一餐 →</Link></Card>}
    <div className="grid two"><Trend days={r.days} metric="energy" label="热量" unit="kcal"/><Trend days={r.days} metric="protein" label="蛋白质" unit="g"/></div>
    <Card title="完整记录日的参考均值"><div className="grid two">{[['energy','热量'],['protein','蛋白质']].map(([k,label])=><p key={k}>{label}：<strong>{r.means[k].value??'暂无法计算'} {r.means[k].value!==null?r.means[k].unit:''}</strong><br/><small className="muted">{r.means[k].days} 天参与；仅限已结束、本人确认记录完整且该指标无缺项的日期。</small></p>)}</div></Card>
    <Card title="饮水、睡眠与运动"><div className="grid three">{[['water_ml','已记录日平均饮水','ml'],['sleep_hours','已记录日平均睡眠','小时'],['exercise_minutes','已记录日平均运动','分钟']].map(([k,label,unit])=><div key={k}><h3>{label}</h3><strong>{r.life[k].mean??'未记录'} {r.life[k].mean!==null?unit:''}</strong><p className="muted">{r.life[k].days} 天有该项；仅代表填写的范围，包括已填的当天数据。</p></div>)}</div></Card>
    <Card title="每天的记录与感受"><div className="table-wrap"><table><thead><tr><th>日期</th><th>覆盖情况</th><th>蔬菜 / 水果</th><th>生活记录</th><th>体征</th><th>反馈</th><th>补充记录</th></tr></thead><tbody>{r.days.map((d:Data)=><tr key={d.date}><td>{d.date}{d.in_progress&&<small>当天未结束</small>}</td><td>{d.coverage}<small>{d.record_count} 条饮食</small></td><td>{d.vegetables_g===null?'未记录':Math.round(d.vegetables_g)+'g'} / {d.fruit_g===null?'未记录':Math.round(d.fruit_g)+'g'}<small>仅按已匹配类别统计</small></td><td>水 {d.life?.water_ml??'未填'} ml<br/>睡眠 {d.life?.sleep_hours??'未填'} h<br/>运动 {d.life?.exercise_minutes??'未填'} min<br/>{d.life?.feeling}</td><td>{d.vitals?.length?d.vitals.map((v:Data)=><span key={v.id}>{v.time} {v.systolic!=null?`${v.systolic}/${v.diastolic} mmHg`:''}{v.heart_rate!=null?` ${v.heart_rate} 次/分`:''}<br/></span>):'未记录'}</td><td>{d.feedback?`${d.feedback.hunger} · ${d.feedback.energy} · ${d.feedback.difficulty}`:'尚无反馈'}</td><td><Link to={'/records?date='+d.date}>补记 →</Link></td></tr>)}</tbody></table></div></Card>
    <Card title="下一步，让执行容易一点">{r.tips.map((t:string)=><p key={t}>{t}</p>)}<div className="row actions"><Link to="/feedback">记录感受与查看明日调整 →</Link><Link to="/records">完善饮食记录 →</Link></div></Card>
  </>;
}