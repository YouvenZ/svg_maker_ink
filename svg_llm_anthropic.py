#!/usr/bin/env python3
"""
Anthropic Claude provider for AI SVG Generator.

Exposes:
  PROVIDER_ID, NAME, ENV_KEY, CONFIG_KEY, DEFAULT_MODELS,
  NEEDS_ENDPOINT, ENDPOINT_PLACEHOLDER, SUPPORTS_SEED
  generate(prompt, system_prompt, opts, api_key, ssl_context) -> str
  fetch_models(api_key, endpoint='', ssl_context=None) -> list[str]
"""

import json
import urllib.request
import urllib.error
import re

PROVIDER_ID = 'anthropic'
NAME = 'Anthropic Claude'
ENV_KEY = 'ANTHROPIC_API_KEY'
CONFIG_KEY = 'anthropic_api_key'
DEFAULT_MODELS = [
    'claude-opus-4-5',
    'claude-sonnet-4-5',
    'claude-3-5-sonnet-20241022',
    'claude-3-5-haiku-20241022',
    'claude-3-opus-20240229',
    'claude-3-haiku-20240307',
]
NEEDS_ENDPOINT = False
ENDPOINT_PLACEHOLDER = ''
SUPPORTS_SEED = False  # Anthropic does not support seed

_BASE_URL = 'https://api.anthropic.com/v1'
_API_VERSION = '2023-06-01'


def generate(prompt: str, system_prompt: str, opts: dict, api_key: str, ssl_context) -> str:
    """
    Call the Anthropic Messages API and return the raw response text.

    opts keys used: model, temperature, max_tokens, timeout
    Note: seed is not supported by Anthropic.
    """
    model = opts.get('model', 'claude-3-5-sonnet-20241022')
    if not model.startswith('claude'):
        model = 'claude-3-5-sonnet-20241022'

    url = f'{_BASE_URL}/messages'
    headers = {
        'Content-Type': 'application/json',
        'x-api-key': api_key,
        'anthropic-version': _API_VERSION,
    }
    data: dict = {
        'model': model,
        'max_tokens': int(opts.get('max_tokens', 4000)),
        'system': system_prompt,
        'messages': [
            {'role': 'user', 'content': prompt},
        ],
        'temperature': float(opts.get('temperature', 0.7)),
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode('utf-8'),
        headers=headers,
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=int(opts.get('timeout', 60)),
                                    context=ssl_context) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            content = result.get('content', [])
            if content:
                text = content[0].get('text', '').strip()
                return _clean(text)
            raise Exception('No content in Anthropic response')
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        try:
            msg = json.loads(body).get('error', {}).get('message', str(e))
        except Exception:
            msg = body[:300]
        raise Exception(f'Anthropic API error ({e.code}): {msg}')
    except urllib.error.URLError as e:
        raise Exception(f'Anthropic network error: {e.reason}')


def fetch_models(api_key: str, endpoint: str = '', ssl_context=None) -> list:
    """
    Fetch available Claude models from the Anthropic /v1/models endpoint.
    Falls back to DEFAULT_MODELS if the request fails or returns nothing useful.
    """
    base = (endpoint.rstrip('/') if endpoint else _BASE_URL)
    url = f'{base}/models'
    req = urllib.request.Request(
        url,
        headers={
            'x-api-key': api_key,
            'anthropic-version': _API_VERSION,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10, context=ssl_context) as resp:
            data = json.loads(resp.read().decode())
        models = [m['id'] for m in data.get('data', []) if m.get('id')]
        models.sort(reverse=True)  # newest first
        return models or DEFAULT_MODELS
    except Exception:
        return DEFAULT_MODELS


def _clean(svg_code: str) -> str:
    svg_code = re.sub(r'^```(?:svg|xml)?\s*\n?', '', svg_code, flags=re.MULTILINE)
    svg_code = re.sub(r'\n?```\s*$', '', svg_code, flags=re.MULTILINE)
    svg_code = re.sub(r'<\?xml[^>]+\?>\s*', '', svg_code)
    svg_code = re.sub(r'<!DOCTYPE[^>]+>\s*', '', svg_code)
    return svg_code.strip()
