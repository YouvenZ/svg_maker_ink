# SVG Maker Inkscape Extension — Review & Improvement Plan

> **Usage**: This file is used recursively by the agent until the extension converges to an ideal state.
> Each session: pick the highest-priority open item, implement it, move it to Done, commit.

---

## Legend
- `[ ]` — To Do
- `[~]` — In Progress
- `[x]` — Done
- `[!]` — Bug
- `[?]` — Question / needs decision

---

## CRITICAL (do first — security & crashes)

### [x] BUG — Real API key committed in `config.json`
**File**: `config.json`
The file contains a live OpenAI API key (`sk-proj-MhP68W435J0...`).
- **Action**: Revoke/rotate the key on https://platform.openai.com immediately.
- Replace with the placeholder from `example_config.json`.
- Add `config.json` to `.gitignore` (create the file, it doesn't exist yet).

---

### [x] BUG — SSL verification is disabled for ALL HTTPS providers (security, OWASP A02)
**File**: `svg_llm.py` — `_make_api_request()`
```python
# BUG: this creates an *unverified* context when use_ssl=True (i.e., for OpenAI/Anthropic/Google)
context = ssl._create_unverified_context() if use_ssl else None
```
The logic is **inverted**: verified calls get an unverified context; Ollama (HTTP, `use_ssl=False`) gets `None`.
- **Fix**: Remove the entire `use_ssl` / `context` parameter.  
  For HTTPS endpoints let `urllib` use the default verified context (`context=None`).  
  For Ollama (HTTP) no SSL context is needed either — just pass `context=None` always.

---

### [x] BUG — `get_config_value` and `set_config_value` methods are called but never defined
**File**: `svg_llm.py`
- `get_save_directory()` calls `self.get_config_value('default_save_directory', ...)`
- `get_api_key()` calls `self.set_config_value(config_key, self.options.api_key)`
These will raise `AttributeError` at runtime.
- **Fix**: Implement both helpers, or inline the logic using `self.config.get(...)` and `self.save_config(...)`.

---

### [x] BUG — Debug `inkex.errormsg` calls left in `get_api_key()` (pollutes user UI)
**File**: `svg_llm.py` — `get_api_key()`
Three debug messages are printed unconditionally to the user every run:
```python
inkex.errormsg(f"env_key ::  {env_key}")
inkex.errormsg(f"env_key ::  {env_key}")   # duplicate
inkex.errormsg(f"env_value ::  {env_value}")
```
- **Fix**: Remove all three lines.

---

### [x] BUG — API key save path is inconsistent between `save_api_key()` and `get_api_key()`
**File**: `svg_llm.py`
- `save_api_key()` writes to `config['api_keys']['openai']`
- `get_api_key()` reads from `self.config.get('openai_api_key', '')` (flat key)
The read path will never find keys saved by the write path.
- **Fix**: Standardise to one schema. Recommended: flat keys (`openai_api_key`, etc.) everywhere, matching the existing `config.json` / `example_config.json` format.

---

## HIGH (core functionality gaps)

### [x] MISSING — `embed_in_svg` option is in the UI but never used in code
**File**: `svg_llm.py`
`add_arguments` parses `--embed_in_svg` but no code path reads or acts on it.
- **Fix**: When `embed_in_svg=False`, save the SVG to disk and insert an `<image href="...">` link instead of inline elements. When `True` (default), keep current inline behaviour.

---

### [x] MISSING — No model-to-provider validation
**File**: `svg_llm.py`
A user can select "GPT-4o" model with the Anthropic provider and the code will silently fall back to a default in `call_anthropic_api`. This is confusing.
- **Fix**: In `effect()` or `call_api()`, check that the selected model belongs to the selected provider and show a clear warning (or auto-correct with a message).

---

### [x] MISSING — History is saved but never surfaced to the user
**File**: `svg_llm.py`, `svg_llm.inx`
`save_to_history()` writes a JSON file but there is no way to browse, select, or replay past prompts from the UI.
- **Fix (minimal)**: Add a "History" tab in the INX that lists the last N entries.  
  Since INX is static, the simplest approach is a separate "History Viewer" extension or writing the last 10 prompts into a readable label/text area. *(Needs decision — see [?] below.)*

---

### [x] MISSING — Hardcoded user-specific save directory in `svg_llm.inx`
**File**: `svg_llm.inx`
```xml
<param name="save_directory" type="string" ...>C:\Users\youve\Pictures\SVG_Images</param>
```
This is specific to one machine. It will be wrong for every other user.
- **Fix**: Change default to an empty string or `~/Pictures/SVG_Images`. The Python already falls back to `os.path.expanduser('~/Pictures/AI_Images')` when empty.

---

### [x] MISSING — `seed` is only passed to OpenAI; Anthropic/Google/Ollama ignore it
**File**: `svg_llm.py`
`data['seed'] = self.options.seed` is only added in `call_openai_api()`.
- **Fix**: Add seed support in each provider where the API supports it (Gemini: `generationConfig.seed`, Ollama: `options.seed`). Document that Anthropic does not support seed.

---

### [x] MISSING — `.gitignore` does not exist
**File**: (new file)
`config.json` with API keys and `svg_llm_history.json` with usage history should not be committed.
- **Fix**: Create `.gitignore` containing:
  ```
  config.json
  svg_llm_history.json
  __pycache__/
  *.pyc
  ```

---

## MEDIUM (quality & robustness)

### [x] ENHANCE — SSL: use system certs for verified HTTPS
After fixing the inverted `use_ssl` bug, ensure the HTTPS calls work cross-platform.
On some systems (Windows packaged Python), default certs may be missing.
- **Fix**: Try `import certifi` with a fallback to the default context. Wrap in a try/except.

---

### [x] ENHANCE — `save_svg_to_disk()` is called inside `_parse_response()` (poor separation of concerns)
**File**: `svg_llm.py`
A response parser should not have a side-effect of saving to disk. This makes the flow hard to follow and test.
- **Fix**: Move the `save_svg_to_disk()` call to `effect()` after `validate_and_fix_svg()`.

---

### [x] ENHANCE — `import_element()` silently drops `.tail` text
**File**: `svg_llm.py` — `import_element()`
ElementTree elements have a `.tail` attribute for text after the closing tag (relevant in `<text>` elements).
- **Fix**: Copy `et_element.tail` to `new_elem.tail` when it exists and is non-empty.

---

### [x] ENHANCE — Bare `except:` clauses suppress all errors including `KeyboardInterrupt`
**File**: `svg_llm.py` — `load_config()`, `load_history()`, `save_to_history()`, `import_element()`
- **Fix**: Replace `except:` with `except Exception:` throughout.

---

### [x] ENHANCE — Retry logic has no back-off delay
**File**: `svg_llm.py` — `call_api_with_retry()`
Retrying immediately after a network error or rate-limit (HTTP 429) will likely fail again.
- **Fix**: Add exponential back-off: `time.sleep(2 ** attempt)` between retries.

---

### [x] ENHANCE — `variations` offset stacks elements horizontally but ignores document bounds
**File**: `svg_llm.py` — `effect()`
When generating 4 variations with xlarge size, elements will be placed far outside the canvas with no warning.
- **Fix**: After placing all variations, optionally zoom/fit to page, or at least show a message about the canvas size.

---

### [x] ENHANCE — No feedback while the API call is running
**File**: `svg_llm.py`
The Inkscape UI freezes with no indication of progress.
- **Fix**: Use `inkex.errormsg` / `inkex.utils.debug` to print step-by-step status ("Calling API...", "Parsing response...", "Adding to document..."). This at least shows in the Inkscape log.

---

### [x] ENHANCE — Custom Ollama endpoint is not validated
**File**: `svg_llm.py` — `call_ollama_api()`
If the user leaves the field empty or types an invalid URL, the error message is generic.
- **Fix**: Validate `endpoint` is a non-empty, well-formed URL before making the request.

---

## LOW (nice-to-have / future features)

### [x] FEATURE — Ollama: auto-discover available local models via `/api/tags`
Implemented as part of P2-2 — background thread queries `GET {endpoint}/api/tags` on Ollama select and repopulates the model combo via `GLib.idle_add()`.

---

### [x] FEATURE — System prompt customisation
**File**: `svg_llm_dialog.py` — Advanced tab
Added an "Advanced" tab with a multiline text area for the system prompt and a
"Use custom system prompt" checkbox. `SVGLLMGenerator.get_system_prompt()` returns
the custom value when enabled, the built-in default otherwise. All four provider
call methods use `get_system_prompt()`.

---

### [x] FEATURE — Provider: Azure OpenAI endpoint support
**File**: `svg_llm_dialog.py` — PROVIDERS dict + endpoint row; `svg_llm.py` — `call_azure_api()`
Added `azure` to both PROVIDERS registries. In the dialog the `needs_endpoint` flag
shows the endpoint row for both Ollama and Azure, with provider-specific placeholder
text. `call_azure_api()` builds the URL as
`{endpoint}/openai/deployments/{model}/chat/completions?api-version=2024-08-01-preview`
and uses `api-key:` header (Azure format). Seeds supported; same response parser as OpenAI.

---

### [x] FEATURE — "Re-generate / Refine" workflow
**File**: `svg_llm_dialog.py` — Prompt tab; `svg_llm.py` — `_get_selection_as_svg()`, `build_prompt()`
Added "Include selected elements as raw SVG (refine/edit workflow)" checkbox in the
Prompt tab (`include_selection_svg` field). When checked, `_get_selection_as_svg()`
serializes the selected lxml elements to an SVG string and injects it into the prompt
between `=== EXISTING SVG ===` delimiters with an instruction to preserve unchanged
elements. Complementary to the existing `use_selection_context` text-description feature.

---

### [x] FEATURE — Prompt template save/load
**File**: `svg_llm_dialog.py` — Advanced tab
Added template save/load in the Advanced tab. Templates store: prompt, provider, model, preset, temperature, style, colour, complexity, and system prompt. Saved to `svg_llm_templates.json`. Users can save, load, and delete named templates from a combo + buttons UI.

---

### [x] FEATURE — Layer target selection
**File**: `svg_llm_dialog.py` — Output tab; `svg_llm.py` — `_get_target_layer()`
Added a "Target layer" combo to the Output tab listing all Inkscape layers in the
document. `SVGLLMGenerator._get_target_layer()` resolves the selected layer by ID;
falls back to the current layer when none is selected. Both `add_svg_to_document()`
and `_insert_image_link()` now call `_get_target_layer()` instead of
`get_current_layer()`.

---

### [x] FEATURE — Post-generation: auto-fit to page option
**File**: `svg_llm_dialog.py` — Output tab; `svg_llm.py` — `_auto_fit_page()`
Added "Expand page to fit all generated content" checkbox in the Output tab.
When checked after multi-variation generation, `_auto_fit_page()` resizes the SVG
`width`/`height`/`viewBox` to contain all placed variations.

---

---

## GTK UI MIGRATION (replaces static `.inx` dialog)

> **Goal**: Replace the static XML `.inx` dialog with a fully dynamic GTK dialog built in Python.  
> The `.inx` file is kept minimal — it only registers the extension in the Inkscape menu and launches the script.  
> All UI, validation, and state live in Python.

### Architecture

```
svg_llm.inx          ← minimal: registers extension, no <param> inputs, calls svg_llm.py
svg_llm.py           ← SVGLLMGenerator.effect() opens SVGLLMDialog, then runs generation
svg_llm_dialog.py    ← GTK dialog class (new file)
svg_llm_api.py       ← all API call logic extracted (new file, refactor from svg_llm.py)
config.json          ← persisted settings (unchanged)
svg_llm_history.json ← prompt history (unchanged)
```

---

### Phase 1 — Minimal `.inx` + GTK dialog scaffold

#### [x] TASK P1-1 — Strip `.inx` to a no-param shell
**File**: `svg_llm.inx`
Remove all `<param>` and `<page>` elements. Keep only the metadata, `<effect>`, and `<script>` blocks.
```xml
<?xml version="1.0" encoding="UTF-8"?>
<inkscape-extension xmlns="http://www.inkscape.org/namespace/inkscape/extension">
    <name>AI SVG Generator</name>
    <id>org.inkscape.ai.svg.generator</id>
    <effect>
        <object-type>all</object-type>
        <effects-menu>
            <submenu name="Generate"/>
        </effects-menu>
    </effect>
    <script>
        <command location="inx" interpreter="python">svg_llm.py</command>
    </script>
</inkscape-extension>
```

---

#### [x] TASK P1-2 — Create `svg_llm_dialog.py` with GTK window skeleton
**File**: `svg_llm_dialog.py` (new)

Tabs to implement (mirrors current `.inx` tabs):
- **Prompt** — provider combo, API key entry (masked), env/config toggles, preset combo, multiline prompt entry, use-selection checkbox
- **Model** — model combo (populated dynamically per provider), temperature scale, max_tokens spinbox, timeout spinbox, retry spinbox, seed spinbox
- **Size** — size preset combo, aspect ratio combo, custom width/height spinboxes
- **Style** — style combo, complexity combo, colour scheme combo, stroke style combo, gradients checkbox
- **Output** — position combo, group checkbox, group name entry, variations spinbox, animations/accessibility/optimize checkboxes
- **Save** — save-to-disk checkbox, directory chooser button (`Gtk.FileChooserButton`), filename prefix entry
- **History** — `Gtk.TreeView` showing last 50 history entries; double-click row to reload prompt
- **Help** — static labels (same content as current help tab)

Extra dynamic behaviours:
- Provider combo `changed` signal → filter model combo to only show models for that provider
- Provider combo `changed` signal → show/hide "Custom endpoint" row (only visible when Ollama selected)
- API key entry: "Test key" button that makes a cheap ping to the provider and shows ✓ / ✗
- History tab: populated from `svg_llm_history.json` on dialog open
- Ollama model combo: on Ollama select, fire a background thread to `GET /api/tags` and repopulate combo

---

#### [x] TASK P1-3 — Wire dialog into `SVGLLMGenerator.effect()`
**File**: `svg_llm.py`

```python
def effect(self):
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk
    from svg_llm_dialog import SVGLLMDialog

    self.config = self.load_config()
    dialog = SVGLLMDialog(self.config, self.svg.selection)

    response = dialog.run()
    if response != Gtk.ResponseType.OK:
        dialog.destroy()
        return

    options = dialog.get_options()   # returns a plain dataclass / dict
    dialog.destroy()

    # rest of generation logic using `options` instead of `self.options`
    ...
```

`remove_arguments()` / `add_arguments()` can be removed entirely (no INX params to parse).

---

#### [x] TASK P1-4 — `dialog.get_options()` — define `GenerationOptions` dataclass
**File**: `svg_llm_dialog.py`

```python
from dataclasses import dataclass, field

@dataclass
class GenerationOptions:
    provider: str = "openai"
    api_key: str = ""
    use_env_key: bool = True
    use_config_key: bool = True
    save_api_key: bool = False
    api_endpoint: str = ""
    prompt: str = ""
    prompt_preset: str = "none"
    use_selection_context: bool = False
    model: str = "gpt-4-turbo"
    temperature: float = 0.7
    max_tokens: int = 4000
    timeout: int = 60
    retry_count: int = 2
    seed: int = -1
    size: str = "medium"
    custom_width: int = 400
    custom_height: int = 400
    aspect_ratio: str = "square"
    style_hint: str = "none"
    complexity: str = "medium"
    color_scheme: str = "any"
    stroke_style: str = "any"
    include_gradients: bool = True
    add_group: bool = True
    group_name: str = ""
    position: str = "center"
    include_animations: bool = False
    add_accessibility: bool = False
    optimize_paths: bool = True
    variations: int = 1
    save_to_history: bool = True
    save_to_disk: bool = True
    save_directory: str = ""
    filename_prefix: str = "svg_image"
    embed_in_svg: bool = True
```

---

### Phase 2 — Dynamic model list & Ollama discovery

#### [x] TASK P2-1 — Per-provider model filtering
When the provider combo changes, clear and repopulate the model combo using `PROVIDERS[provider]['models']`.

#### [x] TASK P2-2 — Ollama live model discovery
On selecting Ollama provider, spawn a `threading.Thread` that calls `GET {endpoint}/api/tags`.  
On success: update model combo on the GTK main thread via `GLib.idle_add()`.  
On failure: keep the hardcoded fallback list, show a small warning label.

---

### Phase 3 — Progress feedback

### [x] TASK P3-1 — Progress dialog during generation
**File**: `svg_llm_dialog.py` — `GenerationProgressDialog`; `svg_llm.py` — `effect()`
Added `GenerationProgressDialog` (GTK3 `Gtk.Dialog` subclass). When GTK is available
it is shown after the main dialog closes: API calls run in a `threading.Thread`,
status lines appear in a log view, a pulsing `Gtk.ProgressBar` shows activity, and
a Cancel button sets `cancelled = True` to abort between variations. The dialog
automatically sends `Gtk.ResponseType.OK` on the GTK main thread via `GLib.idle_add`
when all variations finish. `effect()` reads `prog.results` (list of
`(svg_str | None, error_str | None)` tuples) and processes them after the dialog
closes.

---

### Phase 4 — History browser

#### [x] TASK P4-1 — Implement History tab as `Gtk.TreeView`
Already implemented in Round 1 Phase 1. Columns: `#`, `Date`, `Provider`, `Model`,
`Prompt (truncated)`. Double-click reloads the entry's prompt, provider, and model
into the dialog. "Clear history" button with confirmation dialog.

---

### Phase 5 — Prompt templates

#### [x] TASK P5-1 — Save/load named prompt templates
**File**: `svg_llm_dialog.py` — Advanced tab
Implemented via `_build_advanced_tab()`, `_on_save_template()`, `_on_load_template()`,
`_on_delete_template()`, `_load_templates_data()`, `_save_templates_data()`.
Templates stored in `svg_llm_templates.json` (added to `.gitignore`).
Fields saved: prompt, provider, model, preset, temperature, style, colour scheme,
complexity, system prompt, use_custom_system_prompt flag.

---

## Questions / Decisions Needed

### [?] History UI strategy
The INX format is static XML — it cannot dynamically populate a list from a JSON file.
Options:
- A) Write a second Python companion script (`svg_llm_history.py`) as a separate "History" extension.
- B) Write the last 10 prompts as plain-text labels into a static page (rebuilt on each run).
- C) Accept limitation, keep history as a JSON file that users can inspect manually.

