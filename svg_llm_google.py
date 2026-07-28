#!/usr/bin/env python3
"""
Google Gemini provider for AI SVG Generator.

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

PROVIDER_ID = 'google'
NAME = PROVIDERS['google']['name']
ENV_KEY = PROVIDERS['google']['env_key']
CONFIG_KEY = PROVIDERS['google']['config_key']
DEFAULT_MODELS = PROVIDERS['google']['models']
NEEDS_ENDPOINT = False
ENDPOINT_PLACEHOLDER = ''
SUPPORTS_SEED = True

_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta'


def generate(prompt: str, system_prompt: str, opts: dict, api_key: str,
             ssl_context, progress_cb=None) -> str:
    """
    Call the Google Gemini generateContent API and return the raw response text.

    opts keys used: model, temperature, max_tokens, timeout, seed
    progress_cb is accepted for interface parity but streaming is not used.
    """
    model = opts.get('model', 'gemini-2.5-flash')
    if not model.startswith('gemini'):
        raise Exception(
            f"'{model}' is not a Gemini model. Pick a gemini-* model in "
            "the Model tab (use ⟳ Refresh to fetch the current list)."
        )

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

    result = http_post_json(url, headers, data, int(opts.get('timeout', 60)),
                            ssl_context, 'Gemini')
    candidates = result.get('candidates', [])
    if candidates:
        parts = candidates[0].get('content', {}).get('parts', [])
        text = ''.join(p.get('text', '') for p in parts).strip()
        if text:
            return clean_svg_response(text)
    raise Exception('No content in Gemini response')


def fetch_models(api_key: str, endpoint: str = '', ssl_context=None) -> list:
    """
    Fetch available Gemini model IDs that support generateContent.
    Falls back to DEFAULT_MODELS on failure.
    """
    try:
        data = http_get_json(f'{_BASE_URL}/models?key={api_key}', {},
                             10, ssl_context)
        models = []
        for m in data.get('models', []):
            name = m.get('name', '')  # e.g. "models/gemini-2.5-pro"
            supported = m.get('supportedGenerationMethods', [])
            if 'generateContent' in supported and name:
                short = name.split('/')[-1]
                if short.startswith('gemini'):
                    models.append(short)
        models.sort(reverse=True)
        return models or DEFAULT_MODELS
    except Exception:
        return DEFAULT_MODELS
