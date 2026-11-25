import asyncio
import json
import subprocess
import sys

import httpx
import pytest

from app.backend.cloud.ai_model import PrivateModel, model_from_env
from app.backend.errors import AppError


@pytest.mark.parametrize('url', ['https://public.example.com','http://169.254.169.254',
    'http://user:secret@10.0.0.2','http://10.0.0.2/path','http://10.0.0.2?token=secret'])
def test_private_model_refuses_public_metadata_or_credential_endpoints(url):
    with pytest.raises(ValueError):PrivateModel(url,'test')


def test_structured_model_and_sanitized_failure():
    def respond(request):
        body=json.loads(request.content)
        assert body['stream'] is False and body['format']['additionalProperties'] is False
        return httpx.Response(200,json={'message':{'content':json.dumps(
            {'intent':'protein','steps':['check_records'],'recipe_ids':[]})}})
    model=PrivateModel('http://10.0.0.2:11434','test',transport=httpx.MockTransport(respond))
    payload={'question':'测试','context':{},'candidates':[]}
    assert asyncio.run(model.chat(payload))['intent']=='protein'
    model.transport=httpx.MockTransport(lambda r:httpx.Response(500,text='secret-upstream-error'))
    with pytest.raises(AppError) as error:asyncio.run(model.chat(payload))
    assert 'secret' not in error.value.message
    assert model_from_env({}) is None


def test_cloud_import_does_not_load_windows_model_launcher():
    code="import sys; import app.backend.cloud.ai_tasks; assert 'app.scripts.model_runtime' not in sys.modules"
    result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