---

## Done

> Round 1 — 2026-04-28

### Security / Critical
- [x] Revoked & replaced live OpenAI API key in `config.json`
- [x] Created `.gitignore` (excludes `config.json`, `svg_llm_history.json`, `__pycache__`)
- [x] Fixed inverted SSL: removed `ssl._create_unverified_context()` — now uses system-verified context
- [x] Implemented missing `get_config_value()` and `set_config_value()` helpers
- [x] Removed 3× debug `inkex.errormsg` from `get_api_key()`
- [x] Fixed `save_api_key()` / `get_api_key()` flat-key schema mismatch

### High — Functionality
- [x] Fixed hardcoded `C:\Users\youve\...` save directory in `.inx` (now empty → falls back to `~/Pictures/AI_Images`)
- [x] Added seed support to Google Gemini (`generationConfig.seed`) and Ollama (`options.seed`)
- [x] Implemented `embed_in_svg=False` path: saves SVG to disk + inserts `<image href>` link
- [x] Added `_validate_model_for_provider()` with a clear warning when model/provider mismatch
- [x] Added `_insert_image_link()` helper for external SVG linking

### Medium — Quality
- [x] Moved `save_svg_to_disk()` out of `_parse_response()` → now called in `effect()`
- [x] Added `.tail` copy in `import_element()` for correct `<text>` rendering
- [x] Replaced all bare `except:` with `except Exception:` throughout
- [x] Added exponential back-off (`time.sleep(2 ** attempt)`) to retry logic
- [x] Added canvas-overflow warning when variations extend beyond document bounds
- [x] Added step-by-step `inkex.utils.debug()` progress messages
- [x] Added Ollama endpoint validation (must start with `http://` or `https://`)
- [x] Removed unused `import ssl`; added `import time`

