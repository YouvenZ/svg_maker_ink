#!/usr/bin/env python3
"""
Standalone SVG generation test script.

Tests the API connection and SVG generation outside of Inkscape.
Reads config.json for API keys and save directory, then calls the configured
provider with a simple test prompt and saves the result to disk.

Usage:
    python test_svg_generation.py
    python test_svg_generation.py --provider openai --model gpt-4o-mini
    python test_svg_generation.py --prompt "a red circle on white background"
    python test_svg_generation.py --provider anthropic
"""

import argparse
import json
import os
import re
import ssl
import sys
import urllib.request
import urllib.error
from datetime import datetime


# ── SSL context ───────────────────────────────────────────────────────────────

def _build_ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    return ssl.create_default_context()


_SSL_CONTEXT = _build_ssl_context()

# ── Config ────────────────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, 'config.json')

DEFAULT_SYSTEM_PROMPT = (
    "You are an expert SVG code generator. You only respond with valid, clean SVG code "
    "without any explanation or markdown formatting. Never include ```svg or ``` markers. "
    "Always produce well-formed, valid SVG."
)

DEFAULT_TEST_PROMPT = (
    "A simple geometric test shape: a blue circle inside a red square, "
    "centered on a white background. viewBox 0 0 200 200."
)


def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[warn] Could not load config.json: {e}")
    return {}


# ── API callers ───────────────────────────────────────────────────────────────

def _post(url, headers, data, timeout=60):
    body = json.dumps(data).encode('utf-8')
    req = urllib.request.Request(url, data=body, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
            return json.loads(resp.read().decode('utf-8')), None
    except urllib.error.HTTPError as e:
        err_body = e.read().decode('utf-8')
        try:
            msg = json.loads(err_body).get('error', {}).get('message', err_body)
        except Exception:
            msg = err_body
        return None, f"HTTP {e.code}: {msg}"
    except urllib.error.URLError as e:
        return None, f"Network error: {e}"
    except Exception as e:
        return None, str(e)


def call_openai(prompt, api_key, model, temperature=0.7, max_tokens=4000, timeout=60):
    result, err = _post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
        },
        data={
            'model': model,
            'messages': [
                {'role': 'system', 'content': DEFAULT_SYSTEM_PROMPT},
                {'role': 'user', 'content': prompt},
            ],
            'temperature': temperature,
            'max_tokens': max_tokens,
        },
        timeout=timeout,
    )
    if err:
        return None, err
    try:
        return result['choices'][0]['message']['content'].strip(), None
    except (KeyError, IndexError) as e:
        return None, f"Unexpected response shape: {e}\n{result}"


def call_anthropic(prompt, api_key, model, temperature=0.7, max_tokens=4000, timeout=60):
    result, err = _post(
        "https://api.anthropic.com/v1/messages",
        headers={
            'Content-Type': 'application/json',
            'x-api-key': api_key,
            'anthropic-version': '2023-06-01',
        },
        data={
            'model': model,
            'max_tokens': max_tokens,
            'messages': [
                {'role': 'user', 'content': f"{DEFAULT_SYSTEM_PROMPT}\n\n{prompt}"},
            ],
        },
        timeout=timeout,
    )
    if err:
        return None, err
    try:
        return result['content'][0]['text'].strip(), None
    except (KeyError, IndexError) as e:
        return None, f"Unexpected response shape: {e}\n{result}"


def call_google(prompt, api_key, model, temperature=0.7, max_tokens=4000, timeout=60):
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    result, err = _post(
        url,
        headers={'Content-Type': 'application/json'},
        data={
            'contents': [{'parts': [{'text': f"{DEFAULT_SYSTEM_PROMPT}\n\n{prompt}"}]}],
            'generationConfig': {
                'temperature': temperature,
                'maxOutputTokens': max_tokens,
            },
        },
        timeout=timeout,
    )
    if err:
        return None, err
    try:
        return result['candidates'][0]['content']['parts'][0]['text'].strip(), None
    except (KeyError, IndexError) as e:
        return None, f"Unexpected response shape: {e}\n{result}"


