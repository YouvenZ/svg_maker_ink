#!/usr/bin/env python3
"""
Ollama (local) provider for AI SVG Generator.

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

PROVIDER_ID = 'ollama'
NAME = 'Ollama (Local)'
ENV_KEY = ''
CONFIG_KEY = ''
DEFAULT_MODELS = [
    'llama3.2',
    'llama3.1',
    'qwen2.5-coder',
    'codellama',
    'mistral',
    'phi3',
]
NEEDS_ENDPOINT = True
ENDPOINT_PLACEHOLDER = 'http://localhost:11434'
SUPPORTS_SEED = True

_DEFAULT_ENDPOINT = 'http://localhost:11434'


def generate(prompt: str, system_prompt: str, opts: dict, api_key: str, ssl_context) -> str:
    """
    Call the Ollama Chat API (/api/chat) and return the raw response text.

    opts keys used: model, temperature, max_tokens, timeout, seed, endpoint
    """
    endpoint = (opts.get('endpoint') or _DEFAULT_ENDPOINT).rstrip('/')
    if not endpoint.startswith(('http://', 'https://')):
        raise Exception(
            f"Invalid Ollama endpoint: '{endpoint}'. Must start with http:// or https://"
        )

    model = opts.get('model', 'llama3.2')
    # Guard against accidentally using a cloud model name
    if model.startswith(('gpt-', 'claude', 'gemini')):
        model = 'llama3.2'

    url = f'{endpoint}/api/chat'
    headers = {'Content-Type': 'application/json'}

    ollama_options: dict = {
        'temperature': float(opts.get('temperature', 0.7)),
        'num_predict': int(opts.get('max_tokens', 4000)),
    }
    seed = int(opts.get('seed', -1))
    if seed >= 0:
        ollama_options['seed'] = seed

    data = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user',   'content': prompt},
        ],
        'stream': False,
        'options': ollama_options,
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
            # /api/chat response
            message = result.get('message', {})
            text = message.get('content', '').strip()
            if text:
                return _clean(text)
            # Fallback: /api/generate response shape
            text = result.get('response', '').strip()
            if text:
                return _clean(text)
            raise Exception('No content in Ollama response')
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        raise Exception(f'Ollama API error ({e.code}): {body[:300]}')
    except urllib.error.URLError as e:
        raise Exception(f'Ollama network error: {e.reason}')


def fetch_models(api_key: str = '', endpoint: str = '', ssl_context=None) -> list:
    """
    Fetch locally installed model names from GET {endpoint}/api/tags.
    Falls back to DEFAULT_MODELS on failure.
    """
    base = (endpoint.rstrip('/') if endpoint else _DEFAULT_ENDPOINT)
    url = f'{base}/api/tags'
    try:
        with urllib.request.urlopen(url, timeout=5, context=ssl_context) as resp:
            data = json.loads(resp.read().decode())
        models = [m['name'] for m in data.get('models', []) if m.get('name')]
        return models or DEFAULT_MODELS
    except Exception:
        return DEFAULT_MODELS


def _clean(svg_code: str) -> str:
    svg_code = re.sub(r'^```(?:svg|xml)?\s*\n?', '', svg_code, flags=re.MULTILINE)
    svg_code = re.sub(r'\n?```\s*$', '', svg_code, flags=re.MULTILINE)
    svg_code = re.sub(r'<\?xml[^>]+\?>\s*', '', svg_code)
    svg_code = re.sub(r'<!DOCTYPE[^>]+>\s*', '', svg_code)
    return svg_code.strip()