### GTK Migration — Phase 1 & 2
- [x] P1-1: Stripped `svg_llm.inx` to a minimal shell (fallback params preserved)
- [x] P1-2: Created `svg_llm_dialog.py` with full 8-tab GTK3 dialog
- [x] P1-3: Wired GTK dialog into `effect()` with try/except fallback to INX options
- [x] P1-4: Defined `GenerationOptions` dataclass (same field names as legacy `self.options`)
- [x] P2-1: Provider combo `changed` signal repopulates model combo
- [x] P2-2: Ollama model discovery via background thread + `GLib.idle_add()` update

---

> Round 3 — 2026-04-29

### GTK UI debug
- [x] GTK fallback `except Exception: pass` now calls `inkex.utils.debug(...)` with the actual error, so the Inkscape debug panel shows exactly why the GTK dialog failed to open

### NEW Features — Round 3
- [x] Azure OpenAI provider — added to both PROVIDERS dicts, `call_azure_api()` with `api-key:` header and deployment-name URL; endpoint row shown for both Azure and Ollama
- [x] Refine / edit workflow — `include_selection_svg` checkbox in Prompt tab; `_get_selection_as_svg()` serializes selected lxml elements; injected into prompt as `=== EXISTING SVG ===` block; INX fallback param added

---

> Round 4 — 2026-04-30