def call_ollama(prompt, model, endpoint="http://localhost:11434", temperature=0.7,
                max_tokens=4000, timeout=60):
    endpoint = endpoint.rstrip('/')
    result, err = _post(
        f"{endpoint}/api/generate",
        headers={'Content-Type': 'application/json'},
        data={
            'model': model,
            'prompt': f"{DEFAULT_SYSTEM_PROMPT}\n\n{prompt}",
            'stream': False,
            'options': {
                'temperature': temperature,
                'num_predict': max_tokens,
            },
        },
        timeout=timeout,
    )
    if err:
        return None, err
    try:
        return result['response'].strip(), None
    except KeyError as e:
        return None, f"Unexpected response shape: {e}\n{result}"


# ── SVG cleanup ───────────────────────────────────────────────────────────────

def clean_svg(svg_code):
    svg_code = re.sub(r'^```(?:svg|xml)?\s*\n?', '', svg_code, flags=re.MULTILINE)
    svg_code = re.sub(r'\n?```\s*$', '', svg_code, flags=re.MULTILINE)
    svg_code = re.sub(r'<\?xml[^>]+\?>\s*', '', svg_code)
    svg_code = re.sub(r'<!DOCTYPE[^>]+>\s*', '', svg_code)
    svg_code = svg_code.strip()
    return svg_code


def validate_svg(svg_code):
    """Returns (is_valid, issues_list)."""
    issues = []
    if not svg_code.startswith('<svg'):
        # Try to extract
        m = re.search(r'<svg[^>]*>.*</svg>', svg_code, re.DOTALL)
        if m:
            svg_code = m.group(0)
        else:
            issues.append("Does not start with <svg")
    if 'xmlns=' not in svg_code:
        issues.append("Missing xmlns attribute")
    if 'viewBox=' not in svg_code and 'viewbox=' not in svg_code.lower():
        issues.append("Missing viewBox attribute")
    if not svg_code.rstrip().endswith('</svg>'):
        issues.append("Does not end with </svg>")
    import xml.etree.ElementTree as ET
    try:
        ET.fromstring(svg_code)
    except ET.ParseError as e:
        issues.append(f"XML parse error: {e}")
    return len(issues) == 0, issues


# ── Save ──────────────────────────────────────────────────────────────────────

