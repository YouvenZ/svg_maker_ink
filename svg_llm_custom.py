#!/usr/bin/env python3
"""
Custom OpenAI-compatible provider for AI SVG Generator.

Supports any API server that implements the OpenAI Chat Completions interface,
e.g. LM Studio, LocalAI, vLLM, Groq, Together AI, Mistral, DeepSeek, etc.

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

PROVIDER_ID = 'custom_openai'
NAME = 'Custom (OpenAI-compatible)'
ENV_KEY = 'CUSTOM_OPENAI_API_KEY'
CONFIG_KEY = 'custom_openai_api_key'
DEFAULT_MODELS = ['custom-model']
NEEDS_ENDPOINT = True
ENDPOINT_PLACEHOLDER = 'http://localhost:1234/v1  or  https://api.groq.com/openai/v1'
SUPPORTS_SEED = True


def generate(prompt: str, system_prompt: str, opts: dict, api_key: str, ssl_context) -> str:
    """
    Call any OpenAI-compatible /chat/completions endpoint and return the raw text.

    opts keys used: model, temperature, max_tokens, timeout, seed, endpoint
    """
    endpoint = (opts.get('endpoint') or '').rstrip('/')
    if not endpoint.startswith(('http://', 'https://')):
        raise Exception(
            "Custom provider requires a valid base URL in the 'Endpoint' field "
            "(e.g. http://localhost:1234/v1 or https://api.groq.com/openai/v1)"
        )

    url = f'{endpoint}/chat/completions'
    headers = {
        'Content-Type': 'application/json',
    }
    # Include Authorization header if an API key was provided
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    data: dict = {
        'model': opts.get('model', 'custom-model'),
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
    # Use None for SSL context when connecting to http:// (local) endpoints
    ctx = None if endpoint.startswith('http://') else ssl_context
    try:
        with urllib.request.urlopen(req, timeout=int(opts.get('timeout', 60)),
                                    context=ctx) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            choices = result.get('choices', [])
            if choices:
                text = choices[0].get('message', {}).get('content', '').strip()
                return _clean(text)
            raise Exception('No content in custom provider response')
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        try:
            msg = json.loads(body).get('error', {}).get('message', str(e))
        except Exception:
            msg = body[:300]
        raise Exception(f'Custom provider API error ({e.code}): {msg}')
    except urllib.error.URLError as e:
        raise Exception(f'Custom provider network error: {e.reason}')


def fetch_models(api_key: str = '', endpoint: str = '', ssl_context=None) -> list:
    """
    Fetch model list from GET {endpoint}/models (OpenAI-compatible /v1/models).
    Falls back to DEFAULT_MODELS on failure.
    """
    if not endpoint:
        return DEFAULT_MODELS
    base = endpoint.rstrip('/')
    url = f'{base}/models'
    headers: dict = {}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    req = urllib.request.Request(url, headers=headers)
    ctx = None if base.startswith('http://') else ssl_context
    try:
        with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
            data = json.loads(resp.read().decode())
        models = [m['id'] for m in data.get('data', []) if m.get('id')]
        return models or DEFAULT_MODELS
    except Exception:
        return DEFAULT_MODELS


def _clean(svg_code: str) -> str:
    svg_code = re.sub(r'^```(?:svg|xml)?\s*\n?', '', svg_code, flags=re.MULTILINE)
    svg_code = re.sub(r'\n?```\s*$', '', svg_code, flags=re.MULTILINE)
    svg_code = re.sub(r'<\?xml[^>]+\?>\s*', '', svg_code)
    svg_code = re.sub(r'<!DOCTYPE[^>]+>\s*', '', svg_code)
    return svg_code.strip()
