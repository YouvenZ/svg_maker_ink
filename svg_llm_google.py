#!/usr/bin/env python3
"""
Google Gemini provider for AI SVG Generator.

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

PROVIDER_ID = 'google'
NAME = 'Google Gemini'
ENV_KEY = 'GOOGLE_API_KEY'
CONFIG_KEY = 'google_api_key'
DEFAULT_MODELS = [
    'gemini-2.0-flash',
    'gemini-2.0-flash-lite',
    'gemini-1.5-pro',
    'gemini-1.5-flash',
    'gemini-1.5-flash-8b',
]
NEEDS_ENDPOINT = False
ENDPOINT_PLACEHOLDER = ''
SUPPORTS_SEED = True

_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta'


def generate(prompt: str, system_prompt: str, opts: dict, api_key: str, ssl_context) -> str:
    """
    Call the Google Gemini generateContent API and return the raw response text.

    opts keys used: model, temperature, max_tokens, timeout, seed
    """
    model = opts.get('model', 'gemini-2.0-flash')
    if not model.startswith('gemini'):
        model = 'gemini-2.0-flash'

    url = f'{_BASE_URL}/models/{model}:generateContent?key={api_key}'
    headers = {'Content-Type': 'application/json'}

    generation_config: dict = {
        'temperature': float(opts.get('temperature', 0.7)),
        'maxOutputTokens': int(opts.get('max_tokens', 4000)),
    }
    seed = int(opts.get('seed', -1))
    if seed >= 0:
        generation_config['seed'] = seed

    data = {
        'systemInstruction': {
            'parts': [{'text': system_prompt}],
        },
        'contents': [
            {'parts': [{'text': prompt}]},
        ],
        'generationConfig': generation_config,
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
            candidates = result.get('candidates', [])
            if candidates:
                parts = candidates[0].get('content', {}).get('parts', [])
                if parts:
                    return _clean(parts[0].get('text', '').strip())
            raise Exception('No content in Gemini response')
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        try:
            err = json.loads(body)
            msg = err.get('error', {}).get('message', str(e))
        except Exception:
            msg = body[:300]
        raise Exception(f'Gemini API error ({e.code}): {msg}')
    except urllib.error.URLError as e:
        raise Exception(f'Gemini network error: {e.reason}')


def fetch_models(api_key: str, endpoint: str = '', ssl_context=None) -> list:
    """
    Fetch available Gemini model IDs that support generateContent.
    Falls back to DEFAULT_MODELS on failure.
    """
    url = f'{_BASE_URL}/models?key={api_key}'
    try:
        with urllib.request.urlopen(url, timeout=10, context=ssl_context) as resp:
            data = json.loads(resp.read().decode())
        models = []
        for m in data.get('models', []):
            name = m.get('name', '')  # e.g. "models/gemini-1.5-pro"
            supported = m.get('supportedGenerationMethods', [])
            if 'generateContent' in supported and name:
                short = name.split('/')[-1]
                if short.startswith('gemini'):
                    models.append(short)
        models.sort(reverse=True)
        return models or DEFAULT_MODELS
    except Exception:
        return DEFAULT_MODELS


def _clean(svg_code: str) -> str:
    svg_code = re.sub(r'^```(?:svg|xml)?\s*\n?', '', svg_code, flags=re.MULTILINE)
    svg_code = re.sub(r'\n?```\s*$', '', svg_code, flags=re.MULTILINE)
    svg_code = re.sub(r'<\?xml[^>]+\?>\s*', '', svg_code)
    svg_code = re.sub(r'<!DOCTYPE[^>]+>\s*', '', svg_code)
    return svg_code.strip()
