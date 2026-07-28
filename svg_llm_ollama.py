#!/usr/bin/env python3
"""
Ollama (local) provider for AI SVG Generator.

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

PROVIDER_ID = 'ollama'
NAME = PROVIDERS['ollama']['name']
ENV_KEY = ''
CONFIG_KEY = ''
DEFAULT_MODELS = PROVIDERS['ollama']['models']
NEEDS_ENDPOINT = True
ENDPOINT_PLACEHOLDER = PROVIDERS['ollama']['endpoint_placeholder']
SUPPORTS_SEED = True

_DEFAULT_ENDPOINT = 'http://localhost:11434'


def _build_payload(model, system_prompt, prompt, opts, stream=False):
    ollama_options: dict = {
        'temperature': float(opts.get('temperature', 0.7)),
        'num_predict': int(opts.get('max_tokens', 4000)),
    }
    seed = int(opts.get('seed', -1))
    if seed >= 0:
        ollama_options['seed'] = seed
    return {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user',   'content': prompt},
        ],
        'stream': stream,
        'options': ollama_options,
    }


def generate(prompt: str, system_prompt: str, opts: dict, api_key: str,
             ssl_context, progress_cb=None) -> str:
    """
    Call the Ollama Chat API (/api/chat) and return the raw response text.

    opts keys used: model, temperature, max_tokens, timeout, seed, endpoint
    progress_cb(chars_received) enables streaming with live progress.
    """
    endpoint = (opts.get('endpoint') or _DEFAULT_ENDPOINT).rstrip('/')
    if not endpoint.startswith(('http://', 'https://')):
        raise Exception(
            f"Invalid Ollama endpoint: '{endpoint}'. Must start with http:// or https://"
        )

    model = opts.get('model', 'llama3.2')
    if model.startswith(('gpt-', 'claude', 'gemini')):
        raise Exception(
            f"'{model}' is a cloud model name — Ollama runs local models. "
            "Pick one of your installed models (use ⟳ Refresh to list them)."
        )

    url = f'{endpoint}/api/chat'
    headers = {'Content-Type': 'application/json'}
    timeout = int(opts.get('timeout', 60))

    if progress_cb:
        data = _build_payload(model, system_prompt, prompt, opts, stream=True)
        parts = []
        total = 0
        # Ollama streams NDJSON: one JSON object per line
        for event in http_post_stream(url, headers, data, timeout,
                                      ssl_context, 'Ollama'):
            if event.get('error'):
                raise Exception(f"Ollama API error: {event['error']}")
            piece = (event.get('message') or {}).get('content', '')
            if piece:
                parts.append(piece)
                total += len(piece)
                progress_cb(total)
            if event.get('done'):
                break
        text = ''.join(parts).strip()
        if text:
            return clean_svg_response(text)
        raise Exception('No content in Ollama streaming response')

    data = _build_payload(model, system_prompt, prompt, opts)
    result = http_post_json(url, headers, data, timeout, ssl_context, 'Ollama')
    text = (result.get('message') or {}).get('content', '').strip()
    if not text:
        # Fallback: /api/generate response shape
        text = result.get('response', '').strip()
    if text:
        return clean_svg_response(text)
    raise Exception('No content in Ollama response')


def fetch_models(api_key: str = '', endpoint: str = '', ssl_context=None) -> list:
    """
    Fetch locally installed model names from GET {endpoint}/api/tags.
    Falls back to DEFAULT_MODELS on failure.
    """
    base = (endpoint.rstrip('/') if endpoint else _DEFAULT_ENDPOINT)
    try:
        data = http_get_json(f'{base}/api/tags', {}, 5, ssl_context)
        models = [m['name'] for m in data.get('models', []) if m.get('name')]
        return models or DEFAULT_MODELS
    except Exception:
        return DEFAULT_MODELS
