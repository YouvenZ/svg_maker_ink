#!/usr/bin/env python3
"""
Standalone test script for the AI SVG Generator extension.

Runs OUTSIDE Inkscape with any Python 3.8+ — it imports the extension's
provider modules and shared utilities directly (none of them require inkex).

Modes
-----
Self-test (no network, no keys):
    python test_svg_generation.py --self-test

Live smoke test (uses config.json / env keys, calls the real API):
    python test_svg_generation.py
    python test_svg_generation.py --provider openai --model gpt-5-mini
    python test_svg_generation.py --provider anthropic --stream
    python test_svg_generation.py --prompt "a red circle on white background"
"""

import argparse
import importlib
import json
import os
import sys
from datetime import datetime

# Windows consoles often default to cp1252 — keep unicode output safe
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from svg_llm_common import (           # noqa: E402
    PROVIDERS,
    build_ssl_context,
    clean_svg_response,
    normalize_svg_dimensions,
    sanitize_svg,
)

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


# ==================== SELF-TEST (no network) ====================

def _check(name, condition, detail=''):
    status = 'PASS' if condition else 'FAIL'
    print(f"  [{status}] {name}" + (f"  — {detail}" if detail and not condition else ''))
    return bool(condition)


def run_self_tests():
    print("Running self-tests (no network access needed)…\n")
    ok = True

    # ── clean_svg_response ───────────────────────────────────
    fenced = "```svg\n<svg xmlns=\"x\"><rect/></svg>\n```"
    cleaned = clean_svg_response(fenced)
    ok &= _check("clean: strips markdown fences",
                 cleaned.startswith('<svg') and '```' not in cleaned, cleaned)

    decl = '<?xml version="1.0"?>\n<!DOCTYPE svg>\n<svg xmlns="x"><g/></svg>'
    cleaned = clean_svg_response(decl)
    ok &= _check("clean: strips XML declaration and DOCTYPE",
                 cleaned.startswith('<svg') and '<?xml' not in cleaned, cleaned)

    chatty = 'Sure! Here is your SVG:\n<svg xmlns="x"><circle r="5"/></svg>\nEnjoy!'
    cleaned = clean_svg_response(chatty)
    ok &= _check("clean: isolates <svg> from surrounding narration",
                 cleaned.startswith('<svg') and cleaned.endswith('</svg>'), cleaned)

    # ── sanitize_svg ─────────────────────────────────────────
    evil = ('<svg xmlns="x" onload="evil()">'
            '<script>alert(1)</script>'
            '<foreignObject><iframe src="http://x"/></foreignObject>'
            '<a href="javascript:evil()"><rect onclick="evil()" width="5"/></a>'
            '</svg>')
    safe = sanitize_svg(evil)
    ok &= _check("sanitize: removes <script>", '<script' not in safe, safe)
    ok &= _check("sanitize: removes <foreignObject>",
                 'foreignObject' not in safe, safe)
    ok &= _check("sanitize: removes on* event handlers",
                 'onload' not in safe and 'onclick' not in safe, safe)
    ok &= _check("sanitize: neutralizes javascript: URIs",
                 'javascript:' not in safe, safe)
    ok &= _check("sanitize: keeps visual elements", '<rect' in safe, safe)

    # ── normalize_svg_dimensions ─────────────────────────────
    # Root has no width/height but a child rect does — the rect must survive.
    src = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="55" height="66"/></svg>'
    out = normalize_svg_dimensions(src, 400, 300)
    ok &= _check("normalize: child rect width untouched",
                 'width="55"' in out and 'height="66"' in out, out)
    root = out[:out.find('>') + 1]
    ok &= _check("normalize: root gets target width/height",
                 'width="400"' in root and 'height="300"' in root, out)
    ok &= _check("normalize: viewBox added when missing",
                 'viewBox="0 0 400 300"' in root, out)

    src2 = '<svg width="100" height="100" xmlns="x"><circle r="1"/></svg>'
    out2 = normalize_svg_dimensions(src2, 200, 200)
    ok &= _check("normalize: existing root size replaced",
                 'width="200"' in out2 and 'width="100"' not in out2, out2)

    src3 = '<svg xmlns="x" stroke-width="3"><g/></svg>'
    out3 = normalize_svg_dimensions(src3, 50, 50)
    ok &= _check("normalize: stroke-width attribute untouched",
                 'stroke-width="3"' in out3, out3)

    src4 = 'no svg tag at all'
    out4 = normalize_svg_dimensions(src4, 10, 20)
    ok &= _check("normalize: wraps bare content in an <svg> root",
                 out4.startswith('<svg') and out4.endswith('</svg>'), out4)

    # ── provider registry consistency ────────────────────────
    for pid, info in PROVIDERS.items():
        mod_ok = True
        try:
            mod = importlib.import_module(info['module'])
            mod_ok = callable(getattr(mod, 'generate', None)) and \
                callable(getattr(mod, 'fetch_models', None))
        except Exception as exc:
            mod_ok = False
            print(f"         import error: {exc}")
        ok &= _check(f"registry: {pid} module loads with generate()/fetch_models()",
                     mod_ok)

    print()
    if ok:
        print("All self-tests PASSED.")
        return 0
    print("Some self-tests FAILED.")
    return 1


# ==================== SVG validation ====================