### Bug fix — GTK dialog crash on open
- [x] Moved `_on_provider_changed(self._provider_combo)` initial call from end of `_build_prompt_tab()` to after all tabs are built in `_build_ui()`. Previously `_model_combo` didn't exist yet when the call fired, causing `AttributeError: 'SVGLLMDialog' object has no attribute '_model_combo'` and the dialog never appeared.

### Improvements — Round 4
- [x] Replaced `Gtk.FileChooserButton` with `Gtk.Entry` + Browse button — `FileChooserButton` can misbehave on Windows Inkscape; the new Entry+button approach works cross-platform
- [x] Implemented real per-provider "Test key" ping in `_on_test_key()` — fires a background thread, sends a cheap request (model list / minimal message) to each provider, shows ✓ or ✗ result asynchronously
- [x] Fixed Azure false-positive in `_validate_model_for_provider()` — Azure uses a deployment name as the model which is always custom, so the warning is now suppressed for the `azure` provider
- [x] Save `default_provider`, `default_model`, `default_save_directory` back to `config.json` on Generate — next run pre-fills these values via `_load_defaults_from_config()`

### Full GTK migration — Round 4
- [x] Removed all `<param>` / `<page>` blocks from `svg_llm.inx` — file is now a pure 19-line shell (name, id, effect, script only)
- [x] Removed `add_arguments()` from `svg_llm.py` — no INX params to parse
- [x] Removed INX fallback branch from `effect()` — GTK is now required; if unavailable a clear `inkex.errormsg` is shown and the extension exits
- [x] Removed inline fallback `svg_results` loop — `GenerationProgressDialog` is always used

