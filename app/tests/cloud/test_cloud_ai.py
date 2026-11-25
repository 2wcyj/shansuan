"""Cloud AI: schema gates, allergy safety, numbers rendered only from verified data."""
import socket

import httpx
import pytest

from app.backend.cloud.conversation import (parse_selection, parse_vision, prepare_context,
                                            render_reply)
from app.backend.cloud.model_client import (CloudModelClient, ModelConfig, ModelInputError,
                                            ModelUnavailable, model_client_from_env,
                                            prepare_image)
from app.backend.errors import AppError
from app.backend.storage.database import Store


def loopback_available():
    try:
        left, right = socket.socketpair()
        left.close()
        right.close()
        return True
    except OSError:
        return False


requires_loopback = pytest.mark.skipif(not loopback_available(),
                                       reason='sandbox blocks loopback sockets')


def context(**overrides):
    value = {
        'question': '今天蛋白质够吗',
        'profile': {'primary_goal': '日常营养均衡', 'allergens': [], 'excluded': [],
                    'intolerances': [], 'conditions': []},
        'blocked': None,
        'today': {'recorded': True, 'record_count': 2, 'complete': True,
                  'protein_known': 42.0, 'protein_complete': True},
        'protein_target': 60,
        'available_recipes': [{'id': 'r1', 'name': '番茄鸡蛋面'}],
        'history': [],
    }
    value.update(overrides)
    return value


def test_selection_rejects_unknown_intent_steps_and_recipes():
    good = '{"intent":"meals","steps":["check_records"],"recipe_ids":["r1"]}'
    assert parse_selection(good, {'r1'})['recipe_ids'] == ['r1']
    for bad in ['{"intent":"hack","steps":["check_records"],"recipe_ids":[]}',
                '{"intent":"meals","steps":["run_shell"],"recipe_ids":[]}',
                '{"intent":"meals","steps":[],"recipe_ids":[]}',
                '{"intent":"meals","steps":["check_records"],"recipe_ids":["unknown"]}',
                'not json']:
        with pytest.raises(AppError):
            parse_selection(bad, {'r1'})


def test_reply_numbers_come_from_records_not_from_the_model():
    selection = {'intent': 'protein', 'steps': ['check_records'], 'recipe_ids': ['r1']}
    reply = render_reply(selection, context())
    assert '42.0g' in reply and '60g' in reply and '番茄鸡蛋面' in reply
    assert '不构成诊断' in reply


def test_reply_flags_unconfirmed_profile_and_partial_records():
    selection = {'intent': 'protein', 'steps': ['check_records'], 'recipe_ids': []}
    reply = render_reply(selection, context(
        blocked='请先确认过敏信息；未填写不能当作无过敏',
        today={'recorded': True, 'record_count': 1, 'complete': False,
               'protein_known': 20.0, 'protein_complete': False}))
    assert '仅已知部分' in reply
    assert '请先确认过敏信息' in reply


def test_vision_schema_limits_items_and_confidence():
    good = ('{"foods":[{"name":"米饭","ingredients":["米"],"grams":150,'
            '"recognition_confidence":"高","portion_confidence":"低"}],'
            '"uncertainty":"油盐未知"}')
    items, uncertainty = parse_vision(good)
    assert items[0]['grams'] == 150 and uncertainty == '油盐未知'
    for bad in ['{"foods":[]}', '{"foods":[{"name":"","grams":10}]}',
                '{"foods":[{"name":"米饭","grams":-1}]}',
                '{"foods":[' + ','.join(['{"name":"x","grams":1}'] * 5) + ']}',
                'no json']:
        with pytest.raises(AppError):
            parse_vision(bad)


def test_unknown_confidence_defaults_to_low():
    items, _ = parse_vision('{"foods":[{"name":"米饭","grams":100,'
                            '"recognition_confidence":"确定","portion_confidence":"99%"}]}')
    assert items[0]['recognition_confidence'] == '低'
    assert items[0]['portion_confidence'] == '低'


def test_model_config_requires_https_and_complete_credentials():
    assert model_client_from_env({}) is None
    with pytest.raises(ValueError):
        model_client_from_env({'MODEL_BASE_URL': 'https://example/v1'})
    with pytest.raises(ValueError):
        model_client_from_env({'MODEL_BASE_URL': 'http://example/v1',
                               'MODEL_API_KEY': 'k', 'MODEL_NAME': 'm'})
    client = model_client_from_env({'MODEL_BASE_URL': 'https://example/v1/',
                                    'MODEL_API_KEY': 'k', 'MODEL_NAME': 'm'})
    assert client.config.base_url == 'https://example/v1'


def test_image_upload_is_resized_and_bounded():
    from PIL import Image
    import io
    out = io.BytesIO()
    Image.new('RGB', (4000, 3000), 'red').save(out, format='PNG')
    encoded, mime = prepare_image(out.getvalue(), 'image/png')
    assert mime == 'image/jpeg' and encoded
    with pytest.raises(ModelInputError):
        prepare_image(b'not-an-image', 'image/jpeg')
    with pytest.raises(ModelInputError):
        prepare_image(b'x', 'image/gif')


def test_context_without_profile_is_blocked_and_has_no_recipes(tmp_path):
    store = Store(tmp_path)
    value = prepare_context(store, '今天吃什么')
    assert value['blocked'] == '请先完成个人档案'
    assert value['available_recipes'] == []
    assert value['today']['recorded'] is False
    store.close()


@requires_loopback
def test_chat_and_vision_use_only_the_configured_endpoint():
    import asyncio

    def handler(request):
        assert request.url.host == 'model.example'
        assert request.headers['authorization'] == 'Bearer synthetic'
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"foods":[]}'}}],
                                         'usage': {'total_tokens': 7}})

    client = CloudModelClient(ModelConfig('https://model.example/v1', 'synthetic', 'm'),
                              transport=httpx.MockTransport(handler))
    result = asyncio.run(client.chat([{'role': 'user', 'content': 'hi'}]))
    assert result['content'] == '{"foods":[]}'
    assert result['usage']['total_tokens'] == 7


@requires_loopback
@pytest.mark.parametrize('status,expect', [(401, ModelUnavailable), (429, ModelUnavailable),
                                           (500, ModelUnavailable)])
def test_upstream_errors_are_sanitized(status, expect):
    import asyncio
    client = CloudModelClient(
        ModelConfig('https://model.example/v1', 'synthetic', 'm'),
        transport=httpx.MockTransport(lambda request: httpx.Response(
            status, json={'error': 'AccessKey=secret-value'})))
    with pytest.raises(expect) as error:
        asyncio.run(client.chat([{'role': 'user', 'content': 'hi'}]))
    assert 'secret-value' not in str(error.value)