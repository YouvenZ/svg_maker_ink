#!/usr/bin/env python3
"""
Shared utilities for the AI SVG Generator Inkscape extension.

This module is deliberately free of inkex / GTK imports so that it can be
unit-tested with any system Python and imported by every other module
(main extension, dialog, provider modules, test script).

Contents:
  PROVIDERS            — single source of truth for the provider registry
  build_ssl_context()  — verified SSL context (certifi when available)
  clean_svg_response() — strip markdown fences / XML decl, isolate <svg>…</svg>
  sanitize_svg()       — remove scripts, event handlers, foreignObject, js: URIs
  http_post_json()     — POST JSON + parse response, unified error messages
  http_get_json()      — GET + parse JSON
  http_post_stream()   — POST with SSE / NDJSON streaming, yields parsed events
"""

import json
import re
import ssl
import urllib.error
import urllib.request


# ==================== PROVIDER REGISTRY ====================
# The only place provider metadata is defined. svg_llm.py and
# svg_llm_dialog.py import this — do not duplicate it elsewhere.

PROVIDERS = {
    'openai': {
        'name': 'OpenAI',
        'module': 'svg_llm_openai',
        'env_key': 'OPENAI_API_KEY',
        'config_key': 'openai_api_key',
        'models': ['gpt-5.1', 'gpt-5', 'gpt-5-mini', 'gpt-4.1', 'gpt-4o',
                   'o3', 'o4-mini'],
        'supports_seed': True,
        'needs_endpoint': False,
        'endpoint_placeholder': '',
        'supports_fetch_models': True,
        'supports_stream': True,
        'keyless': False,
    },
    'anthropic': {
        'name': 'Anthropic Claude',
        'module': 'svg_llm_anthropic',
        'env_key': 'ANTHROPIC_API_KEY',
        'config_key': 'anthropic_api_key',
        'models': [
            'claude-opus-4-8',
            'claude-sonnet-5',
            'claude-haiku-4-5',
            'claude-opus-4-6',
            'claude-sonnet-4-6',
            'claude-opus-4-5',
        ],
        'supports_seed': False,
        'needs_endpoint': False,
        'endpoint_placeholder': '',
        'supports_fetch_models': True,
        'supports_stream': True,
        'keyless': False,
    },
    'google': {
        'name': 'Google Gemini',
        'module': 'svg_llm_google',
        'env_key': 'GOOGLE_API_KEY',
        'config_key': 'google_api_key',
        'models': ['gemini-2.5-pro', 'gemini-2.5-flash',
                   'gemini-2.5-flash-lite', 'gemini-2.0-flash'],
        'supports_seed': True,
        'needs_endpoint': False,
        'endpoint_placeholder': '',
        'supports_fetch_models': True,
        'supports_stream': False,
        'keyless': False,
    },
    'azure': {
        'name': 'Azure OpenAI',
        'module': 'svg_llm_azure',
        'env_key': 'AZURE_OPENAI_API_KEY',
        'config_key': 'azure_openai_api_key',
        'models': ['gpt-4o', 'gpt-4.1', 'gpt-35-turbo'],
        'supports_seed': True,
        'needs_endpoint': True,
        'endpoint_placeholder': 'https://your-resource.openai.azure.com',
        'supports_fetch_models': True,
        'supports_stream': True,
        'keyless': False,
    },
    'ollama': {
        'name': 'Ollama (Local)',
        'module': 'svg_llm_ollama',
        'env_key': '',
        'config_key': '',
        'models': ['llama3.2', 'llama3.1', 'qwen2.5-coder', 'codellama',
                   'mistral', 'phi3'],
        'supports_seed': True,
        'needs_endpoint': True,
        'endpoint_placeholder': 'http://localhost:11434',
        'supports_fetch_models': True,
        'supports_stream': True,
        'keyless': True,
    },
    'custom_openai': {
        'name': 'Custom (OpenAI-compatible)',
        'module': 'svg_llm_custom',
        'env_key': 'CUSTOM_OPENAI_API_KEY',
        'config_key': 'custom_openai_api_key',
        'models': ['custom-model'],
        'supports_seed': True,
        'needs_endpoint': True,
        'endpoint_placeholder': 'http://localhost:1234/v1  or  https://api.groq.com/openai/v1',
        'supports_fetch_models': True,
        'supports_stream': True,
        'keyless': False,
    },
    'claude_code': {
        'name': 'Claude Code (CLI)',
        'module': 'svg_llm_claude_code',
        'env_key': '',
        'config_key': '',
        'models': ['default', 'opus', 'sonnet', 'haiku'],
        'supports_seed': False,
        'needs_endpoint': True,
        'endpoint_placeholder': '(optional) full path to the claude CLI — leave blank to auto-detect',
        'supports_fetch_models': True,
        'supports_stream': False,
        'keyless': True,
    },
}