---

> Round 5 — 2026-04-30

### Bug fix
- [x] `_save_defaults_to_config` silently failed every run — `SVGLLMDialog` had no `config_path` attribute. Fixed by adding `config_path=""` parameter to `SVGLLMDialog.__init__` and passing `config_path=self.config_path` from `effect()`.

### UX Improvements — Round 5
- [x] Keyboard shortcuts — `Ctrl+Enter` triggers Generate; `Escape` triggers Cancel (`_on_key_press` handler wired via `key-press-event` in `_build_ui`)
- [x] Negative prompt field — single-line entry in Prompt tab ("things to avoid"); injected into `build_prompt()` as `Do NOT include: …`
- [x] Prompt character counter — live label below the prompt text area updates on every keystroke (`_on_prompt_buffer_changed`)
- [x] Preset hint label — small dim label below the Preset combo updates to a description of the selected preset (`PRESET_HINTS` dict + `_on_preset_changed`)
- [x] History tab search/filter — `Gtk.SearchEntry` above the TreeView filters rows in real-time by prompt, provider, or model text (`_on_history_search`)
- [x] Ollama endpoint re-trigger — editing the Endpoint entry while Ollama is selected schedules a debounced (900 ms) re-discovery of local models (`_on_endpoint_changed` / `_on_endpoint_changed_debounced`)
- [x] Copy SVG to clipboard — "Copy SVG to Clipboard" button in `GenerationProgressDialog` appears after generation completes; copies the last successful SVG text using `Gtk.Clipboard` (`_on_copy_svg`)

