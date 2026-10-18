"""Real downloaded local-model checks; never mocked or skipped."""
from pathlib import Path
import json
import urllib.request

ROOT = Path(__file__).resolve().parents[2]


def test_real_food_image_evaluation():
    results = json.loads((ROOT / '.test-output/model-evaluation.json').read_text(encoding='utf-8'))
    assert len(results) == 11
    assert all(x['model'] == 'qwen3-vl:2b-instruct' for x in results)
    assert all(x['content'].strip() for x in results)
    assert len({x['content'] for x in results[1:]}) >= 3
    expected = {'pizza': ['披萨', '比萨', 'pizza'], 'steak': ['肉', '牛排', 'steak'], 'sushi': ['寿司', '米饭', 'sushi']}
    for result in results[1:]:
        category = next(key for key in expected if key in result['case'])
        assert any(word in result['content'].lower() for word in expected[category]), result


def test_real_chinese_chat_no_external_proxy():
    # Explicitly unusable remote proxy: loopback remains accessible.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    body = {'model':'qwen3-vl:2b-instruct', 'stream':False, 'think':False,
            'messages':[{'role':'user','content':'请用中文简短说明：食物照片能否确定隐藏过敏原？'}],
            'options':{'temperature':0,'num_predict':200,'num_ctx':4096}}
    req = urllib.request.Request('http://127.0.0.1:11439/api/chat',
                                 data=json.dumps(body).encode(), headers={'Content-Type':'application/json'})
    with opener.open(req, timeout=180) as response:
        answer = json.load(response)['message']['content']
    assert len(answer.strip()) >= 10
    assert '过敏' in answer
