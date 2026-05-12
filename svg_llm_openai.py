#!/usr/bin/env python3
"""
OpenAI provider for AI SVG Generator.

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

PROVIDER_ID = 'openai'
NAME = 'OpenAI'
ENV_KEY = 'OPENAI_API_KEY'
CONFIG_KEY = 'openai_api_key'
DEFAULT_MODELS = [
    'gpt-4o',
    'gpt-4o-mini',
    'gpt-4-turbo',
    'gpt-4',
    'gpt-3.5-turbo',
    'o1',
    'o1-mini',
    'o3-mini',
]
NEEDS_ENDPOINT = False
ENDPOINT_PLACEHOLDER = ''
SUPPORTS_SEED = True

_BASE_URL = 'https://api.openai.com/v1'


def generate(prompt: str, system_prompt: str, opts: dict, api_key: str, ssl_context) -> str:
    """
    Call the OpenAI Chat Completions API and return the raw response text.

    opts keys used: model, temperature, max_tokens, timeout, seed
    """
    url = f'{_BASE_URL}/chat/completions'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}',
    }
    data: dict = {
        'model': opts.get('model', 'gpt-4o'),
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

    return _post_and_parse(url, headers, data, 'openai',
                           int(opts.get('timeout', 60)), ssl_context)


def fetch_models(api_key: str, endpoint: str = '', ssl_context=None) -> list:
    """
    Fetch the list of available model IDs from OpenAI's /v1/models endpoint.
    Returns an empty list if the request fails.
    """
    base = (endpoint.rstrip('/') if endpoint else _BASE_URL)
    url = f'{base}/models'
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {api_key}'})
    try:
        with urllib.request.urlopen(req, timeout=10, context=ssl_context) as resp:
            data = json.loads(resp.read().decode())
        models = [m['id'] for m in data.get('data', [])
                  if m.get('id', '').startswith(('gpt-', 'o1', 'o3', 'chatgpt'))]
        models.sort()
        return models or DEFAULT_MODELS
    except Exception:
        return DEFAULT_MODELS


# ── Internal helpers ───────────────────────────────────────────────────────────

def _post_and_parse(url, headers, data, parser, timeout, ssl_context):
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode('utf-8'),
        headers=headers,
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_context) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            return _parse(result, parser)
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        try:
            msg = json.loads(body).get('error', {}).get('message', str(e))
        except Exception:
            msg = body[:300]
        raise Exception(f'OpenAI API error ({e.code}): {msg}')
    except urllib.error.URLError as e:
        raise Exception(f'OpenAI network error: {e.reason}')


def _parse(result, parser):
    if parser == 'openai':
        choices = result.get('choices', [])
        if choices:
            text = choices[0].get('message', {}).get('content', '').strip()
            return _clean(text)
    raise Exception('No content in OpenAI response')


def _clean(svg_code: str) -> str:
    svg_code = re.sub(r'^```(?:svg|xml)?\s*\n?', '', svg_code, flags=re.MULTILINE)
    svg_code = re.sub(r'\n?```\s*$', '', svg_code, flags=re.MULTILINE)
    svg_code = re.sub(r'<\?xml[^>]+\?>\s*', '', svg_code)
    svg_code = re.sub(r'<!DOCTYPE[^>]+>\s*', '', svg_code)
    return svg_code.strip()
