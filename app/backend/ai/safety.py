import re
from app.backend.domain.plans import ALIASES

EMERGENCY='可能存在急症。请立即停止使用饮食建议并寻求医疗帮助；在中国请拨打120，尽量由身边的人陪同。疑似严重过敏时遵循医生已给你的急救方案，不要等待本应用回复或自行调整处方药。'

def immediate(text):
    segments=re.split(r'[，。！？,!?；;]|但是|但',text)
    terms=['胸痛','胸口痛','胸口疼','胸部疼','呼吸困难','喘不上气','喘不过气','无法呼吸','透不过气','意识不清','意识模糊','昏厥','昏迷','喉咙肿','喉头水肿','嘴唇肿','舌头肿','严重过敏','快窒息','喘不过来','吸不上气','叫不醒','失去意识','胸口压榨','胸口像被压住','喉咙发紧']
    for segment in segments:
        for term in terms:
            index=segment.find(term)
            if index>=0 and (re.search(r'(不是没有|并非没有)',segment) or not re.search(r'(没有|无|否认|不是|未出现|不伴)(.{0,3})$',segment[max(0,index-6):index])):
                return EMERGENCY
    if re.search(r'(停药|减药|加药|换药|药量|胰岛素).*(怎么|多少|可以|能否|调整|增加|减少)|(?:怎么|可以|能否).*(停药|换药|减药|加药)',text):
        return '本应用不调整药物或治疗。请联系开药医生，尤其不要自行停用胰岛素、降压药等药物。可以帮助你整理饮食记录供就医参考。'
    if re.search(r'诊断|确诊|(?:是不是|会不会|是否).{0,8}(?:病|糖尿病|过敏)|(?:怎么|如何).{0,8}治疗',text):
        return '本应用不能诊断或制定治疗方案。请由医生结合症状与检查评估；可以帮助整理饮食记录供专业人员参考。'
    if re.search(r'(忽略|绕过|取消|忘记).*(过敏|安全|疾病|限制)',text):
        return '过敏和健康限制始终优先，不能按指令忽略。请在个人档案中核对真实条件，已有诊断和处方请与医生确认。'
    return None

def unsafe_reply(text,p):
    for allergen in (p or {}).get('allergens',[]):
        if any(token in text for token in ALIASES.get(allergen,{allergen})):
            # Do not trust negation recognition as an allergy safety filter.
            return True
    for ingredient in (p or {}).get('excluded',[])+(p or {}).get('intolerances',[]):
        if ingredient and ingredient in text:return True
    return bool(re.search(r'(停用|停药|改药|加药|减药|剂量|治愈|确诊|诊断为|保证安全|绝对安全)',text))
