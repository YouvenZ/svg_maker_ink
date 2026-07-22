#!/usr/bin/env python3
"""
OpenAI provider for AI SVG Generator.

Exposes:
  PROVIDER_ID, NAME, ENV_KEY, CONFIG_KEY, DEFAULT_MODELS,
  NEEDS_ENDPOINT, ENDPOINT_PLACEHOLDER, SUPPORTS_SEED
  generate(prompt, system_prompt, opts, api_key, ssl_context,
           progress_cb=None) -> str
  fetch_models(api_key, endpoint='', ssl_context=None) -> list[str]
"""

from svg_llm_common import (
    PROVIDERS, clean_svg_response, http_get_json, http_post_json,
    http_post_stream,
)

PROVIDER_ID = 'openai'
NAME = PROVIDERS['openai']['name']
ENV_KEY = PROVIDERS['openai']['env_key']
CONFIG_KEY = PROVIDERS['openai']['config_key']
DEFAULT_MODELS = PROVIDERS['openai']['models']
NEEDS_ENDPOINT = False
ENDPOINT_PLACEHOLDER = ''
SUPPORTS_SEED = True

_BASE_URL = 'https://api.openai.com/v1'

# Reasoning models use max_completion_tokens and reject a custom temperature.
_REASONING_PREFIXES = ('o1', 'o3', 'o4', 'gpt-5')


def _is_reasoning_model(model: str) -> bool:
    return model.startswith(_REASONING_PREFIXES)


def build_chat_payload(model: str, system_prompt: str, prompt: str,
                       opts: dict, stream: bool = False) -> dict:
    """
    Build an OpenAI-compatible chat/completions payload with correct
    per-model parameter handling. Shared with the Azure provider.
    """
    data: dict = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user',   'content': prompt},
        ],
    }
    if _is_reasoning_model(model):
        # Reasoning models: max_completion_tokens, default temperature only.
        data['max_completion_tokens'] = int(opts.get('max_tokens', 4000))
    else:
        data['max_tokens'] = int(opts.get('max_tokens', 4000))
        data['temperature'] = float(opts.get('temperature', 0.7))
    seed = int(opts.get('seed', -1))
    if seed >= 0:
        data['seed'] = seed
    if stream:
        data['stream'] = True
    return data


def stream_chat_text(url, headers, data, timeout, ssl_context,
                     provider_label, progress_cb):
    """
    Consume an OpenAI-compatible streaming chat response, reporting
    progress via progress_cb(total_chars). Returns the full text.
    Shared with the Azure and custom-endpoint providers.
    """
    parts = []
    total = 0
    for event in http_post_stream(url, headers, data, timeout,
                                  ssl_context, provider_label):
        choices = event.get('choices') or []
        if not choices:
            continue
        delta = choices[0].get('delta') or {}
        piece = delta.get('content')
        if piece:
            parts.append(piece)
            total += len(piece)
            if progress_cb:
                progress_cb(total)
    return ''.join(parts).strip()


def generate(prompt: str, system_prompt: str, opts: dict, api_key: str,
             ssl_context, progress_cb=None) -> str:
    """
    Call the OpenAI Chat Completions API and return the raw response text.

    opts keys used: model, temperature, max_tokens, timeout, seed
    progress_cb(chars_received) enables streaming with live progress.
    """
    model = opts.get('model', 'gpt-5.1')
    url = f'{_BASE_URL}/chat/completions'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}',
    }
    timeout = int(opts.get('timeout', 60))

    if progress_cb:
        data = build_chat_payload(model, system_prompt, prompt, opts, stream=True)
        text = stream_chat_text(url, headers, data, timeout, ssl_context,
                                'OpenAI', progress_cb)
        if text:
            return clean_svg_response(text)
        raise Exception('No content in OpenAI streaming response')

    data = build_chat_payload(model, system_prompt, prompt, opts)
    result = http_post_json(url, headers, data, timeout, ssl_context, 'OpenAI')
    choices = result.get('choices', [])
    if choices:
        text = choices[0].get('message', {}).get('content', '').strip()
        if text:
            return clean_svg_response(text)
    raise Exception('No content in OpenAI response')


def fetch_models(api_key: str, endpoint: str = '', ssl_context=None) -> list:
    """
    Fetch the list of available model IDs from OpenAI's /v1/models endpoint.
    Falls back to DEFAULT_MODELS if the request fails.
    """
    base = (endpoint.rstrip('/') if endpoint else _BASE_URL)
    try:
        data = http_get_json(
            f'{base}/models',
            {'Authorization': f'Bearer {api_key}'},
            10, ssl_context,
        )
        models = [m['id'] for m in data.get('data', [])
                  if m.get('id', '').startswith(('gpt-', 'o1', 'o3', 'o4', 'chatgpt'))]
        models.sort(reverse=True)
        return models or DEFAULT_MODELS
    except Exception:
        return DEFAULT_MODELS
