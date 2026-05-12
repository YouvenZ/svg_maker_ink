#!/usr/bin/env python3
"""
Azure OpenAI provider for AI SVG Generator.

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

PROVIDER_ID = 'azure'
NAME = 'Azure OpenAI'
ENV_KEY = 'AZURE_OPENAI_API_KEY'
CONFIG_KEY = 'azure_openai_api_key'
DEFAULT_MODELS = [
    'gpt-4o',
    'gpt-4-turbo',
    'gpt-35-turbo',
]
NEEDS_ENDPOINT = True
ENDPOINT_PLACEHOLDER = 'https://your-resource.openai.azure.com'
SUPPORTS_SEED = True

_API_VERSION = '2024-08-01-preview'


def generate(prompt: str, system_prompt: str, opts: dict, api_key: str, ssl_context) -> str:
    """
    Call Azure OpenAI chat completions endpoint and return the raw response text.

    opts keys used: model (deployment name), temperature, max_tokens, timeout, seed, endpoint
    """
    endpoint = (opts.get('endpoint') or '').rstrip('/')
    if not endpoint.startswith(('http://', 'https://')):
        raise Exception(
            "Azure OpenAI requires a valid endpoint URL in the 'Endpoint' field "
            "(e.g. https://your-resource.openai.azure.com)"
        )

    deployment = opts.get('model', 'gpt-4o')
    url = (
        f'{endpoint}/openai/deployments/{deployment}'
        f'/chat/completions?api-version={_API_VERSION}'
    )
    headers = {
        'Content-Type': 'application/json',
        'api-key': api_key,
    }
    data: dict = {
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
            choices = result.get('choices', [])
            if choices:
                text = choices[0].get('message', {}).get('content', '').strip()
                return _clean(text)
            raise Exception('No content in Azure OpenAI response')
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        try:
            msg = json.loads(body).get('error', {}).get('message', str(e))
        except Exception:
            msg = body[:300]
        raise Exception(f'Azure OpenAI API error ({e.code}): {msg}')
    except urllib.error.URLError as e:
        raise Exception(f'Azure OpenAI network error: {e.reason}')


def fetch_models(api_key: str, endpoint: str = '', ssl_context=None) -> list:
    """
    Fetch deployment names from Azure OpenAI's /openai/models endpoint.
    Falls back to DEFAULT_MODELS on failure.
    """
    if not endpoint:
        return DEFAULT_MODELS
    base = endpoint.rstrip('/')
    url = f'{base}/openai/models?api-version={_API_VERSION}'
    req = urllib.request.Request(url, headers={'api-key': api_key})
    try:
        with urllib.request.urlopen(req, timeout=10, context=ssl_context) as resp:
            data = json.loads(resp.read().decode())
        models = [m['id'] for m in data.get('value', data.get('data', []))
                  if m.get('id')]
        return models or DEFAULT_MODELS
    except Exception:
        return DEFAULT_MODELS


def _clean(svg_code: str) -> str:
    svg_code = re.sub(r'^```(?:svg|xml)?\s*\n?', '', svg_code, flags=re.MULTILINE)
    svg_code = re.sub(r'\n?```\s*$', '', svg_code, flags=re.MULTILINE)
    svg_code = re.sub(r'<\?xml[^>]+\?>\s*', '', svg_code)
    svg_code = re.sub(r'<!DOCTYPE[^>]+>\s*', '', svg_code)
    return svg_code.strip()
