#!/usr/bin/env python3
"""
Anthropic Claude provider for AI SVG Generator.

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

PROVIDER_ID = 'anthropic'
NAME = PROVIDERS['anthropic']['name']
ENV_KEY = PROVIDERS['anthropic']['env_key']
CONFIG_KEY = PROVIDERS['anthropic']['config_key']
DEFAULT_MODELS = PROVIDERS['anthropic']['models']
NEEDS_ENDPOINT = False
ENDPOINT_PLACEHOLDER = ''
SUPPORTS_SEED = False  # Anthropic does not support seed

_BASE_URL = 'https://api.anthropic.com/v1'
_API_VERSION = '2023-06-01'

# Models released from Opus 4.7 onward reject the temperature parameter
# (400). Only send it to models known to accept it.
_TEMPERATURE_OK_PREFIXES = (
    'claude-3',
    'claude-opus-4-0', 'claude-opus-4-1', 'claude-opus-4-5', 'claude-opus-4-6',
    'claude-sonnet-4',   # sonnet-4-0 / 4-5 / 4-6 (NOT sonnet-5)
    'claude-haiku-4-5',
)


def _accepts_temperature(model: str) -> bool:
    return model.startswith(_TEMPERATURE_OK_PREFIXES)


def _build_payload(model, system_prompt, prompt, opts, stream=False):
    data: dict = {
        'model': model,
        'max_tokens': int(opts.get('max_tokens', 4000)),
        'system': system_prompt,
        'messages': [
            {'role': 'user', 'content': prompt},
        ],
    }
    if _accepts_temperature(model):
        data['temperature'] = float(opts.get('temperature', 0.7))
    if stream:
        data['stream'] = True
    return data


def generate(prompt: str, system_prompt: str, opts: dict, api_key: str,
             ssl_context, progress_cb=None) -> str:
    """
    Call the Anthropic Messages API and return the raw response text.

    opts keys used: model, temperature (older models only), max_tokens, timeout
    progress_cb(chars_received) enables streaming with live progress.
    Note: seed is not supported by Anthropic.
    """
    model = opts.get('model', 'claude-opus-4-8')
    if not model.startswith('claude'):
        raise Exception(
            f"'{model}' is not an Anthropic model. Pick a claude-* model in "
            "the Model tab (use ⟳ Refresh to fetch the current list)."
        )

    url = f'{_BASE_URL}/messages'
    headers = {
        'Content-Type': 'application/json',
        'x-api-key': api_key,
        'anthropic-version': _API_VERSION,
    }
    timeout = int(opts.get('timeout', 60))

    if progress_cb:
        data = _build_payload(model, system_prompt, prompt, opts, stream=True)
        parts = []
        total = 0
        for event in http_post_stream(url, headers, data, timeout,
                                      ssl_context, 'Anthropic'):
            etype = event.get('type')
            if etype == 'content_block_delta':
                piece = (event.get('delta') or {}).get('text')
                if piece:
                    parts.append(piece)
                    total += len(piece)
                    progress_cb(total)
            elif etype == 'error':
                err = event.get('error') or {}
                raise Exception(
                    f"Anthropic API error: {err.get('message', 'unknown error')}"
                )
        text = ''.join(parts).strip()
        if text:
            return clean_svg_response(text)
        raise Exception('No content in Anthropic streaming response')

    data = _build_payload(model, system_prompt, prompt, opts)
    result = http_post_json(url, headers, data, timeout, ssl_context, 'Anthropic')
    content = result.get('content', [])
    for block in content:
        if block.get('type') == 'text' and block.get('text'):
            return clean_svg_response(block['text'].strip())
    raise Exception('No content in Anthropic response')


def fetch_models(api_key: str, endpoint: str = '', ssl_context=None) -> list:
    """
    Fetch available Claude models from the Anthropic /v1/models endpoint.
    Falls back to DEFAULT_MODELS if the request fails or returns nothing.
    """
    base = (endpoint.rstrip('/') if endpoint else _BASE_URL)
    try:
        data = http_get_json(
            f'{base}/models',
            {'x-api-key': api_key, 'anthropic-version': _API_VERSION},
            10, ssl_context,
        )
        models = [m['id'] for m in data.get('data', []) if m.get('id')]
        models.sort(reverse=True)  # newest first
        return models or DEFAULT_MODELS
    except Exception:
        return DEFAULT_MODELS
