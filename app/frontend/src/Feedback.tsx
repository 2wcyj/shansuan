import {ClipboardCheck,Utensils,Heart,NotebookPen} from 'lucide-react';
import {useState} from 'react';
import {Link} from 'react-router-dom';
import {useQuery} from '@tanstack/react-query';
import {api,Data,today,useSelectedDate,requestKey} from './api';
import {Card,Field,Notice,useAction,LoadError} from './ui';
import {Tags} from './Profile';

const defaults={adherence:'未填',hunger:'未填',taste:'未填',difficulty:'未填',discomfort_status:'未填',symptoms:[],energy:'未填',binge:null,special:'',temporary_goal:'',suspect_food_ids:[]};
const quickChoices=[
  {key:'顺利',label:'今天整体顺利',field:'adherence',value:'基本按照'},
  {key:'饥饿',label:'经常饿',field:'hunger',value:'经常饿'},
  {key:'过饱',label:'有些过饱',field:'hunger',value:'过饱'},
  {key:'费时',label:'准备费时',field:'difficulty',value:'准备费时'},
  {key:'购买',label:'购买不便',field:'difficulty',value:'购买不便'},
  {key:'口味',label:'口味不合',field:'taste',value:'不喜欢'},
  {key:'不适',label:'身体不适',field:'discomfort_status',value:'有'},
  {key:'疲劳',label:'精力疲劳',field:'energy',value:'疲劳'}
] as const;

function quickFrom(value:Data|null){
  if(!value)return '';
  const priority=['不适','饥饿','过饱','费时','购买','口味','疲劳','顺利'];
  return priority.find(key=>{const option=quickChoices.find(item=>item.key===key);return option&&value[option.field]===option.value})??'';
}

export default function Feedback(){
  const [date,setDate]=useSelectedDate();
  const q=useQuery({queryKey:['feedback',date],queryFn:()=>api('/feedback/'+date)});
  return <>
    <div className="row between"><div><h1>今天，感觉如何？</h1><p className="muted">不必追求满分。记录真实感受，让明天更容易执行。</p></div><Field label="反馈日期"><input type="date" max={today()} required value={date} onChange={e=>e.target.value&&setDate(e.target.value)}/></Field></div>
    {!q.data?<LoadError error={q.error} retry={()=>q.refetch()}/>:<><FeedbackForm key={date+':'+(q.data.feedback?.version??0)} date={date} value={q.data.feedback}/>{q.data.adjustment?<Adjustment value={q.data.adjustment}/>:<Card title="明日调整"><p>保存反馈后会检查明日计划。没有反馈时不推测你的感受，也不会因此判定执行失败。</p></Card>}</>}
  </>;
}

function FeedbackForm({date,value}:{date:string,value:Data|null}){
  const [v,set]=useState<Data>(value??defaults);
  const [quick,setQuick]=useState(()=>quickFrom(value));
  const [emergency,setEmergency]=useState('');
  const a=useAction();
  const records=useQuery({queryKey:['records',date],queryFn:()=>api('/records?date='+date)});
  const setKey=(k:string,x:unknown)=>set(p=>({...p,[k]:x}));
  const selectQuick=(key:string)=>{
    const previous=quickChoices.find(item=>item.key===quick);
    const next=quickChoices.find(item=>item.key===key);
    set(old=>{
      const updated={...old};
      if(previous&&updated[previous.field]===previous.value)updated[previous.field]=defaults[previous.field];
      if(previous?.field==='discomfort_status'){updated.symptoms=[];updated.suspect_food_ids=[];}
      if(next)updated[next.field]=next.value;
      return updated;
    });
    setQuick(key);
  };
  const fields=[
    ['adherence','是否按建议饮食',['未填','基本按照','部分按照','没有按照']],
    ['hunger','饥饿与饱腹感',['未填','合适','经常饿','过饱']],
    ['taste','口味感受',['未填','合适','偏淡','偏咸','不喜欢']],
    ['difficulty','准备和购买难度',['未填','容易','准备费时','购买不便']],
    ['energy','精力状态',['未填','良好','一般','疲劳']]
  ] as const;
  return <Card title={value?'修改当日反馈':'一分钟，记下今天'}>
    <form onSubmit={async e=>{
      e.preventDefault();
      const body={...v};
      for(const k of ['id','day','created_at','updated_at','profile_version'])delete body[k];
      const result=await a.run(()=>api('/feedback/'+date,'PUT',{...body,request_key:requestKey()}),'反馈与明日调整已保存');
      if(result)setEmergency((result as Data).emergency??'');
    }}>
      <p className="feedback-save-state" role="status"><ClipboardCheck size={17}/>{a.busy?'保存中…':a.error?'保存失败，输入已保留':a.message?'保存成功':JSON.stringify(v)!==JSON.stringify(value??defaults)?'已选择，尚未保存':value?'已保存当日反馈':'今天尚未反馈'}</p>
      <Field label="今天最明显的情况（选一项即可）">
        <select value={quick} onChange={e=>selectQuick(e.target.value)}>
          <option value="">先不记录</option>
          {quickChoices.map(option=><option key={option.key} value={option.key}>{option.label}</option>)}
        </select>
      </Field>
      <p className="muted">其余反馈都可留空；需要时再展开补充。</p>
      <details>
        <summary>补充其他感受（可选）</summary>
        <section className="feedback-group"><h3><Utensils size={18}/>饮食执行、饱腹与口味</h3><div className="grid two">{fields.filter(([key])=>key!=='energy').map(([key,label,options])=><Field key={key} label={label}><select value={v[key]} onChange={e=>setKey(key,e.target.value)}>{options.map(x=><option key={x}>{x}</option>)}</select></Field>)}
          <Field label="是否出现暴食"><select value={v.binge===null?'':String(v.binge)} onChange={e=>setKey('binge',e.target.value===''?null:e.target.value==='true')}><option value="">未填</option><option value="false">没有</option><option value="true">有</option></select></Field>
        </div>
        </section><section className="feedback-group"><h3><Heart size={18}/>精力与身体感受</h3><Field label="精力状态"><select value={v.energy} onChange={e=>setKey('energy',e.target.value)}>{['未填','良好','一般','疲劳'].map(x=><option key={x}>{x}</option>)}</select></Field>
        <Field label="是否出现不适"><select value={v.discomfort_status} onChange={e=>set({...v,discomfort_status:e.target.value,symptoms:[],suspect_food_ids:[]})}>{['未填','无','有'].map(x=><option key={x}>{x}</option>)}</select></Field>
        {v.discomfort_status==='有'&&<>
          <Tags label="不适感受（多选，可自定义）" options={['胃胀','胃痛','腹泻','便秘','恶心','皮疹']} value={v.symptoms} onChange={x=>setKey('symptoms',x)}/>
          <fieldset><legend>需要核对的当日食物（可选，不代表已确定原因）</legend>{Array.from(new Map((records.data?.records??[]).flatMap((r:Data)=>r.items).map((i:Data)=>[i.food_id,i])).values()).map((it:any)=><label key={it.food_id} className="check-option"><input type="checkbox" checked={v.suspect_food_ids.includes(it.food_id)} onChange={e=>setKey('suspect_food_ids',e.target.checked?[...v.suspect_food_ids,it.food_id]:v.suspect_food_ids.filter((x:string)=>x!==it.food_id))}/>{it.name}</label>)}{!records.data?.record_count&&<p className="muted">这一天还没有饮食记录，可先补记，再核对相关食物。</p>}</fieldset>
        </>}
        </section><section className="feedback-group"><h3><NotebookPen size={18}/>其他情况与想法</h3><Field label="特殊情况（可选）"><textarea maxLength={1500} value={v.special} onChange={e=>setKey('special',e.target.value)} placeholder="例如出差、加班、聚餐或疲劳"/></Field>
        <Field label="临时目标或想调整的地方（可选）"><input maxLength={300} value={v.temporary_goal} onChange={e=>setKey('temporary_goal',e.target.value)}/></Field>
      </section></details>
      <p className="muted">临时文字不会直接改变健康限制或处方。胸痛、呼吸困难、意识异常或严重过敏请立即寻求医疗帮助，必要时拨打120。</p>
      <button className="primary" disabled={a.busy}>保存反馈并检查明日方案</button>
      <Notice action={a}/>
      {emergency&&<p role="alert" className="warning">{emergency}</p>}
    </form>
  </Card>;
}

