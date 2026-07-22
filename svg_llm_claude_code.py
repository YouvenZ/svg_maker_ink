#!/usr/bin/env python3
"""
Claude Code (CLI) provider for AI SVG Generator.

Bridges the Inkscape extension to a local Claude Code installation by
invoking the `claude` CLI in headless mode (`claude -p`). Generation runs
through the user's existing Claude Code login/subscription, so no API key
is required.

The 'endpoint' option is repurposed as an OPTIONAL override path to the
claude executable. When blank, the CLI is auto-detected from PATH and
common install locations.

Exposes:
  PROVIDER_ID, NAME, ENV_KEY, CONFIG_KEY, DEFAULT_MODELS,
  NEEDS_ENDPOINT, ENDPOINT_PLACEHOLDER, SUPPORTS_SEED
  generate(prompt, system_prompt, opts, api_key, ssl_context) -> str
  fetch_models(api_key='', endpoint='', ssl_context=None) -> list[str]
  ping(cli_override='') -> (bool, str)
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime

from svg_llm_common import clean_svg_response

PROVIDER_ID = 'claude_code'
NAME = 'Claude Code (CLI)'
ENV_KEY = ''
CONFIG_KEY = ''
# 'default' = whatever model the user's Claude Code session is configured
# to use; the aliases resolve to the latest model of each tier.
DEFAULT_MODELS = ['default', 'opus', 'sonnet', 'haiku']
NEEDS_ENDPOINT = True
ENDPOINT_PLACEHOLDER = '(optional) full path to the claude CLI — leave blank to auto-detect'
SUPPORTS_SEED = False

# Session metadata (last session id, for potential --resume workflows)
_SESSION_FILENAME = 'claude_code_session.json'

# Hide the console window that would otherwise flash up on Windows
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0


def _candidate_paths():
    """Common Claude Code install locations, checked after PATH."""
    home = os.path.expanduser('~')
    if sys.platform == 'win32':
        return [
            os.path.join(home, '.local', 'bin', 'claude.exe'),
            os.path.join(home, 'AppData', 'Roaming', 'npm', 'claude.cmd'),
            os.path.join(home, 'AppData', 'Roaming', 'npm', 'claude.exe'),
        ]
    return [
        os.path.join(home, '.local', 'bin', 'claude'),
        '/usr/local/bin/claude',
        '/opt/homebrew/bin/claude',
        os.path.join(home, '.npm-global', 'bin', 'claude'),
    ]


def find_cli(override=''):
    """
    Resolve the claude executable.

    Priority: explicit override path > PATH lookup > common install dirs.
    Returns the absolute path, or raises with installation guidance.
    """
    override = (override or '').strip().strip('"')
    if override:
        if os.path.isfile(override):
            return override
        # allow a bare command name as override too
        found = shutil.which(override)
        if found:
            return found
        raise Exception(
            f"Claude Code CLI not found at the configured path:\n{override}\n"
            "Clear the Endpoint field to auto-detect, or fix the path."
        )

    found = shutil.which('claude')
    if found:
        return found

    for path in _candidate_paths():
        if os.path.isfile(path):
            return path

    raise Exception(
        "Claude Code CLI ('claude') was not found.\n\n"
        "Install it from https://claude.com/claude-code and make sure the\n"
        "'claude' command works in a terminal, or set the full path to the\n"
        "executable in the Endpoint field of the Provider tab."
    )


def _save_session_info(ext_dir, info):
    """Persist last session metadata (best effort, never fatal)."""
    try:
        path = os.path.join(ext_dir, _SESSION_FILENAME)
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(info, fh, indent=2)
    except Exception:
        pass


def generate(prompt, system_prompt, opts, api_key, ssl_context, progress_cb=None):
    """
    Run `claude -p` in headless mode and return the raw text response.

    opts keys used: model, timeout, endpoint (= optional CLI path override)
    api_key and ssl_context are ignored — auth is Claude Code's own login.
    progress_cb is accepted for interface parity but not used (no streaming).
    """
    cli = find_cli(opts.get('endpoint', ''))

    # System prompt is folded into the stdin payload rather than passed as a
    # CLI argument: on Windows the npm shim is a .cmd script, and cmd.exe
    # argument quoting would mangle multi-line prompt text.
    full_prompt = (
        "SYSTEM INSTRUCTIONS (follow these exactly):\n"
        f"{system_prompt}\n\n"
        "USER REQUEST:\n"
        f"{prompt}"
    )

    cmd = [cli, '-p', '--output-format', 'json']
    model = (opts.get('model') or '').strip()
    if model and model != 'default':
        cmd += ['--model', model]

    # Claude Code turns can be slower than a raw API call — enforce a floor.
    timeout = max(int(opts.get('timeout', 60)), 120)

    try:
        proc = subprocess.run(
            cmd,
            input=full_prompt.encode('utf-8'),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
            # Predictable cwd — avoids picking up project CLAUDE.md context
            # from wherever Inkscape happened to launch the extension.
            cwd=os.path.expanduser('~'),
        )
    except subprocess.TimeoutExpired:
        raise Exception(
            f"Claude Code did not respond within {timeout}s. "
            "Increase the timeout in the Advanced tab and try again."
        )
    except FileNotFoundError:
        raise Exception(f"Could not execute Claude Code CLI at: {cli}")

    stdout = proc.stdout.decode('utf-8', errors='replace').strip()
    stderr = proc.stderr.decode('utf-8', errors='replace').strip()

    if proc.returncode != 0 and not stdout:
        raise Exception(
            f"Claude Code CLI failed (exit {proc.returncode}):\n"
            f"{stderr[:500] or 'no error output'}\n\n"
            "If you are not logged in, run 'claude' once in a terminal "
            "to authenticate."
        )

    text, session_id = _parse_cli_output(stdout, stderr)

    _save_session_info(os.path.dirname(os.path.abspath(__file__)), {
        'session_id': session_id,
        'model': model or 'default',
        'timestamp': datetime.now().isoformat(),
    })

    return clean_svg_response(text)


def _parse_cli_output(stdout, stderr):
    """Parse `--output-format json` output; fall back to raw text."""
    try:
        data = json.loads(stdout)
    except Exception:
        # Older CLI or plain-text output — use it verbatim
        if stdout:
            return stdout, None
        raise Exception(
            f"Empty response from Claude Code CLI.\n{stderr[:300]}"
        )

    if isinstance(data, dict):
        if data.get('is_error'):
            raise Exception(
                "Claude Code returned an error: "
                f"{data.get('result') or data.get('subtype') or 'unknown error'}"
            )
        result = data.get('result')
        if result:
            return result, data.get('session_id')
        raise Exception(
            "Claude Code returned no result "
            f"(subtype: {data.get('subtype', 'unknown')})."
        )

    # Unexpected JSON shape — return as string
    return stdout, None


def fetch_models(api_key='', endpoint='', ssl_context=None):
    """
    Claude Code has no model-list endpoint; return the supported aliases
    (only if the CLI is actually reachable, so the Refresh button doubles
    as an install check).
    """
    try:
        find_cli(endpoint)
        return DEFAULT_MODELS
    except Exception:
        return DEFAULT_MODELS


def ping(cli_override=''):
    """Verify the CLI is installed and runnable. Returns (ok, message)."""
    try:
        cli = find_cli(cli_override)
    except Exception as exc:
        return False, str(exc)
    try:
        proc = subprocess.run(
            [cli, '--version'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            creationflags=_CREATE_NO_WINDOW,
        )
        version = proc.stdout.decode('utf-8', errors='replace').strip()
        if proc.returncode == 0:
            return True, f"Claude Code found ✓  ({version or cli})"
        return False, (
            f"Claude Code CLI found at {cli} but '--version' failed:\n"
            f"{proc.stderr.decode('utf-8', errors='replace')[:200]}"
        )
    except Exception as exc:
        return False, f"Could not run Claude Code CLI: {exc}"
