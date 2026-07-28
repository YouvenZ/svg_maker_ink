#!/usr/bin/env python3
"""
Custom OpenAI-compatible provider for AI SVG Generator.

Supports any API server that implements the OpenAI Chat Completions interface,
e.g. LM Studio, LocalAI, vLLM, Groq, Together AI, Mistral, DeepSeek, etc.

Exposes:
  PROVIDER_ID, NAME, ENV_KEY, CONFIG_KEY, DEFAULT_MODELS,
  NEEDS_ENDPOINT, ENDPOINT_PLACEHOLDER, SUPPORTS_SEED
  generate(prompt, system_prompt, opts, api_key, ssl_context,
           progress_cb=None) -> str
  fetch_models(api_key, endpoint='', ssl_context=None) -> list[str]
"""

from svg_llm_common import (
    PROVIDERS, clean_svg_response, http_get_json, http_post_json,
)
from svg_llm_openai import stream_chat_text

PROVIDER_ID = 'custom_openai'
NAME = PROVIDERS['custom_openai']['name']
ENV_KEY = PROVIDERS['custom_openai']['env_key']
CONFIG_KEY = PROVIDERS['custom_openai']['config_key']
DEFAULT_MODELS = PROVIDERS['custom_openai']['models']
NEEDS_ENDPOINT = True
ENDPOINT_PLACEHOLDER = PROVIDERS['custom_openai']['endpoint_placeholder']
SUPPORTS_SEED = True


def _build_payload(model, system_prompt, prompt, opts, stream=False):
    # Deliberately conservative: always classic max_tokens + temperature —
    # third-party OpenAI-compatible servers (llama.cpp, LM Studio, vLLM…)
    # commonly don't understand max_completion_tokens.
    data: dict = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user',   'content': prompt},
        ],
        'temperature': float(opts.get('temperature', 0.7)),
        'max_tokens':  int(opts.get('max_tokens', 4000)),
    }
    seed = int(opts.get('seed', -1))
    if seed >= 0:
        data['seed'] = seed
    if stream:
        data['stream'] = True
    return data


def generate(prompt: str, system_prompt: str, opts: dict, api_key: str,
             ssl_context, progress_cb=None) -> str:
    """
    Call any OpenAI-compatible /chat/completions endpoint and return the raw text.

    opts keys used: model, temperature, max_tokens, timeout, seed, endpoint
    progress_cb(chars_received) enables streaming with live progress.
    """
    endpoint = (opts.get('endpoint') or '').rstrip('/')
    if not endpoint.startswith(('http://', 'https://')):
        raise Exception(
            "Custom provider requires a valid base URL in the 'Endpoint' field "
            "(e.g. http://localhost:1234/v1 or https://api.groq.com/openai/v1)"
        )

    url = f'{endpoint}/chat/completions'
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    model = opts.get('model', 'custom-model')
    timeout = int(opts.get('timeout', 60))

    if progress_cb:
        data = _build_payload(model, system_prompt, prompt, opts, stream=True)
        text = stream_chat_text(url, headers, data, timeout, ssl_context,
                                'Custom provider', progress_cb)
        if text:
            return clean_svg_response(text)
        raise Exception('No content in custom provider streaming response')

    data = _build_payload(model, system_prompt, prompt, opts)
    result = http_post_json(url, headers, data, timeout, ssl_context,
                            'Custom provider')
    choices = result.get('choices', [])
    if choices:
        text = choices[0].get('message', {}).get('content', '').strip()
        if text:
            return clean_svg_response(text)
    raise Exception('No content in custom provider response')


def fetch_models(api_key: str = '', endpoint: str = '', ssl_context=None) -> list:
    """
    Fetch model list from GET {endpoint}/models (OpenAI-compatible /v1/models).
    Falls back to DEFAULT_MODELS on failure.
    """
    if not endpoint:
        return DEFAULT_MODELS
    base = endpoint.rstrip('/')
    headers = {}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    try:
        data = http_get_json(f'{base}/models', headers, 8, ssl_context)
        models = [m['id'] for m in data.get('data', []) if m.get('id')]
        return models or DEFAULT_MODELS
    except Exception:
        return DEFAULT_MODELS
