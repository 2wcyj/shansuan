import {CSSProperties} from 'react';
import {Data} from './api';

/** Presentation only. Never replaces the stored energy or intake calculations. */
export function MacroRing({value,compact=false}:{value:Data,compact?:boolean}){
 const entries=[['protein','蛋白质',4],['carbs','碳水',4],['fat','脂肪',9]] as const;
 const valid=entries.every(([key])=>{const n=value?.[key];return n?.complete===true&&typeof n.known==='number'&&Number.isFinite(n.known)&&n.known>=0&&n.unit==='g'});
 const total=valid?entries.reduce((s,[k,,factor])=>s+value[k].known*factor,0):0;
 if(!valid||total<=0)return <p className="macro-unavailable muted">数据不足，暂不绘制供能占比；请查看下方已知营养数值。</p>;
 const parts=entries.map(([key,label,factor])=>({key,label,grams:value[key].known,percent:value[key].known*factor/total*100}));
 const a=parts[0].percent,b=a+parts[1].percent;
 return <figure className={'macro-figure'+(compact?' macro-compact':'')}>
  <div className="macro-ring" role="img" data-macro-total={total} aria-label={'估算供能占比：'+parts.map(x=>`${x.label} ${x.percent.toFixed(1)}%`).join('，')} style={{'--macro-a':a+'%','--macro-b':b+'%'} as CSSProperties}><span>供能<small>占比</small></span></div>
  <figcaption><div className="macro-legend">{parts.map(x=><div key={x.key} className={'macro-'+x.key}><i aria-hidden="true"/><span>{x.label}</span><strong>{x.grams.toLocaleString('zh-CN',{maximumFractionDigits:1})} g</strong><small>{x.percent.toFixed(1)}%</small></div>)}</div><p>估算供能：蛋白质 / 碳水 4 kcal/g，脂肪 9 kcal/g；不替代原有总能量。数值对应当前所示分量。</p></figcaption>
 </figure>;
}