def validate_svg(svg_code):
    """Returns (is_valid, issues_list)."""
    issues = []
    if not svg_code.startswith('<svg'):
        issues.append("Does not start with <svg")
    if 'xmlns=' not in svg_code:
        issues.append("Missing xmlns attribute")
    if 'viewBox=' not in svg_code:
        issues.append("Missing viewBox attribute")
    if not svg_code.rstrip().endswith('</svg>'):
        issues.append("Does not end with </svg>")
    import xml.etree.ElementTree as ET
    try:
        ET.fromstring(svg_code)
    except ET.ParseError as e:
        issues.append(f"XML parse error: {e}")
    return len(issues) == 0, issues


def save_svg(svg_code, save_dir, prefix="test_svg"):
    os.makedirs(save_dir, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    filepath = os.path.join(save_dir, f"{prefix}_{ts}.svg")
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(svg_code)
    return filepath


# ==================== Live smoke test ====================

def main():
    parser = argparse.ArgumentParser(
        description="Test SVG generation from the AI SVG Generator extension."
    )
    parser.add_argument('--self-test', action='store_true',
                        help="Run offline unit checks and exit")
    parser.add_argument('--provider', default=None,
                        help=f"Provider to test: {', '.join(PROVIDERS)}")
    parser.add_argument('--model', default=None,
                        help="Model name (overrides config default)")
    parser.add_argument('--prompt', default=DEFAULT_TEST_PROMPT,
                        help="Test prompt to send")
    parser.add_argument('--save-dir', default=None,
                        help="Directory to save SVG (overrides config)")
    parser.add_argument('--endpoint', default=None,
                        help="Endpoint URL (Ollama / Azure / custom)")
    parser.add_argument('--timeout', type=int, default=120,
                        help="Request timeout in seconds (default: 120)")
    parser.add_argument('--stream', action='store_true',
                        help="Use streaming with progress output")
    parser.add_argument('--no-save', action='store_true',
                        help="Do not save the SVG to disk")
    args = parser.parse_args()

    if args.self_test:
        sys.exit(run_self_tests())

    config = load_config()
    provider = args.provider or config.get('default_provider', 'openai')
    pinfo = PROVIDERS.get(provider)
    if pinfo is None:
        print(f"[ERROR] Unknown provider: {provider}. "
              f"Choose one of: {', '.join(PROVIDERS)}")
        sys.exit(1)

    save_dir = args.save_dir or config.get(
        'default_save_directory',
        os.path.join(os.path.expanduser('~'), 'Pictures', 'AI_Images')
    )
    model = args.model or config.get('default_model') or pinfo['models'][0]

    api_key = ''
    if not pinfo['keyless']:
        api_key = (
            os.environ.get(pinfo['env_key'], '') if pinfo['env_key'] else ''
        ) or config.get(pinfo['config_key'], '')

    print("=" * 60)
    print("  AI SVG Generator — Live Smoke Test")
    print("=" * 60)
    print(f"  Provider : {provider}")
    print(f"  Model    : {model}")
    print(f"  Save dir : {save_dir}")
    print(f"  Timeout  : {args.timeout}s")
    print(f"  Stream   : {args.stream and pinfo['supports_stream']}")
    if not pinfo['keyless']:
        masked = api_key[:8] + '…' if len(api_key) > 8 else '(empty)'
        print(f"  API key  : {masked}")
    print(f"  Prompt   : {args.prompt[:80]}{'…' if len(args.prompt) > 80 else ''}")
    print()

    if not pinfo['keyless'] and not api_key:
        print("[ERROR] No API key found.")
        print(f"        Set the {pinfo['env_key']} environment variable,")
        print(f"        or add '{pinfo['config_key']}' to config.json.")
        sys.exit(1)

    module = importlib.import_module(pinfo['module'])
    opts = {
        'model': model,
        'temperature': 0.7,
        'max_tokens': 4000,
        'timeout': args.timeout,
        'seed': -1,
        'endpoint': args.endpoint or '',
    }

    progress_cb = None
    if args.stream and pinfo['supports_stream']:
        def progress_cb(chars):
            print(f"\r  …{chars:,} chars received", end='', flush=True)

    print("[...] Calling API — this may take a while…")
    start = datetime.now()
    try:
        svg_code = module.generate(
            args.prompt, DEFAULT_SYSTEM_PROMPT, opts, api_key,
            build_ssl_context(), progress_cb=progress_cb,
        )
    except Exception as exc:
        elapsed = (datetime.now() - start).total_seconds()
        print(f"\n[FAILED] API call failed after {elapsed:.1f}s")
        print(f"         {exc}")
        sys.exit(1)
    if progress_cb:
        print()

    elapsed = (datetime.now() - start).total_seconds()
    print(f"[OK]     Response received in {elapsed:.1f}s  ({len(svg_code)} chars)")

    svg_code = sanitize_svg(svg_code)
    svg_code = normalize_svg_dimensions(svg_code, 200, 200)
    is_valid, issues = validate_svg(svg_code)
    if is_valid:
        print("[OK]     SVG is well-formed")
    else:
        print("[WARN]   SVG validation issues:")
        for issue in issues:
            print(f"           - {issue}")

    if not args.no_save:
        try:
            saved_path = save_svg(
                svg_code, save_dir,
                prefix=f"test_{provider}_{model.replace('/', '_').replace(':', '_')}")
            print(f"[OK]     Saved to: {saved_path}")
        except Exception as e:
            print(f"[WARN]   Could not save SVG: {e}")
    else:
        print("[INFO]   --no-save specified, SVG not saved to disk")

    print()
    print("── SVG preview (first 300 chars) ──────────────────────")
    print(svg_code[:300] + ('…' if len(svg_code) > 300 else ''))
    print()
    print("── DONE ───────────────────────────────────────────────")
    sys.exit(0)


if __name__ == '__main__':
    main()
