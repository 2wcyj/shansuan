import {useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {api,Data,requestKey} from './api';
import {Card,Field,Dialog,LoadError,Notice,useAction} from './ui';

const FIELDS:[string,string,number,number,string][]=[
  ['systolic','收缩压',50,300,'mmHg'],
  ['diastolic','舒张压',20,200,'mmHg'],
  ['heart_rate','静息心率',25,240,'次/分'],
];

export function Vitals({date}:{date:string}){
  const now=new Date(),time=`${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}`;
  const [form,setForm]=useState<Data>({time,systolic:null,diastolic:null,heart_rate:null,note:''});
  const [warnings,setWarnings]=useState<string[]>([]);
  const [deleting,setDeleting]=useState<Data>();
  const q=useQuery({queryKey:['vitals',date],queryFn:()=>api('/vitals?date='+date)});
  const a=useAction();
  const items=(q.data?.items??[]) as Data[];
  const save=()=>a.run(async()=>{
    const result=await api('/vitals','POST',{...form,date,request_key:requestKey()});
    setWarnings((result as Data).warnings??[]);
    setForm({...form,systolic:null,diastolic:null,heart_rate:null,note:''});
    await q.refetch();
  });
  const remove=(item:Data)=>{
    void a.run(async()=>{
      await api('/vitals/'+item.id+'/delete','POST',{version:item.version,request_key:requestKey()});
      await q.refetch();
    });
    setDeleting(undefined);
  };
  return <Card title="血压与静息心率（可选）">
    <p className="muted">可选记录，不增加每日必填。血压成组填写，收缩压应高于舒张压；同一天可记录多次，不互相覆盖。这里只做记录与趋势展示，不用于诊断或调整药物。</p>
    <form onSubmit={e=>{e.preventDefault();void save()}}>
      <div className="grid two">
        <Field label="测量时间"><input type="time" required value={form.time} onChange={e=>setForm({...form,time:e.target.value})}/></Field>
        {FIELDS.map(([k,label,min,max,unit])=><Field key={k} label={`${label}（${unit}）`}>
          <input type="number" min={min} max={max} step={1} value={form[k]??''} onChange={e=>setForm({...form,[k]:e.target.value===''?null:Number(e.target.value)})}/>
        </Field>)}
      </div>
      <Field label="备注（可选）"><input maxLength={500} value={form.note??''} onChange={e=>setForm({...form,note:e.target.value})} placeholder="例如：晨起静坐五分钟后"/></Field>
      <div className="actions"><button className="primary" disabled={a.busy}>保存体征记录</button></div>
      <Notice action={a}/>
      {warnings.length>0&&<div role="alert" className="warning">{warnings.map(w=><p key={w}>{w}</p>)}</div>}
      {q.error&&<LoadError error={q.error} retry={()=>q.refetch()}/>}
    </form>
    {items.length>0&&<div className="table-wrap"><table><thead><tr><th>时间</th><th>血压</th><th>心率</th><th>备注</th><th>操作</th></tr></thead><tbody>{items.map((item:Data)=><tr key={item.id}><td>{item.time}</td><td>{item.systolic!=null?`${item.systolic}/${item.diastolic} mmHg`:'未记录'}</td><td>{item.heart_rate!=null?`${item.heart_rate} 次/分`:'未记录'}</td><td>{item.note||'—'}</td><td><button className="danger" onClick={()=>setDeleting(item)}>删除</button></td></tr>)}</tbody></table></div>}
    {deleting&&<Dialog title="删除这条体征记录？" onClose={()=>setDeleting(undefined)}><p>{deleting.day} {deleting.time}。删除后报告中的对应点也会消失。</p><div className="row actions"><button className="danger" disabled={a.busy} onClick={()=>remove(deleting)}>确认删除</button><button onClick={()=>setDeleting(undefined)}>取消</button></div></Dialog>}
  </Card>;
}