export function Adjustment({value:v}:{value:Data}){
  const a=useAction();
  return <Card title={`明日方案 · ${v.target_date}`}>
    <span className="badge">{{applied:'已按程序规则调整',unchanged:'保留基础安排',pending_review:'待你核对',confirmed:'已确认应用',restored:'已恢复原方案'}[v.status as string]}</span>
    <p>{v.reason}</p>
    <small className="muted">来源：程序规则 {v.rule_version}；档案版本 {v.inputs.profile_version}，反馈版本 {v.inputs.feedback_version}，当日实际记录 {v.inputs.records} 条。保留历史版本，无模型训练。</small>
    {v.changes.length>0?<div className="table-wrap"><table><thead><tr><th>餐次</th><th>调整前</th><th>调整后</th></tr></thead><tbody>{v.changes.map((c:Data)=><tr key={c.meal}><td>{c.meal}</td><td>{c.before}<small>{c.before_items.map((x:Data)=>`${x.name} ${x.grams}g`).join('、')}</small></td><td>{c.after}<small>{c.after_items.map((x:Data)=>`${x.name} ${x.grams}g`).join('、')}</small></td></tr>)}</tbody></table></div>:<p>没有足够依据改变食物或分量，原有安排保持。</p>}
    <details><summary>查看主要营养素估算的前后影响</summary><div className="table-wrap"><table><thead><tr><th>指标</th><th>之前</th><th>之后</th><th>变化</th></tr></thead><tbody>{[['energy','热量'],['protein','蛋白质'],['fat','脂肪'],['carbs','碳水']].map(([k,label])=><tr key={k}><td>{label}（{v.impact[k].unit}）</td><td>{v.impact[k].before??'未知'}</td><td>{v.impact[k].after??'未知'}</td><td>{v.impact[k].delta===null?'数据不完整，无法比较':(v.impact[k].delta>0?'+':'')+v.impact[k].delta}</td></tr>)}</tbody></table></div></details>
    {v.limitations.map((x:string)=><p key={x} className="muted">{x}</p>)}
    <div className="row actions">{v.status==='pending_review'&&v.proposal&&<button disabled={a.busy} onClick={()=>a.run(()=>api('/adjustments/'+v.source_date,'POST',{version:v.version,action:'apply',request_key:requestKey()}),'调整已应用到明日计划')}>确认应用以上调整</button>}{['applied','confirmed'].includes(v.status)&&v.before&&<button disabled={a.busy} onClick={()=>a.run(()=>api('/adjustments/'+v.source_date,'POST',{version:v.version,action:'restore',request_key:requestKey()}),'已恢复调整前方案')}>恢复调整前方案</button>}<Link to={'/meals?date='+v.target_date}>查看明日完整计划 →</Link></div>
    <Notice action={a}/>
  </Card>;
}