# ==================== SSL ====================

def build_ssl_context():
    """
    Return an SSL context that performs full certificate verification.
    Prefers certifi's CA bundle when available (reliable inside Inkscape's
    bundled Python on Windows); falls back to the system default context.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    return ssl.create_default_context()


# ==================== SVG POST-PROCESSING ====================

def clean_svg_response(text):
    """
    Normalize a raw model response into bare SVG source:
    - strip markdown code fences (```svg / ```xml / ```)
    - strip <?xml?> declaration and <!DOCTYPE>
    - if the model added narration around the SVG, isolate <svg>…</svg>
    """
    if not text:
        return ''
    text = re.sub(r'^```(?:svg|xml)?\s*\n?', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n?```\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'<\?xml[^>]+\?>\s*', '', text)
    text = re.sub(r'<!DOCTYPE[^>]+>\s*', '', text)
    text = text.replace('&nbsp;', ' ')
    text = re.sub(r'xmlns=""', '', text)
    match = re.search(r'<svg[\s>].*</svg>', text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(0).strip()
    return text.strip()


# Patterns for sanitize_svg — model output is untrusted input.
_RE_SCRIPT = re.compile(r'<script\b[^>]*(?:/\s*>|>.*?</script\s*>)',
                        re.DOTALL | re.IGNORECASE)
_RE_FOREIGN = re.compile(r'<foreignObject\b[^>]*(?:/\s*>|>.*?</foreignObject\s*>)',
                         re.DOTALL | re.IGNORECASE)
_RE_EVENT_ATTR = re.compile(r'\s+on\w+\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s>]+)',
                            re.IGNORECASE)
_RE_JS_URI = re.compile(r'(\s(?:xlink:)?href\s*=\s*)(["\'])\s*javascript:[^"\']*\2',
                        re.IGNORECASE)


def sanitize_svg(text):
    """
    Strip active content from LLM-generated SVG before it is previewed or
    inserted into the user's document:
    - <script> elements
    - <foreignObject> elements (can embed arbitrary HTML/JS)
    - on* event-handler attributes (onclick, onload, …)
    - javascript: URIs in href / xlink:href
    Visual content (shapes, gradients, filters, animations) is preserved.
    """
    if not text:
        return ''
    text = _RE_SCRIPT.sub('', text)
    text = _RE_FOREIGN.sub('', text)
    text = _RE_EVENT_ATTR.sub('', text)
    text = _RE_JS_URI.sub(r'\1\2\2', text)
    return text


def normalize_svg_dimensions(svg_code, width, height):
    """
    Ensure the SVG has a root tag with xmlns, a viewBox of
    "0 0 {width} {height}" (added only when missing), and root width/height
    attributes forced to the target size so the viewBox-to-pixel mapping is
    1:1 on import.

    Attribute rewriting is confined to the opening <svg ...> tag —
    child elements' width/height (e.g. on a <rect>) are never touched.
    """
    if not svg_code.startswith('<svg'):
        svg_match = re.search(r'<svg[^>]*>.*</svg>', svg_code, re.DOTALL)
        if svg_match:
            svg_code = svg_match.group(0)
        else:
            svg_code = (
                f'<svg xmlns="http://www.w3.org/2000/svg" '
                f'viewBox="0 0 {width} {height}" '
                f'width="{width}" height="{height}">' + svg_code + '</svg>'
            )

    # Isolate the opening <svg ...> tag and rewrite only its attributes
    tag_end = svg_code.find('>')
    if tag_end == -1:
        return svg_code
    root_tag = svg_code[:tag_end + 1]
    rest = svg_code[tag_end + 1:]

    if 'xmlns=' not in root_tag:
        root_tag = root_tag.replace(
            '<svg', '<svg xmlns="http://www.w3.org/2000/svg"', 1)

    if 'viewBox=' not in root_tag:
        root_tag = root_tag.replace(
            '<svg', f'<svg viewBox="0 0 {width} {height}"', 1)

    # Force root width / height to match target (1:1 viewBox ratio).
    # Negative lookbehind keeps stroke-width etc. untouched.
    root_tag, n_w = re.subn(r'(?<![-\w])width\s*=\s*"[^"]*"',
                            f'width="{width}"', root_tag, count=1)
    root_tag, n_h = re.subn(r'(?<![-\w])height\s*=\s*"[^"]*"',
                            f'height="{height}"', root_tag, count=1)
    if not n_w or not n_h:
        missing = ''
        if not n_w:
            missing += f' width="{width}"'
        if not n_h:
            missing += f' height="{height}"'
        root_tag = root_tag.replace('<svg', f'<svg{missing}', 1)

    return root_tag + rest


# ==================== HTTP HELPERS ====================

def _extract_error_message(body):
    """Pull a human-readable message out of a JSON error body."""
    try:
        parsed = json.loads(body)
        err = parsed.get('error', parsed)
        if isinstance(err, dict):
            return err.get('message') or str(err)[:300]
        return str(err)[:300]
    except Exception:
        return body[:300]


def http_post_json(url, headers, payload, timeout, ssl_context, provider_label):
    """
    POST a JSON payload and return the parsed JSON response.
    Raises Exception with a '{provider} API error (code): message' /
    '{provider} network error: reason' message on failure.
    """
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers=headers,
        method='POST',
    )
    ctx = None if url.startswith('http://') else ssl_context
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        raise Exception(
            f'{provider_label} API error ({e.code}): {_extract_error_message(body)}'
        )
    except urllib.error.URLError as e:
        raise Exception(f'{provider_label} network error: {e.reason}')


def http_get_json(url, headers, timeout, ssl_context):
    """GET a URL and return the parsed JSON response. Raises on failure."""
    req = urllib.request.Request(url, headers=headers or {})
    ctx = None if url.startswith('http://') else ssl_context
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return json.loads(resp.read().decode('utf-8'))


def http_post_stream(url, headers, payload, timeout, ssl_context, provider_label):
    """
    POST a JSON payload and yield parsed JSON events from a streaming
    response. Handles both SSE ('data: {...}' lines, OpenAI/Anthropic
    style) and NDJSON (one JSON object per line, Ollama style).
    'data: [DONE]' sentinel lines are skipped.
    """
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers=headers,
        method='POST',
    )
    ctx = None if url.startswith('http://') else ssl_context
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            for raw_line in resp:
                line = raw_line.decode('utf-8', errors='replace').strip()
                if not line:
                    continue
                if line.startswith('data:'):
                    line = line[5:].strip()
                    if line == '[DONE]':
                        break
                elif line.startswith(('event:', 'id:', 'retry:', ':')):
                    continue  # SSE metadata lines
                try:
                    yield json.loads(line)
                except ValueError:
                    continue  # partial / non-JSON line — skip
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        raise Exception(
            f'{provider_label} API error ({e.code}): {_extract_error_message(body)}'
        )
    except urllib.error.URLError as e:
        raise Exception(f'{provider_label} network error: {e.reason}')