def save_svg(svg_code, save_dir, prefix="test_svg"):
    os.makedirs(save_dir, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{prefix}_{ts}.svg"
    filepath = os.path.join(save_dir, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(svg_code)
    return filepath


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Test SVG generation from the AI SVG Generator extension."
    )
    parser.add_argument('--provider', default=None,
                        help="Provider to test: openai, anthropic, google, ollama")
    parser.add_argument('--model', default=None,
                        help="Model name (overrides config default)")
    parser.add_argument('--prompt', default=DEFAULT_TEST_PROMPT,
                        help="Test prompt to send")
    parser.add_argument('--save-dir', default=None,
                        help="Directory to save SVG (overrides config)")
    parser.add_argument('--endpoint', default=None,
                        help="Ollama/Azure endpoint URL")
    parser.add_argument('--timeout', type=int, default=60,
                        help="Request timeout in seconds (default: 60)")
    parser.add_argument('--no-save', action='store_true',
                        help="Do not save the SVG to disk")
    args = parser.parse_args()

    config = load_config()

    provider = args.provider or config.get('default_provider', 'openai')
    save_dir = args.save_dir or config.get(
        'default_save_directory',
        os.path.join(os.path.expanduser('~'), 'Pictures', 'AI_Images')
    )

    # Resolve model
    DEFAULT_MODELS = {
        'openai': 'gpt-4o-mini',
        'anthropic': 'claude-3-haiku-20240307',
        'google': 'gemini-1.5-flash',
        'ollama': 'llama3.2',
    }
    model = args.model or config.get('default_model') or DEFAULT_MODELS.get(provider, 'gpt-4o-mini')

    # Resolve API key
    KEY_CONFIG_MAP = {
        'openai': 'openai_api_key',
        'anthropic': 'anthropic_api_key',
        'google': 'google_api_key',
    }
    ENV_KEY_MAP = {
        'openai': 'OPENAI_API_KEY',
        'anthropic': 'ANTHROPIC_API_KEY',
        'google': 'GOOGLE_API_KEY',
    }
    api_key = ''
    if provider != 'ollama':
        env_var = ENV_KEY_MAP.get(provider, '')
        config_key = KEY_CONFIG_MAP.get(provider, '')
        api_key = (
            os.environ.get(env_var, '')
            or config.get(config_key, '')
        )

    print("=" * 60)
    print(f"  AI SVG Generator — Test Run")
    print("=" * 60)
    print(f"  Provider : {provider}")
    print(f"  Model    : {model}")
    print(f"  Save dir : {save_dir}")
    print(f"  Timeout  : {args.timeout}s")
    if provider != 'ollama':
        masked = api_key[:8] + '…' if len(api_key) > 8 else ('(empty)' if not api_key else api_key)
        print(f"  API key  : {masked}")
    print(f"  Prompt   : {args.prompt[:80]}{'…' if len(args.prompt) > 80 else ''}")
    print()

    if provider != 'ollama' and not api_key:
        print("[ERROR] No API key found.")
        print(f"        Set the {ENV_KEY_MAP.get(provider, 'API key')} environment variable,")
        print(f"        or add '{KEY_CONFIG_MAP.get(provider, 'api_key')}' to config.json.")
        sys.exit(1)

    print("[...] Calling API — this may take a few seconds...")
    start = datetime.now()

    if provider == 'openai':
        svg_code, error = call_openai(args.prompt, api_key, model,
                                       timeout=args.timeout)
    elif provider == 'anthropic':
        svg_code, error = call_anthropic(args.prompt, api_key, model,
                                          timeout=args.timeout)
    elif provider == 'google':
        svg_code, error = call_google(args.prompt, api_key, model,
                                       timeout=args.timeout)
    elif provider == 'ollama':
        endpoint = args.endpoint or 'http://localhost:11434'
        svg_code, error = call_ollama(args.prompt, model, endpoint=endpoint,
                                       timeout=args.timeout)
    else:
        print(f"[ERROR] Unknown provider: {provider}")
        sys.exit(1)

    elapsed = (datetime.now() - start).total_seconds()

    if error:
        print(f"[FAILED] API call failed after {elapsed:.1f}s")
        print(f"         {error}")
        sys.exit(1)

    print(f"[OK]     Response received in {elapsed:.1f}s  ({len(svg_code)} chars)")

    # Clean and validate
    svg_code = clean_svg(svg_code)
    is_valid, issues = validate_svg(svg_code)

    if is_valid:
        print("[OK]     SVG is well-formed")
    else:
        print("[WARN]   SVG validation issues:")
        for issue in issues:
            print(f"           - {issue}")

    # Save
    if not args.no_save:
        try:
            saved_path = save_svg(svg_code, save_dir, prefix=f"test_{provider}_{model.replace('/', '_')}")
            print(f"[OK]     Saved to: {saved_path}")
        except Exception as e:
            print(f"[WARN]   Could not save SVG: {e}")
    else:
        print("[INFO]   --no-save specified, SVG not saved to disk")

    # Print a snippet
    print()
    print("── SVG preview (first 300 chars) ──────────────────────")
    print(svg_code[:300] + ('…' if len(svg_code) > 300 else ''))
    print()
    print("── DONE ────────────────────────────────────────────────")
    sys.exit(0)


if __name__ == '__main__':
    main()
