"""Real local model acceptance probe. Outputs contain public test fixtures only."""
import base64
import io
import json
from pathlib import Path
import time
import urllib.request
import argparse
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
URL = 'http://127.0.0.1:11439/api/chat'
MODEL='qwen3-vl:2b-instruct'


def ask(prompt, image=None):
    if image:
        prompt = '先说明主要食物的大类（如肉类、谷物、蔬菜），再说明名称。最多两句话，无法确定具体肉种时只说肉类。' + prompt
    message = {'role':'user','content':prompt}
    if image:
        with Image.open(image) as photo:
            photo.thumbnail((640,640))
            out = io.BytesIO()
            photo.convert('RGB').save(out,format='JPEG',quality=85)
        message['images']=[base64.b64encode(out.getvalue()).decode()]
    body = {'model':MODEL,'messages':[message],'stream':False,'think':False,'options':{'num_predict':350,'temperature':0,'num_ctx':4096}}
    t=time.monotonic()
    req=urllib.request.Request(URL,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=240) as r: result=json.load(r)
    return {'model':MODEL,'seconds':round(time.monotonic()-t,2),'content':result['message']['content'],'load_seconds':round(result.get('load_duration',0)/1e9,2)}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--case')
    args=parser.parse_args()
    results=[]
    path=ROOT/'.test-output/model-evaluation.json'
    path.parent.mkdir(exist_ok=True)
    if args.case:
        results=json.loads(path.read_text(encoding='utf-8'))
    cases=[('中文对话','请用简体中文说明食物照片为什么只能估算分量，不给出热量数值。',None)]
    for image in sorted((ROOT/'.tools/test-photos').glob('*.jpg')):
        cases.append((image.name,'用简体中文描述这张图片实际可见的主要食物和可能配料。不要虚构无法看到的内容。简洁回答。',image))
    for label,prompt,image in cases:
        if args.case and label != args.case:
            continue
        result={'case':label,**ask(prompt,image)}
        if args.case:
            results=[result if old['case']==label else old for old in results]
        else:
            results.append(result)
        path.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print(label,result['seconds'],result['content'][:100].encode('ascii','backslashreplace').decode(),flush=True)
    assert len(results)==11
    assert all(r['content'].strip() for r in results)
    assert len({r['content'] for r in results[1:]})>=3


if __name__=='__main__':main()
