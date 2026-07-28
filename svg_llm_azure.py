#!/usr/bin/env python3
"""
Azure OpenAI provider for AI SVG Generator.

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
from svg_llm_openai import build_chat_payload, stream_chat_text

PROVIDER_ID = 'azure'
NAME = PROVIDERS['azure']['name']
ENV_KEY = PROVIDERS['azure']['env_key']
CONFIG_KEY = PROVIDERS['azure']['config_key']
DEFAULT_MODELS = PROVIDERS['azure']['models']
NEEDS_ENDPOINT = True
ENDPOINT_PLACEHOLDER = PROVIDERS['azure']['endpoint_placeholder']
SUPPORTS_SEED = True

_API_VERSION = '2024-08-01-preview'


def generate(prompt: str, system_prompt: str, opts: dict, api_key: str,
             ssl_context, progress_cb=None) -> str:
    """
    Call Azure OpenAI chat completions endpoint and return the raw response text.

    opts keys used: model (deployment name), temperature, max_tokens,
    timeout, seed, endpoint
    progress_cb(chars_received) enables streaming with live progress.
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
    timeout = int(opts.get('timeout', 60))
    # Azure payload matches OpenAI chat/completions except that the model is
    # addressed via the deployment URL — 'model' in the body is ignored.
    data = build_chat_payload(deployment, system_prompt, prompt, opts,
                              stream=bool(progress_cb))
    data.pop('model', None)

    if progress_cb:
        text = stream_chat_text(url, headers, data, timeout, ssl_context,
                                'Azure OpenAI', progress_cb)
        if text:
            return clean_svg_response(text)
        raise Exception('No content in Azure OpenAI streaming response')

    result = http_post_json(url, headers, data, timeout, ssl_context,
                            'Azure OpenAI')
    choices = result.get('choices', [])
    if choices:
        text = choices[0].get('message', {}).get('content', '').strip()
        if text:
            return clean_svg_response(text)
    raise Exception('No content in Azure OpenAI response')


def fetch_models(api_key: str, endpoint: str = '', ssl_context=None) -> list:
    """
    Fetch deployment names from Azure OpenAI's /openai/models endpoint.
    Falls back to DEFAULT_MODELS on failure.
    """
    if not endpoint:
        return DEFAULT_MODELS
    base = endpoint.rstrip('/')
    try:
        data = http_get_json(
            f'{base}/openai/models?api-version={_API_VERSION}',
            {'api-key': api_key},
            10, ssl_context,
        )
        models = [m['id'] for m in data.get('value', data.get('data', []))
                  if m.get('id')]
        return models or DEFAULT_MODELS
    except Exception:
        return DEFAULT_MODELS
