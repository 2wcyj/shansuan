import {House,Utensils,Camera,MessageCircle,CalendarDays,Heart,ChartNoAxesCombined,UserRound,Save} from 'lucide-react';
import {api} from './api';
import {useAction} from './ui';

export const navigation=[['/','首页',House],['/meals','今日饮食',Utensils],['/photo','拍照分析',Camera],['/chat','智能问答',MessageCircle],['/records','饮食记录',CalendarDays],['/feedback','每日反馈',Heart],['/report','七天报告',ChartNoAxesCombined],['/profile','个人档案',UserRound]] as const;

export function ManualSave(){
  const a=useAction();
  return <div className="row manual-save">
    <button type="button" title="创建可在个人档案中恢复的本机加密备份" aria-label="手动保存" disabled={a.busy} onClick={()=>void a.run(()=>api('/data/backup/local','POST',{}),'本机加密备份已保存，可在个人档案中检查或恢复')}><Save size={16}/>手动保存</button>
    {(a.busy||a.error||a.message)&&<small role={a.error?'alert':'status'} className={a.error?'error':'muted'}>{a.busy?'正在创建本机备份…':a.error?'保存失败：'+a.error:a.message}</small>}
  </div>;
}
