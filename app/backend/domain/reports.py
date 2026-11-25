"""Local calendar windows; missing observations are never replaced by zero."""
from datetime import date,timedelta
from app.backend.errors import AppError
from .food import day
from .records import summary

WINDOWS=(7,30)

def report(s,end,window=7):
    if window not in WINDOWS:raise AppError('报告窗口仅支持 7 天或 30 天')
    end=date.fromisoformat(day(end));today=date.today().isoformat();days=[]
    for i in range(window-1,-1,-1):
        d=(end-timedelta(days=i)).isoformat();r=summary(s,d);p=s.get('plan',d);f=s.get('feedback',d)
        required=[m for m in p['meals'] if m['meal']!='加餐'] if p else []
        r.update(in_progress=d>=today,feedback=f,plan_count=len(required),plan_done=sum(bool(m['record_ids']) for m in required),vegetables_g=sum(it['grams'] for rec in r['records'] for it in rec['items'] if it['category']=='vegetable') if r['records'] else None,fruit_g=sum(it['grams'] for rec in r['records'] for it in rec['items'] if it['category']=='fruit') if r['records'] else None)
        # A measurement can originate from the profile even if no life entry exists.
        r['measurements']={m['metric']:m['value'] for m in s.list('measurement',d)}
        r['vitals']=s.list('vital',d)
        days.append(r)
    mean={}
    for key in ['energy','protein']:
        vals=[d['nutrition'][key]['total'] for d in days if d['food_complete'] and not d['in_progress'] and d['nutrition'][key]['total'] is not None]
        mean[key]={'value':round(sum(vals)/len(vals),2) if vals else None,'days':len(vals),'unit':days[0]['nutrition'][key]['unit']}
    life={}
    for key in ['water_ml','sleep_hours','exercise_minutes']:
        vals=[d['life'][key] for d in days if d['life'] and d['life'].get(key) is not None]
        life[key]={'mean':round(sum(vals)/len(vals),1) if vals else None,'days':len(vals)}
    weights=[{'date':d['date'],'value':d['measurements']['weight']} for d in days if 'weight' in d['measurements']]
    vitals=[{'date':d['date'],'id':v['id'],'time':v['time'],'systolic':v['systolic'],'diastolic':v['diastolic'],'heart_rate':v['heart_rate']} for d in days for v in d['vitals']]
    total=sum(d['plan_count'] for d in days if not d['in_progress']);done=sum(d['plan_done'] for d in days if not d['in_progress'])
    tips=['这些数据仅代表记录，不诊断营养缺乏；空白日不表示没有吃饭。']
    if sum(bool(d['record_count']) for d in days)<max(4,window//2):tips.append('记录天数较少，先从方便记录的一餐开始，逐步补充即可。')
    if any(d['feedback'] and d['feedback']['difficulty'] in ['准备费时','购买不便'] for d in days):tips.append('准备或购买有困难时，优先选择可简单准备的组合，查看次日调整。')
    if any(d['feedback'] and d['feedback']['hunger']=='经常饿' for d in days):tips.append('出现饥饿时先核对漏餐和餐次；完整记录后再评估分量，避免单凭某一天热量判断。')
    if any(d['record_count'] and not d['nutrition']['protein']['complete'] for d in days):tips.append('部分食物缺少蛋白质资料，请核对标签，暂不能据此判断蛋白质是否足够。')
    if any(d['feedback'] and d['feedback']['discomfort_status']=='有' for d in days):tips.append('已有不适反馈。核对相关食物与时间，持续或严重不适请及时就医。')
    return {'start':days[0]['date'],'end':days[-1]['date'],'window':window,'days':days,'recorded_days':sum(bool(d['record_count']) for d in days),'complete_days':sum(d['food_complete'] and not d['in_progress'] for d in days),'means':mean,'life':life,'execution':{'done':done,'total':total,'percent':round(done/total*100,1) if total else None,'note':'仅统计已结束日期有计划的三顿必要主餐；跳过计未执行，加餐不作强制分母。当天单独显示，不计入该比例。'},'vitals':vitals,'weight':{'points':weights,'delta':round(weights[-1]['value']-weights[0]['value'],2) if len(weights)>=2 else None,'note':'不足两次测量无法比较；两次差值也不代表长期趋势。'},'tips':tips,'calculation_version':'report-2'}