---

> Round 6 — 2026-05-01

### Feature: Externalise all AI prompts to editable Markdown files

- [x] `svg_llm_prompts.py` — new `PromptLoader` class reads `prompts/*.md` files with YAML frontmatter; falls back to hardcoded `DEFAULTS` dict when files are absent
- [x] `svg_llm.py` — imports `PromptLoader`, instantiates it in `__init__`, replaces all hardcoded prompt dicts in `build_prompt()` and `get_system_prompt()` with loader calls
- [x] `prompts/system_prompt.md` — detailed system prompt rules (no fences, start with `<svg`, valid SVG, etc.)
- [x] `prompts/presets/` — 7 files: `icon.md`, `illustration.md`, `diagram.md`, `pattern.md`, `logo.md`, `flowchart.md`, `infographic.md`
- [x] `prompts/styles/` — 10 files: `minimal.md`, `detailed.md`, `flat.md`, `outline.md`, `filled.md`, `geometric.md`, `organic.md`, `hand_drawn.md`, `isometric.md`, `cartoon.md`
- [x] `prompts/colors/` — 9 files: `monochrome.md`, `warm.md`, `cool.md`, `pastel.md`, `vibrant.md`, `grayscale.md`, `earth.md`, `neon.md`, `complementary.md`
- [x] `prompts/complexity/` — 3 files: `simple.md`, `medium.md`, `complex.md`
- [x] `prompts/strokes/` — 5 files: `thin.md`, `medium.md`, `thick.md`, `none.md`, `variable.md`

