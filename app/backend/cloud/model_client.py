"""Huawei Cloud model API adapter for OpenAI-compatible chat completions.

The endpoint and credentials come only from the deployment environment. Callers
can never supply a model URL, and upstream error text is never returned because it
may contain keys or internal addresses.
"""
from __future__ import annotations

import base64
import io
import os
from dataclasses import dataclass

import httpx

from app.backend.errors import AppError


class ModelUnavailable(AppError):
    def __init__(self, message='云端模型暂不可用，请稍后重试；手动记录仍可用'):
        super().__init__(message, 'model_unavailable', 503)


class ModelInputError(AppError):
    def __init__(self, message='照片或问题无法用于云端识别，请核对后重试'):
        super().__init__(message, 'model_input', 422)


@dataclass(frozen=True)
class ModelConfig:
    base_url: str
    api_key: str
    model: str
    vision_model: str = ''
    timeout: float = 60.0

    def validate(self):
        if not self.base_url.startswith('https://'):
            raise ValueError('MODEL_BASE_URL must use HTTPS')
        if self.base_url.endswith('/'):
            raise ValueError('MODEL_BASE_URL must not end with a slash')
        if not self.api_key or not self.model:
            raise ValueError('MODEL_API_KEY and MODEL_NAME are required')
        if not 1 <= self.timeout <= 300:
            raise ValueError('MODEL_TIMEOUT must be between 1 and 300 seconds')


def prepare_image(content: bytes, declared_mime: str, limit: int = 900 * 1024) -> tuple[str, str]:
    """Shrink to a bounded JPEG before sending; never forward the original file."""
    if not content or len(content) > 25 * 1024 * 1024 or declared_mime not in {'image/jpeg', 'image/png', 'image/webp'}:
        raise ModelInputError()
    try:
        from PIL import Image
        with Image.open(io.BytesIO(content)) as image:
            image.thumbnail((720, 720))
            out = io.BytesIO()
            image.convert('RGB').save(out, format='JPEG', quality=82)
        value = out.getvalue()
    except Exception:
        raise ModelInputError() from None
    if not 0 < len(value) <= limit:
        raise ModelInputError()
    return base64.b64encode(value).decode('ascii'), 'image/jpeg'


class CloudModelClient:
    def __init__(self, config: ModelConfig, transport=None):
        config.validate()
        self.config = config
        self._client = httpx.AsyncClient(
            base_url=config.base_url + '/',
            timeout=config.timeout,
            transport=transport,
            headers={'Authorization': f'Bearer {config.api_key}',
                     'Content-Type': 'application/json'},
        )

    async def close(self):
        await self._client.aclose()

    async def _complete(self, payload: dict) -> dict:
        try:
            response = await self._client.post('chat/completions', json=payload)
        except httpx.TimeoutException:
            raise ModelUnavailable('云端模型响应超时，请重试或手动记录') from None
        except httpx.HTTPError:
            raise ModelUnavailable() from None
        if response.status_code in {401, 403}:
            raise ModelUnavailable('云端模型凭据无效或未授权，请联系管理员检查配置')
        if response.status_code == 429:
            raise ModelUnavailable('云端模型调用频率受限，请稍后重试')
        if response.status_code >= 400:
            raise ModelUnavailable()
        try:
            data = response.json()
            content = data['choices'][0]['message']['content']
        except (ValueError, KeyError, IndexError, TypeError):
            raise ModelUnavailable('云端模型返回结构不完整，未生成结果') from None
        if not isinstance(content, str) or not content.strip():
            raise ModelUnavailable('云端模型返回空结果，未生成内容')
        return {'content': content.strip(), 'usage': data.get('usage') or {}}

    async def chat(self, messages: list, *, max_tokens: int = 600, temperature: float = 0.0) -> dict:
        if not isinstance(messages, list) or not messages:
            raise ModelInputError('缺少对话内容')
        return await self._complete({
            'model': self.config.model,
            'messages': messages,
            'temperature': temperature,
            'max_tokens': max_tokens,
            'stream': False,
        })

    async def vision(self, content: bytes, declared_mime: str, prompt: str, *, max_tokens: int = 700) -> dict:
        encoded, mime = prepare_image(content, declared_mime)
        model = self.config.vision_model or self.config.model
        return await self._complete({
            'model': model,
            'messages': [{'role': 'user', 'content': [
                {'type': 'text', 'text': prompt},
                {'type': 'image_url', 'image_url': {'url': f'data:{mime};base64,{encoded}'}},
            ]}],
            'temperature': 0.0,
            'max_tokens': max_tokens,
            'stream': False,
        })


def model_client_from_env(environ=None):
    values = os.environ if environ is None else environ
    base_url = (values.get('MODEL_BASE_URL') or '').strip()
    api_key = (values.get('MODEL_API_KEY') or '').strip()
    model = (values.get('MODEL_NAME') or '').strip()
    if not (base_url or api_key or model):
        return None
    if not (base_url and api_key and model):
        raise ValueError('MODEL_BASE_URL, MODEL_API_KEY and MODEL_NAME must be set together')
    try:
        timeout = float(values.get('MODEL_TIMEOUT', '60'))
    except (TypeError, ValueError):
        raise ValueError('MODEL_TIMEOUT must be a number') from None
    vision_model = (values.get('MODEL_VISION_NAME') or '').strip() or model
    config = ModelConfig(base_url=base_url.rstrip('/'), api_key=api_key, model=model,
                         vision_model=vision_model, timeout=timeout)
    config.validate()
    return CloudModelClient(config)