### Feature: SVG visual preview

- [x] Rsvg detection at module level in `svg_llm_dialog.py` (`_HAS_RSVG` / `_Rsvg` via `gi.require_version('Rsvg','2.0')`)
- [x] `SVGPreviewWindow` class — two-tab `Gtk.Notebook` (Preview via `Gtk.DrawingArea` + librsvg rendering; Source via read-only `Gtk.TextView`)
- [x] `_on_draw()` — uses `get_intrinsic_size_in_pixels()` (librsvg ≥ 2.52) with fallback to `get_dimensions()`; renders via `render_document()` with fallback to `render_cairo()`
- [x] "Preview SVG" button in `GenerationProgressDialog` — hidden by default, shown post-generation when `_HAS_RSVG` is True; opens `SVGPreviewWindow` (`_on_preview_svg`)
- [x] "Open Folder" button in `SVGPreviewWindow` bottom bar when `saved_path` is set

### Feature: Open save folder button

- [x] "Open Folder" button added to Save tab next to Browse in `_build_save_tab()`
- [x] `_on_open_save_folder()` handler — cross-platform: `os.startfile` (Windows), `open` (macOS), `xdg-open` (Linux); creates folder if it does not exist



### GTK Migration — Phase 3, 4, 5
- [x] P3-1: `GenerationProgressDialog` — API calls run in background thread with pulsing progress bar, log view, and Cancel support. `effect()` detects GTK availability and uses it when possible; falls back to inline loop otherwise.
- [x] P4-1: History tab `Gtk.TreeView` — already done in Round 1 (confirmed)
- [x] P5-1: Prompt template save/load in Advanced tab; stored in `svg_llm_templates.json`

### LOW Features
- [x] Ollama auto-discover — confirmed done via P2-2 (background thread on provider select)
- [x] System prompt customisation — Advanced tab with custom system prompt text area + toggle; all 4 provider call methods use `get_system_prompt()`
- [x] Layer target selection — Output tab combo lists document layers; `_get_target_layer()` resolves selection; used by `add_svg_to_document()` and `_insert_image_link()`
- [x] Post-generation auto-fit — Output tab checkbox; `_auto_fit_page()` resizes SVG page when multiple variations extend beyond canvas
- [x] Fixed pre-existing `load_history()` docstring syntax error (unmatched quote)
- [x] Added `TEMPLATES_FILENAME` constant and `templates_path` to extension class

---

## Summary of File Issues

| File | Issue | Severity |
|------|-------|----------|
| `config.json` | Live API key committed to repo | CRITICAL |
| `svg_llm.py:206` | SSL verification disabled for HTTPS | CRITICAL |
| `svg_llm.py:195` | Missing `get_config_value` / `set_config_value` | CRITICAL |
| `svg_llm.py:183` | Debug error messages in production | HIGH |
| `svg_llm.py:304` | `save_api_key` / `get_api_key` schema mismatch | HIGH |
| `svg_llm.inx:186` | Hardcoded user-specific save directory | HIGH |
| `svg_llm.py:750` | `save_svg_to_disk` inside response parser | MEDIUM |
| `svg_llm.py:950` | Silent `.tail` loss in element import | MEDIUM |
| `svg_llm.py:~280` | Bare `except:` clauses | MEDIUM |
| `svg_llm.py:555` | No retry back-off | MEDIUM |
| (missing) | No `.gitignore` | HIGH |
