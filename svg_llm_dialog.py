#!/usr/bin/env python3
"""
GTK3 dialog for AI SVG Generator Inkscape extension.

Replaces the static .inx dialog with a fully dynamic UI:
- Provider combo drives the model list (P2-1)
- Ollama endpoint discovery via background thread (P2-2)
- History browser with double-click replay (P4-1 partial)
- All settings map to GenerationOptions dataclass (P1-4)
"""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib
import json
import os
import subprocess
import sys

# Optional librsvg for SVG preview
_HAS_RSVG = False
_Rsvg = None
try:
    gi.require_version('Rsvg', '2.0')
    from gi.repository import Rsvg as _Rsvg  # type: ignore
    _HAS_RSVG = True
except Exception:
    pass
import ssl
import threading
import urllib.request
from dataclasses import dataclass


def _build_ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    return ssl.create_default_context()


_SSL_CONTEXT = _build_ssl_context()


# ==================== PROVIDER REGISTRY ====================

PROVIDERS = {
    'openai': {
        'name': 'OpenAI',
        'env_key': 'OPENAI_API_KEY',
        'config_key': 'openai_api_key',
        'models': ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-3.5-turbo',
                   'o1', 'o1-mini', 'o3-mini'],
        'supports_seed': True,
        'needs_endpoint': False,
        'endpoint_placeholder': '',
        'supports_fetch_models': True,
    },
    'anthropic': {
        'name': 'Anthropic Claude',
        'env_key': 'ANTHROPIC_API_KEY',
        'config_key': 'anthropic_api_key',
        'models': [
            'claude-opus-4-5',
            'claude-sonnet-4-5',
            'claude-3-5-sonnet-20241022',
            'claude-3-5-haiku-20241022',
            'claude-3-opus-20240229',
            'claude-3-haiku-20240307',
        ],
        'supports_seed': False,
        'needs_endpoint': False,
        'endpoint_placeholder': '',
        'supports_fetch_models': True,
    },
    'google': {
        'name': 'Google Gemini',
        'env_key': 'GOOGLE_API_KEY',
        'config_key': 'google_api_key',
        'models': ['gemini-2.0-flash', 'gemini-2.0-flash-lite',
                   'gemini-1.5-pro', 'gemini-1.5-flash', 'gemini-1.5-flash-8b'],
        'supports_seed': True,
        'needs_endpoint': False,
        'endpoint_placeholder': '',
        'supports_fetch_models': True,
    },
    'azure': {
        'name': 'Azure OpenAI',
        'env_key': 'AZURE_OPENAI_API_KEY',
        'config_key': 'azure_openai_api_key',
        'models': ['gpt-4o', 'gpt-4-turbo', 'gpt-35-turbo'],
        'supports_seed': True,
        'needs_endpoint': True,
        'endpoint_placeholder': 'https://your-resource.openai.azure.com',
        'supports_fetch_models': True,
    },
    'ollama': {
        'name': 'Ollama (Local)',
        'env_key': '',
        'config_key': '',
        'models': ['llama3.2', 'llama3.1', 'qwen2.5-coder', 'codellama', 'mistral'],
        'supports_seed': True,
        'needs_endpoint': True,
        'endpoint_placeholder': 'http://localhost:11434',
        'supports_fetch_models': True,
    },
    'custom_openai': {
        'name': 'Custom (OpenAI-compatible)',
        'env_key': 'CUSTOM_OPENAI_API_KEY',
        'config_key': 'custom_openai_api_key',
        'models': ['custom-model'],
        'supports_seed': True,
        'needs_endpoint': True,
        'endpoint_placeholder': 'http://localhost:1234/v1  or  https://api.groq.com/openai/v1',
        'supports_fetch_models': True,
    },
}


# ==================== PRESET HINTS ====================

PRESET_HINTS = {
    'none':        '',
    'icon':        'Simple, recognizable UI icon — clear shapes, minimal detail.',
    'illustration':'Artistic illustration with visual appeal and appropriate detail.',
    'diagram':     'Clear, informative diagram with proper labels and connections.',
    'pattern':     'Seamless repeating pattern that tiles correctly in all directions.',
    'logo':        'Professional, scalable logo that is memorable at any size.',
    'flowchart':   'Flowchart with boxes, decision diamonds, arrows, and labels.',
    'infographic': 'Data-visualization graphic with charts, icons, and callouts.',
}


# ==================== OPTIONS DATACLASS ====================

@dataclass
class GenerationOptions:
    """All generation settings — mirrors the legacy argparse Namespace."""
    provider: str = "openai"
    api_key: str = ""
    use_env_key: bool = True
    use_config_key: bool = True
    save_api_key: bool = False
    api_endpoint: str = ""
    prompt: str = ""
    prompt_preset: str = "none"
    use_selection_context: bool = False
    model: str = "gpt-4o"
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
    system_prompt: str = ""
    use_custom_system_prompt: bool = False
    target_layer: str = ""
    auto_fit_page: bool = False
    include_selection_svg: bool = False
    negative_prompt: str = ""


# ==================== WIDGET HELPERS ====================

def _make_combo(items, active_value=None):
    """Create a ComboBoxText from (value, label) pairs."""
    combo = Gtk.ComboBoxText()
    active_idx = 0
    for i, (val, label) in enumerate(items):
        combo.append(val, label)
        if val == active_value:
            active_idx = i
    combo.set_active(active_idx)
    return combo


def _make_row(label_text, widget, tooltip=None):
    """Horizontal box: fixed-width label + expanding widget."""
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    lbl = Gtk.Label(label=label_text, xalign=0)
    lbl.set_width_chars(22)
    box.pack_start(lbl, False, False, 0)
    box.pack_start(widget, True, True, 0)
    if tooltip:
        widget.set_tooltip_text(tooltip)
    return box


# ==================== MAIN DIALOG ====================

class SVGLLMDialog(Gtk.Window):
    """
    Full-featured GTK3 dialog for the AI SVG Generator extension.
    Opens on effect() call; returns a GenerationOptions via get_options().
    """

    def __init__(self, config, history_path, templates_path="", config_path="",
                 has_selection=False, layers=None):
        super().__init__(title="AI SVG Generator")
        self.set_modal(True)
        self.set_keep_above(True)
        self._accepted = False
        self.config = config or {}
        self.config_path = config_path
        self.history_path = history_path
        self.templates_path = templates_path
        self.has_selection = has_selection
        self.layers = layers or []
        self.set_default_size(640, 560)
        self.set_border_width(8)
        self._build_ui()
        self._load_defaults_from_config()
        self.connect("delete-event", self._on_delete)
        self.show_all()

    def _on_delete(self, widget, event):
        self._accepted = False
        Gtk.main_quit()
        return False

    def _on_cancel(self, *_):
        self._accepted = False
        Gtk.main_quit()

    def _on_generate(self, *_):
        self._accepted = True
        Gtk.main_quit()

    def _on_key_press(self, widget, event):
        """Ctrl+Enter → Generate; Escape → Cancel."""
        from gi.repository import Gdk
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        if event.keyval == Gdk.KEY_Return and ctrl:
            self._on_generate()
        elif event.keyval == Gdk.KEY_Escape:
            self._on_cancel()
        return False

    # ── UI construction ──────────────────────────────────────

    def _build_ui(self):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.add(content)

        self._notebook = Gtk.Notebook()
        content.pack_start(self._notebook, True, True, 0)

        self._build_prompt_tab()
        self._build_model_tab()
        self._build_size_tab()
        self._build_style_tab()
        self._build_output_tab()
        self._build_save_tab()
        self._build_advanced_tab()
        self._build_history_tab()
        self._build_help_tab()

        # Now that all tabs are built, fire initial provider-changed to sync model combo
        self._on_provider_changed(self._provider_combo)

        # Keyboard shortcuts: Ctrl+Enter → Generate, Escape → Cancel
        self.connect("key-press-event", self._on_key_press)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_border_width(8)
        btn_cancel = Gtk.Button(label="Cancel")
        btn_cancel.connect("clicked", self._on_cancel)
        btn_generate = Gtk.Button(label="Generate")
        btn_generate.connect("clicked", self._on_generate)
        btn_generate.get_style_context().add_class("suggested-action")
        btn_box.pack_end(btn_generate, False, False, 0)
        btn_box.pack_end(btn_cancel, False, False, 0)
        content.pack_start(btn_box, False, False, 0)

    def _scrolled_vbox(self):
        """Scrollable, padded VBox for tab content."""
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        vbox.set_border_width(10)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.add(vbox)
        return sw, vbox

    def _section(self, text):
        lbl = Gtk.Label(xalign=0)
        lbl.set_markup(f"<b>{text}</b>")
        return lbl

    # ── Prompt tab ───────────────────────────────────────────

    def _build_prompt_tab(self):
        sw, vbox = self._scrolled_vbox()

        vbox.pack_start(self._section("Provider"), False, False, 0)

        provider_items = [(k, v['name']) for k, v in PROVIDERS.items()]
        self._provider_combo = _make_combo(provider_items, 'openai')
        vbox.pack_start(_make_row("Provider:", self._provider_combo), False, False, 0)

        # API key (masked) + Test button
        self._api_key_entry = Gtk.Entry()
        self._api_key_entry.set_visibility(False)
        self._api_key_entry.set_placeholder_text("Paste key here — or leave blank to use env/config")
        key_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        key_box.pack_start(self._api_key_entry, True, True, 0)
        self._test_key_btn = Gtk.Button(label="Test")
        self._test_key_btn.connect("clicked", self._on_test_key)
        key_box.pack_start(self._test_key_btn, False, False, 0)
        vbox.pack_start(_make_row("API Key:", key_box), False, False, 0)

        self._use_env_key_check = Gtk.CheckButton(
            label="Use environment variable (OPENAI_API_KEY / ANTHROPIC_API_KEY / GOOGLE_API_KEY)"
        )
        self._use_env_key_check.set_active(True)
        vbox.pack_start(self._use_env_key_check, False, False, 0)

        self._use_config_key_check = Gtk.CheckButton(label="Use saved key from config.json")
        self._use_config_key_check.set_active(True)
        vbox.pack_start(self._use_config_key_check, False, False, 0)

        self._save_api_key_check = Gtk.CheckButton(label="Save entered key to config.json")
        vbox.pack_start(self._save_api_key_check, False, False, 0)

        # Endpoint row — visible for Ollama and Azure
        self._endpoint_entry = Gtk.Entry()
        self._endpoint_entry.set_placeholder_text("http://localhost:11434")
        self._endpoint_entry.connect("changed", self._on_endpoint_changed)
        self._endpoint_row = _make_row("Endpoint:", self._endpoint_entry)
        vbox.pack_start(self._endpoint_row, False, False, 0)

        vbox.pack_start(Gtk.Separator(), False, False, 4)

        # Prompt
        vbox.pack_start(self._section("Prompt"), False, False, 0)

        preset_items = [
            ('none', 'None'), ('icon', 'Icon'), ('illustration', 'Illustration'),
            ('diagram', 'Diagram'), ('pattern', 'Pattern'), ('logo', 'Logo'),
            ('flowchart', 'Flowchart'), ('infographic', 'Infographic'),
        ]
        self._preset_combo = _make_combo(preset_items, 'none')
        self._preset_combo.connect("changed", self._on_preset_changed)
        vbox.pack_start(_make_row("Preset:", self._preset_combo), False, False, 0)

        self._preset_hint_label = Gtk.Label(label="", xalign=0)
        self._preset_hint_label.set_line_wrap(True)
        self._preset_hint_label.get_style_context().add_class("dim-label")
        vbox.pack_start(self._preset_hint_label, False, False, 0)

        vbox.pack_start(Gtk.Label(label="Describe the SVG:", xalign=0), False, False, 0)
        self._prompt_text = Gtk.TextView()
        self._prompt_text.set_wrap_mode(Gtk.WrapMode.WORD)
        self._prompt_text.set_accepts_tab(False)
        prompt_scroll = Gtk.ScrolledWindow()
        prompt_scroll.set_min_content_height(110)
        prompt_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        prompt_scroll.add(self._prompt_text)
        vbox.pack_start(prompt_scroll, True, True, 0)

        self._char_count_label = Gtk.Label(label="0 characters", xalign=1)
        self._char_count_label.get_style_context().add_class("dim-label")
        vbox.pack_start(self._char_count_label, False, False, 0)
        self._prompt_text.get_buffer().connect("changed", self._on_prompt_buffer_changed)

        vbox.pack_start(Gtk.Label(label="Negative prompt (things to avoid):", xalign=0), False, False, 0)
        self._negative_prompt_entry = Gtk.Entry()
        self._negative_prompt_entry.set_placeholder_text(
            "e.g. text, labels, shadows, photorealistic, 3D rendering"
        )
        self._negative_prompt_entry.set_tooltip_text(
            "The model will be instructed NOT to include these elements."
        )
        vbox.pack_start(self._negative_prompt_entry, False, False, 0)

        self._use_selection_check = Gtk.CheckButton(label="Use selected elements as style context")
        if not self.has_selection:
            self._use_selection_check.set_sensitive(False)
            self._use_selection_check.set_tooltip_text("Select elements in Inkscape first")
        vbox.pack_start(self._use_selection_check, False, False, 0)

        self._include_svg_check = Gtk.CheckButton(
            label="Include selected elements as raw SVG (refine/edit workflow)"
        )
        self._include_svg_check.set_tooltip_text(
            "Embeds the actual SVG code of the selected elements in the prompt.\n"
            "Use this when you want the model to modify or build on existing shapes."
        )
        if not self.has_selection:
            self._include_svg_check.set_sensitive(False)
        vbox.pack_start(self._include_svg_check, False, False, 0)

        # Wire provider-changed signal — initial call deferred to _build_ui
        # so that _model_combo exists when _on_provider_changed fires.
        self._provider_combo.connect("changed", self._on_provider_changed)

        self._notebook.append_page(sw, Gtk.Label(label="Prompt"))

    # ── Model tab ────────────────────────────────────────────

    def _build_model_tab(self):
        sw, vbox = self._scrolled_vbox()

        vbox.pack_start(self._section("Model Selection"), False, False, 0)

        self._model_combo = Gtk.ComboBoxText()
        self._ollama_status_label = Gtk.Label(label="", xalign=0)
        self._ollama_status_label.get_style_context().add_class("dim-label")
        model_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)

        # Row: combo + Refresh button
        model_row_h = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        model_row_h.pack_start(self._model_combo, True, True, 0)
        self._refresh_models_btn = Gtk.Button(label="⟳ Refresh")
        self._refresh_models_btn.set_tooltip_text(
            "Fetch available models from the provider API"
        )
        self._refresh_models_btn.connect("clicked", self._on_refresh_models)
        model_row_h.pack_start(self._refresh_models_btn, False, False, 0)

        model_box.pack_start(model_row_h, True, True, 0)
        model_box.pack_start(self._ollama_status_label, False, False, 0)

        # Custom model name entry (shown only for custom_openai)
        self._custom_model_entry = Gtk.Entry()
        self._custom_model_entry.set_placeholder_text("Enter model name, e.g. llama-3.3-70b-versatile")
        self._custom_model_row = _make_row("Custom model name:", self._custom_model_entry)
        self._custom_model_row.set_no_show_all(True)
        model_box.pack_start(self._custom_model_row, False, False, 0)

        vbox.pack_start(_make_row("Model:", model_box), False, False, 0)

        self._populate_model_combo('openai')

        vbox.pack_start(Gtk.Separator(), False, False, 4)
        vbox.pack_start(self._section("Generation Settings"), False, False, 0)

        self._temperature_spin = Gtk.SpinButton.new_with_range(0.0, 2.0, 0.1)
        self._temperature_spin.set_value(0.7)
        self._temperature_spin.set_digits(1)
        vbox.pack_start(_make_row(
            "Temperature:", self._temperature_spin,
            "0 = deterministic, 2 = very creative"
        ), False, False, 0)

        self._max_tokens_spin = Gtk.SpinButton.new_with_range(500, 8000, 100)
        self._max_tokens_spin.set_value(4000)
        vbox.pack_start(_make_row("Max tokens:", self._max_tokens_spin), False, False, 0)

        self._timeout_spin = Gtk.SpinButton.new_with_range(30, 300, 10)
        self._timeout_spin.set_value(60)
        vbox.pack_start(_make_row("Timeout (s):", self._timeout_spin), False, False, 0)

        self._retry_spin = Gtk.SpinButton.new_with_range(0, 5, 1)
        self._retry_spin.set_value(2)
        vbox.pack_start(_make_row("Retries:", self._retry_spin,
            "Exponential back-off between retries"
        ), False, False, 0)

        self._seed_spin = Gtk.SpinButton.new_with_range(-1, 999999, 1)
        self._seed_spin.set_value(-1)
        vbox.pack_start(_make_row("Seed (-1 = random):", self._seed_spin,
            "Fixed seed for reproducible results (OpenAI, Gemini, Ollama). Anthropic ignores this."
        ), False, False, 0)

        self._notebook.append_page(sw, Gtk.Label(label="Model"))

    # ── Size tab ─────────────────────────────────────────────

    def _build_size_tab(self):
        sw, vbox = self._scrolled_vbox()

        vbox.pack_start(self._section("Dimensions"), False, False, 0)

        size_items = [
            ('small',  'Small  (200px base)'),
            ('medium', 'Medium (400px base)'),
            ('large',  'Large  (600px base)'),
            ('xlarge', 'Extra Large (800px base)'),
            ('custom', 'Custom'),
        ]
        self._size_combo = _make_combo(size_items, 'medium')
        self._size_combo.connect("changed", self._on_size_changed)
        vbox.pack_start(_make_row("Size preset:", self._size_combo), False, False, 0)

        ratio_items = [
            ('square',     'Square (1:1)'),
            ('landscape',  'Landscape (4:3)'),
            ('portrait',   'Portrait (3:4)'),
            ('widescreen', 'Widescreen (16:9)'),
            ('banner',     'Banner (3:1)'),
            ('icon',       'Icon (1:1)'),
        ]
        self._ratio_combo = _make_combo(ratio_items, 'square')
        vbox.pack_start(_make_row("Aspect ratio:", self._ratio_combo), False, False, 0)

        vbox.pack_start(self._section("Custom Size"), False, False, 4)

        self._custom_width_spin = Gtk.SpinButton.new_with_range(50, 4000, 10)
        self._custom_width_spin.set_value(400)
        self._custom_width_row = _make_row("Width (px):", self._custom_width_spin)
        vbox.pack_start(self._custom_width_row, False, False, 0)

        self._custom_height_spin = Gtk.SpinButton.new_with_range(50, 4000, 10)
        self._custom_height_spin.set_value(400)
        self._custom_height_row = _make_row("Height (px):", self._custom_height_spin)
        vbox.pack_start(self._custom_height_row, False, False, 0)

        self._on_size_changed(self._size_combo)

        self._notebook.append_page(sw, Gtk.Label(label="Size"))

    # ── Style tab ────────────────────────────────────────────

    def _build_style_tab(self):
        sw, vbox = self._scrolled_vbox()

        vbox.pack_start(self._section("Visual Style"), False, False, 0)

        style_items = [
            ('none',       'None (Let AI decide)'),
            ('minimal',    'Minimal / Clean'),
            ('detailed',   'Detailed'),
            ('flat',       'Flat Design'),
            ('outline',    'Outline / Line Art'),
            ('filled',     'Filled Shapes'),
            ('geometric',  'Geometric'),
            ('organic',    'Organic / Natural'),
            ('hand_drawn', 'Hand Drawn / Sketchy'),
            ('isometric',  'Isometric 3D'),
            ('cartoon',    'Cartoon / Comic'),
        ]
        self._style_combo = _make_combo(style_items, 'none')
        vbox.pack_start(_make_row("Style:", self._style_combo), False, False, 0)

        complexity_items = [
            ('simple',  'Simple (10–15 elements)'),
            ('medium',  'Medium (20–40 elements)'),
            ('complex', 'Complex (many elements)'),
        ]
        self._complexity_combo = _make_combo(complexity_items, 'medium')
        vbox.pack_start(_make_row("Complexity:", self._complexity_combo), False, False, 0)

        vbox.pack_start(self._section("Colors"), False, False, 4)

        color_items = [
            ('any',           'Any Colors'),
            ('monochrome',    'Monochrome'),
            ('warm',          'Warm Colors'),
            ('cool',          'Cool Colors'),
            ('pastel',        'Pastel'),
            ('vibrant',       'Vibrant'),
            ('grayscale',     'Grayscale'),
            ('earth',         'Earth Tones'),
            ('neon',          'Neon'),
            ('complementary', 'Complementary'),
        ]
        self._color_combo = _make_combo(color_items, 'any')
        vbox.pack_start(_make_row("Color scheme:", self._color_combo), False, False, 0)

        stroke_items = [
            ('any',      'Any'),
            ('thin',     'Thin (1–2px)'),
            ('medium',   'Medium (2–4px)'),
            ('thick',    'Thick (4–8px)'),
            ('none',     'No Strokes'),
            ('variable', 'Variable Width'),
        ]
        self._stroke_combo = _make_combo(stroke_items, 'any')
        vbox.pack_start(_make_row("Stroke style:", self._stroke_combo), False, False, 0)

        self._gradients_check = Gtk.CheckButton(label="Allow gradients")
        self._gradients_check.set_active(True)
        vbox.pack_start(self._gradients_check, False, False, 0)

        self._notebook.append_page(sw, Gtk.Label(label="Style"))

    # ── Output tab ───────────────────────────────────────────

    def _build_output_tab(self):
        sw, vbox = self._scrolled_vbox()

        vbox.pack_start(self._section("Placement"), False, False, 0)

        pos_items = [
            ('center',    'Center of Document'),
            ('origin',    'Origin (0, 0)'),
            ('selection', 'Next to Selection'),
        ]
        self._position_combo = _make_combo(pos_items, 'center')
        vbox.pack_start(_make_row("Position:", self._position_combo), False, False, 0)

        vbox.pack_start(self._section("Grouping"), False, False, 4)

        self._add_group_check = Gtk.CheckButton(label="Wrap generated elements in a group")
        self._add_group_check.set_active(True)
        vbox.pack_start(self._add_group_check, False, False, 0)

        self._group_name_entry = Gtk.Entry()
        self._group_name_entry.set_placeholder_text("Optional — leave blank for auto ID")
        vbox.pack_start(_make_row("Group name:", self._group_name_entry), False, False, 0)

        vbox.pack_start(self._section("Variations"), False, False, 4)

        self._variations_spin = Gtk.SpinButton.new_with_range(1, 4, 1)
        self._variations_spin.set_value(1)
        vbox.pack_start(_make_row("Variations:", self._variations_spin,
            "Generate multiple interpretations side by side"
        ), False, False, 0)

        vbox.pack_start(self._section("Additional Options"), False, False, 4)

        self._animations_check = Gtk.CheckButton(label="Include animations (CSS / SMIL)")
        vbox.pack_start(self._animations_check, False, False, 0)

        self._accessibility_check = Gtk.CheckButton(label="Add accessibility tags (title / desc)")
        vbox.pack_start(self._accessibility_check, False, False, 0)

        self._optimize_check = Gtk.CheckButton(label="Request optimized paths")
        self._optimize_check.set_active(True)
        vbox.pack_start(self._optimize_check, False, False, 0)

        self._save_history_check = Gtk.CheckButton(label="Save prompt to history")
        self._save_history_check.set_active(True)
        vbox.pack_start(self._save_history_check, False, False, 0)

        vbox.pack_start(self._section("Layer"), False, False, 4)
        layer_items = [('', 'Current Layer')] + [(lid, lbl) for lid, lbl in self.layers]
        self._layer_combo = _make_combo(layer_items, '')
        vbox.pack_start(_make_row(
            "Target layer:", self._layer_combo,
            "Layer to place generated elements on"
        ), False, False, 0)

        self._auto_fit_check = Gtk.CheckButton(label="Expand page to fit all generated content")
        self._auto_fit_check.set_tooltip_text(
            "Resize the SVG page so all generated variations are fully visible."
        )
        vbox.pack_start(self._auto_fit_check, False, False, 0)

        self._notebook.append_page(sw, Gtk.Label(label="Output"))

    # ── Save tab ─────────────────────────────────────────────

    def _build_save_tab(self):
        sw, vbox = self._scrolled_vbox()

        vbox.pack_start(self._section("Save to Disk"), False, False, 0)

        self._save_to_disk_check = Gtk.CheckButton(label="Save generated SVG to disk")
        self._save_to_disk_check.set_active(True)
        vbox.pack_start(self._save_to_disk_check, False, False, 0)

        # Directory — Entry + Browse button (works cross-platform, no FileChooserButton issues)
        default_dir = os.path.expanduser("~/Pictures/AI_Images")
        self._save_dir_entry = Gtk.Entry()
        self._save_dir_entry.set_text(default_dir)
        self._save_dir_entry.set_tooltip_text("Directory where SVG files will be saved")
        browse_btn = Gtk.Button(label="Browse…")
        browse_btn.connect("clicked", self._on_browse_save_dir)
        open_folder_btn = Gtk.Button(label="Open Folder")
        open_folder_btn.set_tooltip_text("Open the save directory in your file manager")
        open_folder_btn.connect("clicked", self._on_open_save_folder)
        dir_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        dir_box.pack_start(self._save_dir_entry, True, True, 0)
        dir_box.pack_start(browse_btn, False, False, 0)
        dir_box.pack_start(open_folder_btn, False, False, 0)
        vbox.pack_start(_make_row("Save directory:", dir_box), False, False, 0)

        self._filename_prefix_entry = Gtk.Entry()
        self._filename_prefix_entry.set_text("svg_image")
        vbox.pack_start(_make_row("Filename prefix:", self._filename_prefix_entry), False, False, 0)

        hint = Gtk.Label(label="Files saved as: prefix_YYYYMMDD_HHMMSS[_seedN].svg", xalign=0)
        hint.get_style_context().add_class("dim-label")
        vbox.pack_start(hint, False, False, 0)

        vbox.pack_start(self._section("SVG Embedding"), False, False, 8)

        self._embed_check = Gtk.CheckButton(label="Embed SVG inline (self-contained)")
        self._embed_check.set_active(True)
        self._embed_check.set_tooltip_text(
            "Checked: SVG elements are inserted directly into the Inkscape document.\n"
            "Unchecked: An <image href=...> link is inserted pointing to the saved file.\n"
            "          Requires 'Save to disk' to be enabled."
        )
        vbox.pack_start(self._embed_check, False, False, 0)

        self._notebook.append_page(sw, Gtk.Label(label="Save"))

    # ── History tab ──────────────────────────────────────────

    def _build_history_tab(self):
        sw, vbox = self._scrolled_vbox()

        vbox.pack_start(self._section("Generation History"), False, False, 0)
        hint = Gtk.Label(label="Double-click a row to reload that prompt.", xalign=0)
        hint.get_style_context().add_class("dim-label")
        vbox.pack_start(hint, False, False, 0)

        # Search / filter
        self._history_search_entry = Gtk.SearchEntry()
        self._history_search_entry.set_placeholder_text("Filter by prompt, provider or model…")
        self._history_search_entry.connect("search-changed", self._on_history_search)
        vbox.pack_start(self._history_search_entry, False, False, 0)

        # Store: index, date, provider, model, prompt_preview
        self._history_store = Gtk.ListStore(str, str, str, str, str)
        tv = Gtk.TreeView(model=self._history_store)
        for i, col_name in enumerate(["#", "Date", "Provider", "Model", "Prompt"]):
            renderer = Gtk.CellRendererText()
            col = Gtk.TreeViewColumn(col_name, renderer, text=i)
            col.set_resizable(True)
            if i == 4:
                col.set_expand(True)
            tv.append_column(col)
        tv.connect("row-activated", self._on_history_row_activated)

        tv_sw = Gtk.ScrolledWindow()
        tv_sw.set_min_content_height(260)
        tv_sw.add(tv)
        vbox.pack_start(tv_sw, True, True, 0)

        btn_clear = Gtk.Button(label="Clear History")
        btn_clear.connect("clicked", self._on_clear_history)
        vbox.pack_start(btn_clear, False, False, 4)

        self._load_history_into_view()
        self._notebook.append_page(sw, Gtk.Label(label="History"))

    # ── Help tab ─────────────────────────────────────────────

    def _build_help_tab(self):
        sw, vbox = self._scrolled_vbox()

        sections = [
            ("Getting Started", [
                "1. Choose a provider (OpenAI, Anthropic, Google, or Ollama)",
                "2. Enter your API key — or set the environment variable and check the box",
                "3. Describe what you want to create in the Prompt tab",
                "4. Adjust Style, Size, and Output options as needed",
                "5. Click Generate",
            ]),
            ("API Keys", [
                "• OpenAI:    https://platform.openai.com/api-keys",
                "• Anthropic: https://console.anthropic.com/",
                "• Google:    https://aistudio.google.com/apikey",
                "• Ollama:    No key needed — runs locally on your machine",
            ]),
            ("Example Prompts", [
                "• A simple house icon with a red chimney",
                "• Three overlapping circles forming a Venn diagram",
                "• A tree with detailed leaves and roots",
                "• An abstract geometric pattern with interlocking triangles",
                "• A flowchart showing a user login process",
                "• A flat-design world map with country outlines",
            ]),
            ("Tips", [
                "• Presets (icon, diagram, etc.) give the model better context",
                "• Select Inkscape elements first to match their style",
                "• Temperature 0.3–0.5 for predictable, structured output",
                "• Temperature 0.8–1.2 for creative, varied output",
                "• Use the History tab to replay and refine past prompts",
                "• Ollama models update automatically when you switch to it",
                "• API usage costs apply for cloud providers (not Ollama)",
            ]),
        ]

        for title, items in sections:
            vbox.pack_start(self._section(title), False, False, 4)
            for item in items:
                lbl = Gtk.Label(label=item, xalign=0)
                lbl.set_selectable(True)
                vbox.pack_start(lbl, False, False, 0)
            vbox.pack_start(Gtk.Separator(), False, False, 4)

        self._notebook.append_page(sw, Gtk.Label(label="Help"))

    # ── Signal handlers ──────────────────────────────────────

    def _on_provider_changed(self, combo):
        """P2-1: Update model combo when provider changes."""
        provider = combo.get_active_id() or 'openai'
        self._populate_model_combo(provider)

        pinfo = PROVIDERS.get(provider, {})
        needs_endpoint = pinfo.get('needs_endpoint', False)
        self._endpoint_row.set_visible(needs_endpoint)
        if needs_endpoint:
            placeholder = pinfo.get('endpoint_placeholder', '')
            self._endpoint_entry.set_placeholder_text(placeholder)
            # Pre-fill default for Ollama if entry is empty
            if provider == 'ollama' and not self._endpoint_entry.get_text().strip():
                self._endpoint_entry.set_text('')  # leave blank — placeholder guides user
            elif provider == 'azure' and not self._endpoint_entry.get_text().strip():
                self._endpoint_entry.set_text('')

        # Show/hide seed note
        supports_seed = PROVIDERS.get(provider, {}).get('supports_seed', True)
        if hasattr(self, '_seed_spin'):
            self._seed_spin.set_tooltip_text(
                "Fixed seed for reproducible results."
                if supports_seed else
                "Anthropic does not support seed — this value is ignored."
            )

        # Show/hide custom model name entry (only for custom_openai)
        if hasattr(self, '_custom_model_row'):
            self._custom_model_row.set_visible(provider == 'custom_openai')

        # P2-2: Auto-discover Ollama models
        if provider == 'ollama':
            self._discover_ollama_models()

    def _on_browse_save_dir(self, _btn):
        """Open a folder-chooser dialog and put the result in the entry."""
        dlg = Gtk.FileChooserDialog(
            title="Select save directory",
            transient_for=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        dlg.add_buttons(
            "_Cancel", Gtk.ResponseType.CANCEL,
            "_Select", Gtk.ResponseType.ACCEPT,
        )
        current = self._save_dir_entry.get_text().strip()
        if current and os.path.isdir(current):
            dlg.set_current_folder(current)
        if dlg.run() == Gtk.ResponseType.ACCEPT:
            self._save_dir_entry.set_text(dlg.get_filename())
        dlg.destroy()

    def _on_open_save_folder(self, _btn):
        """Open the save directory in the system file manager."""
        folder = self._save_dir_entry.get_text().strip()
        if not folder:
            return
        if not os.path.isdir(folder):
            try:
                os.makedirs(folder, exist_ok=True)
            except Exception:
                return
        try:
            if sys.platform == 'win32':
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', folder])
            else:
                subprocess.Popen(['xdg-open', folder])
        except Exception:
            pass

    def _on_size_changed(self, combo):
        is_custom = combo.get_active_id() == 'custom'
        self._custom_width_row.set_visible(is_custom)
        self._custom_height_row.set_visible(is_custom)

    def _on_preset_changed(self, combo):
        """Update the preset hint label when a preset is selected."""
        preset_id = combo.get_active_id() or 'none'
        hint = PRESET_HINTS.get(preset_id, '')
        if hasattr(self, '_preset_hint_label'):
            self._preset_hint_label.set_text(hint)

    def _on_prompt_buffer_changed(self, buf):
        """Update character counter below the prompt text area."""
        n = buf.get_char_count()
        if hasattr(self, '_char_count_label'):
            self._char_count_label.set_text(f"{n} character{'s' if n != 1 else ''}")

    def _on_endpoint_changed(self, entry):
        """Re-trigger Ollama model discovery when the endpoint URL is edited."""
        if self._provider_combo.get_active_id() != 'ollama':
            return
        # Debounce: cancel any pending timer and restart it
        if hasattr(self, '_ollama_discover_timer_id') and self._ollama_discover_timer_id:
            GLib.source_remove(self._ollama_discover_timer_id)
        self._ollama_discover_timer_id = GLib.timeout_add(
            900, self._on_endpoint_changed_debounced
        )

    def _on_endpoint_changed_debounced(self):
        self._discover_ollama_models()
        self._ollama_discover_timer_id = None
        return False  # do not repeat

    def _on_history_search(self, entry):
        """Filter the history TreeView by the search query."""
        query = entry.get_text().strip().lower()
        self._history_store.clear()
        for i, entry_data in enumerate(self._load_history_data(), start=1):
            prompt = entry_data.get('prompt', '')
            provider = entry_data.get('provider', '')
            model = entry_data.get('model', '')
            if query and query not in prompt.lower() \
                    and query not in provider.lower() \
                    and query not in model.lower():
                continue
            ts = entry_data.get('timestamp', '')[:16].replace('T', ' ')
            preview = (prompt[:60] + '\u2026') if len(prompt) > 60 else prompt
            self._history_store.append([str(i), ts, provider, model, preview])

    def _on_test_key(self, button):
        key = self._api_key_entry.get_text().strip()
        provider = self._provider_combo.get_active_id() or 'openai'
        if not key:
            self._alert("No key entered. Enter an API key in the field above.")
            return

        button.set_sensitive(False)
        button.set_label("…")

        def _ping():
            ok, msg = self._ping_provider(provider, key)
            GLib.idle_add(self._finish_test_key, button, ok, msg)

        threading.Thread(target=_ping, daemon=True).start()

    def _ping_provider(self, provider, key):
        """Make the cheapest possible request to verify the key is accepted."""
        try:
            if provider == 'openai':
                req = urllib.request.Request(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {key}"},
                )
                with urllib.request.urlopen(req, timeout=8, context=_SSL_CONTEXT) as r:
                    r.read()
                return True, "Key accepted ✓"

            elif provider == 'anthropic':
                # Anthropic has no free list endpoint; send a minimal message
                import json as _json
                payload = _json.dumps({
                    "model": "claude-3-haiku-20240307",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "hi"}],
                }).encode()
                req = urllib.request.Request(
                    "https://api.anthropic.com/v1/messages",
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "x-api-key": key,
                        "anthropic-version": "2023-06-01",
                    },
                )
                with urllib.request.urlopen(req, timeout=10, context=_SSL_CONTEXT) as r:
                    r.read()
                return True, "Key accepted ✓"

            elif provider == 'google':
                req = urllib.request.Request(
                    f"https://generativelanguage.googleapis.com/v1beta/models?key={key}",
                )
                with urllib.request.urlopen(req, timeout=8, context=_SSL_CONTEXT) as r:
                    r.read()
                return True, "Key accepted ✓"

            elif provider == 'azure':
                endpoint = self._endpoint_entry.get_text().strip().rstrip('/')
                if not endpoint:
                    return False, "Enter the Azure endpoint URL first."
                req = urllib.request.Request(
                    f"{endpoint}/openai/models?api-version=2024-08-01-preview",
                    headers={"api-key": key},
                )
                with urllib.request.urlopen(req, timeout=8, context=_SSL_CONTEXT) as r:
                    r.read()
                return True, "Key accepted ✓"

            elif provider == 'ollama':
                endpoint = self._endpoint_entry.get_text().strip() or "http://localhost:11434"
                req = urllib.request.Request(f"{endpoint.rstrip('/')}/api/tags")
                with urllib.request.urlopen(req, timeout=5, context=_SSL_CONTEXT) as r:
                    r.read()
                return True, "Ollama reachable ✓"

            else:
                return False, f"No test defined for provider '{provider}'."

        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return False, f"Key rejected — HTTP {e.code} Unauthorized ✗"
            return False, f"HTTP {e.code} — key may still be valid (server error)"
        except Exception as exc:
            return False, f"Connection error: {exc}"

    def _finish_test_key(self, button, ok, msg):
        button.set_label("Test")
        button.set_sensitive(True)
        self._alert(msg)
        return False

    def _on_history_row_activated(self, tv, path, column):
        """Double-click row: reload prompt and settings into dialog."""
        history = self._load_history_data()
        row = self._history_store[path]
        idx = int(row[0]) - 1
        if 0 <= idx < len(history):
            entry = history[idx]
            self._prompt_text.get_buffer().set_text(entry.get('prompt', ''))
            provider = entry.get('provider', 'openai')
            self._provider_combo.set_active_id(provider)
            model = entry.get('model', '')
            if model:
                self._model_combo.set_active_id(model)
            self._notebook.set_current_page(0)

    def _on_clear_history(self, button):
        dlg = Gtk.MessageDialog(
            transient_for=self,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
        )
        dlg.set_markup(GLib.markup_escape_text("Clear all generation history?"))
        response = dlg.run()
        dlg.destroy()
        if response == Gtk.ResponseType.YES:
            try:
                if os.path.exists(self.history_path):
                    os.remove(self.history_path)
            except Exception:
                pass
            self._history_store.clear()

    # ── Dynamic helpers ──────────────────────────────────────

    def _populate_model_combo(self, provider):
        """Replace model combo content for the given provider."""
        current = self._model_combo.get_active_id() if hasattr(self, '_model_combo') else None
        self._model_combo.remove_all()
        for m in PROVIDERS.get(provider, {}).get('models', []):
            self._model_combo.append(m, m)
        if current and not self._model_combo.set_active_id(current):
            self._model_combo.set_active(0)
        elif not current:
            self._model_combo.set_active(0)

    def _discover_ollama_models(self):
        """P2-2: Background thread queries Ollama /api/tags, updates combo on GTK thread."""
        endpoint = self._endpoint_entry.get_text().strip() or "http://localhost:11434"
        GLib.idle_add(lambda: self._ollama_status_label.set_text("Discovering models…") or False)

        def _fetch():
            try:
                url = f"{endpoint.rstrip('/')}/api/tags"
                with urllib.request.urlopen(url, timeout=3, context=_SSL_CONTEXT) as resp:
                    data = json.loads(resp.read().decode())
                models = [m['name'] for m in data.get('models', [])]
                if models:
                    GLib.idle_add(self._apply_ollama_models, models)
                else:
                    GLib.idle_add(lambda: self._ollama_status_label.set_text(
                        "No models found — using defaults"
                    ) or False)
            except Exception as e:
                GLib.idle_add(lambda: self._ollama_status_label.set_text(
                    f"Could not reach Ollama ({e}) — using defaults"
                ) or False)

        threading.Thread(target=_fetch, daemon=True).start()

    def _apply_ollama_models(self, models):
        """Called on GTK main thread after Ollama discovery (GLib.idle_add)."""
        self._model_combo.remove_all()
        for m in models:
            self._model_combo.append(m, m)
        self._model_combo.set_active(0)
        self._ollama_status_label.set_text(f"{len(models)} model(s) found")
        return False  # stop idle_add repeating

    def _on_refresh_models(self, _btn):
        """Fetch live model list from the selected provider."""
        provider = self._provider_combo.get_active_id() or 'openai'
        api_key = self._api_key_entry.get_text().strip()
        endpoint = self._endpoint_entry.get_text().strip() if hasattr(self, '_endpoint_entry') else ''

        self._ollama_status_label.set_text("Fetching models…")

        # Map provider id to module name
        _MODULE_MAP = {
            'openai':       'svg_llm_openai',
            'anthropic':    'svg_llm_anthropic',
            'google':       'svg_llm_google',
            'azure':        'svg_llm_azure',
            'ollama':       'svg_llm_ollama',
            'custom_openai':'svg_llm_custom',
        }
        module_name = _MODULE_MAP.get(provider)
        if not module_name:
            self._ollama_status_label.set_text(f"No fetch support for '{provider}'")
            return

        def _fetch():
            try:
                import importlib
                mod = importlib.import_module(module_name)
                models = mod.fetch_models(
                    api_key=api_key,
                    endpoint=endpoint,
                    ssl_context=_SSL_CONTEXT,
                )
                if models:
                    GLib.idle_add(self._apply_fetched_models, models)
                else:
                    GLib.idle_add(lambda: self._ollama_status_label.set_text(
                        "No models returned — using defaults"
                    ) or False)
            except Exception as e:
                GLib.idle_add(lambda: self._ollama_status_label.set_text(
                    f"Error fetching models: {e}"
                ) or False)

        threading.Thread(target=_fetch, daemon=True).start()

    def _apply_fetched_models(self, models):
        """Update model combo from a fetched model list (GTK main thread)."""
        self._model_combo.remove_all()
        for m in models:
            self._model_combo.append(m, m)
        if models:
            self._model_combo.set_active(0)
        self._ollama_status_label.set_text(f"{len(models)} model(s) loaded")
        return False

    def _load_history_data(self):
        if os.path.exists(self.history_path):
            try:
                with open(self.history_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def _load_history_into_view(self):
        self._history_store.clear()
        for i, entry in enumerate(self._load_history_data(), start=1):
            ts = entry.get('timestamp', '')[:16].replace('T', ' ')
            provider = entry.get('provider', '')
            model = entry.get('model', '')
            prompt = entry.get('prompt', '')
            preview = (prompt[:60] + '…') if len(prompt) > 60 else prompt
            self._history_store.append([str(i), ts, provider, model, preview])

    def _load_defaults_from_config(self):
        """Pre-populate fields from saved config.json values."""
        provider = self.config.get('default_provider', 'openai')
        self._provider_combo.set_active_id(provider)

        save_dir = self.config.get('default_save_directory', '')
        if save_dir:
            self._save_dir_entry.set_text(save_dir)

        model = self.config.get('default_model', '')
        if model:
            self._model_combo.set_active_id(model)

    def _alert(self, message):
        dlg = Gtk.MessageDialog(
            transient_for=self,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
        )
        dlg.set_markup(GLib.markup_escape_text(message))
        dlg.run()
        dlg.destroy()

    # ── Advanced tab ─────────────────────────────────────────

    def _build_advanced_tab(self):
        sw, vbox = self._scrolled_vbox()

        # ── System prompt ────────────────────────────────────
        vbox.pack_start(self._section("System Prompt"), False, False, 0)
        hint = Gtk.Label(
            label="Override the default instruction sent to the model as the system role.",
            xalign=0
        )
        hint.set_line_wrap(True)
        hint.get_style_context().add_class("dim-label")
        vbox.pack_start(hint, False, False, 0)

        DEFAULT_SYSTEM = (
            "You are an expert SVG code generator. You only respond with valid, clean SVG code "
            "without any explanation or markdown formatting. Never include ```svg or ``` markers. "
            "Always produce well-formed, valid SVG."
        )
        self._system_prompt_text = Gtk.TextView()
        self._system_prompt_text.set_wrap_mode(Gtk.WrapMode.WORD)
        self._system_prompt_text.set_accepts_tab(False)
        self._system_prompt_text.get_buffer().set_text(DEFAULT_SYSTEM)
        sp_scroll = Gtk.ScrolledWindow()
        sp_scroll.set_min_content_height(90)
        sp_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sp_scroll.add(self._system_prompt_text)
        vbox.pack_start(sp_scroll, True, True, 0)

        self._use_custom_system_check = Gtk.CheckButton(
            label="Use the custom system prompt above (unchecked = default)"
        )
        vbox.pack_start(self._use_custom_system_check, False, False, 0)

        vbox.pack_start(Gtk.Separator(), False, False, 6)

        # ── Prompt templates ─────────────────────────────────
        vbox.pack_start(self._section("Prompt Templates"), False, False, 0)
        hint2 = Gtk.Label(
            label="Save frequently used prompts and settings as named templates.",
            xalign=0
        )
        hint2.get_style_context().add_class("dim-label")
        vbox.pack_start(hint2, False, False, 0)

        # Load row
        self._template_combo = Gtk.ComboBoxText()
        self._template_combo.append('__none__', '— Select template —')
        self._template_combo.set_active(0)
        self._load_templates_into_combo()
        load_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        load_box.pack_start(self._template_combo, True, True, 0)
        load_btn = Gtk.Button(label="Load")
        load_btn.connect("clicked", self._on_load_template)
        load_box.pack_start(load_btn, False, False, 0)
        vbox.pack_start(_make_row("Template:", load_box), False, False, 0)

        # Save row
        self._template_name_entry = Gtk.Entry()
        self._template_name_entry.set_placeholder_text("Name for new template…")
        save_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        save_box.pack_start(self._template_name_entry, True, True, 0)
        save_btn = Gtk.Button(label="Save as Template")
        save_btn.connect("clicked", self._on_save_template)
        save_box.pack_start(save_btn, False, False, 0)
        vbox.pack_start(save_box, False, False, 0)

        del_btn = Gtk.Button(label="Delete Selected Template")
        del_btn.connect("clicked", self._on_delete_template)
        vbox.pack_start(del_btn, False, False, 4)

        self._notebook.append_page(sw, Gtk.Label(label="Advanced"))

    # ── Template helpers ─────────────────────────────────────

    def _load_templates_data(self):
        if self.templates_path and os.path.exists(self.templates_path):
            try:
                with open(self.templates_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def _save_templates_data(self, templates):
        if not self.templates_path:
            return
        try:
            with open(self.templates_path, 'w', encoding='utf-8') as f:
                json.dump(templates, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self._alert(f"Could not save templates: {e}")

    def _load_templates_into_combo(self):
        for t in self._load_templates_data():
            name = t.get('name', '')
            if name:
                self._template_combo.append(name, name)

    def _on_load_template(self, _btn):
        tid = self._template_combo.get_active_id()
        if not tid or tid == '__none__':
            return
        for t in self._load_templates_data():
            if t.get('name') == tid:
                self._prompt_text.get_buffer().set_text(t.get('prompt', ''))
                provider = t.get('provider', 'openai')
                self._provider_combo.set_active_id(provider)
                if t.get('model'):
                    self._model_combo.set_active_id(t['model'])
                self._preset_combo.set_active_id(t.get('preset', 'none') or 'none')
                self._temperature_spin.set_value(t.get('temperature', 0.7))
                self._style_combo.set_active_id(t.get('style_hint', 'none') or 'none')
                self._color_combo.set_active_id(t.get('color_scheme', 'any') or 'any')
                self._complexity_combo.set_active_id(t.get('complexity', 'medium') or 'medium')
                if t.get('system_prompt'):
                    self._system_prompt_text.get_buffer().set_text(t['system_prompt'])
                self._use_custom_system_check.set_active(
                    t.get('use_custom_system_prompt', False)
                )
                self._notebook.set_current_page(0)
                break

    def _on_save_template(self, _btn):
        name = self._template_name_entry.get_text().strip()
        if not name:
            self._alert("Enter a template name first.")
            return
        buf = self._prompt_text.get_buffer()
        prompt = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        sp_buf = self._system_prompt_text.get_buffer()
        system_prompt = sp_buf.get_text(sp_buf.get_start_iter(), sp_buf.get_end_iter(), True)
        template = {
            'name': name,
            'prompt': prompt,
            'provider': self._provider_combo.get_active_id() or 'openai',
            'model': self._model_combo.get_active_id() or '',
            'preset': self._preset_combo.get_active_id() or 'none',
            'temperature': self._temperature_spin.get_value(),
            'style_hint': self._style_combo.get_active_id() or 'none',
            'color_scheme': self._color_combo.get_active_id() or 'any',
            'complexity': self._complexity_combo.get_active_id() or 'medium',
            'system_prompt': system_prompt,
            'use_custom_system_prompt': self._use_custom_system_check.get_active(),
        }
        templates = self._load_templates_data()
        for i, t in enumerate(templates):
            if t.get('name') == name:
                templates[i] = template
                break
        else:
            templates.append(template)
        self._save_templates_data(templates)
        # Refresh combo
        self._template_combo.remove_all()
        self._template_combo.append('__none__', '— Select template —')
        self._load_templates_into_combo()
        self._template_combo.set_active_id(name)
        self._alert(f"Template '{name}' saved.")

    def _on_delete_template(self, _btn):
        tid = self._template_combo.get_active_id()
        if not tid or tid == '__none__':
            self._alert("Select a template to delete.")
            return
        dlg = Gtk.MessageDialog(
            transient_for=self,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
        )
        dlg.set_markup(GLib.markup_escape_text(f"Delete template '{tid}'?"))
        response = dlg.run()
        dlg.destroy()
        if response != Gtk.ResponseType.YES:
            return
        templates = [t for t in self._load_templates_data() if t.get('name') != tid]
        self._save_templates_data(templates)
        self._template_combo.remove_all()
        self._template_combo.append('__none__', '— Select template —')
        self._load_templates_into_combo()
        self._template_combo.set_active(0)

    # ── Extract options ──────────────────────────────────────

    def get_options(self) -> GenerationOptions:
        """Read all widget values and return a GenerationOptions instance."""
        def _tv_text(tv):
            b = tv.get_buffer()
            return b.get_text(b.get_start_iter(), b.get_end_iter(), True)

        buf = self._prompt_text.get_buffer()
        prompt = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        save_dir = self._save_dir_entry.get_text().strip()

        _selected_provider = self._provider_combo.get_active_id() or 'openai'
        # For custom_openai allow the user to type an arbitrary model name
        _selected_model = self._model_combo.get_active_id() or 'gpt-4o'
        if _selected_provider == 'custom_openai':
            _custom_name = self._custom_model_entry.get_text().strip()
            if _custom_name:
                _selected_model = _custom_name

        return GenerationOptions(
            provider=_selected_provider,
            api_key=self._api_key_entry.get_text().strip(),
            use_env_key=self._use_env_key_check.get_active(),
            use_config_key=self._use_config_key_check.get_active(),
            save_api_key=self._save_api_key_check.get_active(),
            api_endpoint=self._endpoint_entry.get_text().strip(),
            prompt=prompt,
            prompt_preset=self._preset_combo.get_active_id() or 'none',
            use_selection_context=self._use_selection_check.get_active(),
            model=_selected_model,
            temperature=self._temperature_spin.get_value(),
            max_tokens=int(self._max_tokens_spin.get_value()),
            timeout=int(self._timeout_spin.get_value()),
            retry_count=int(self._retry_spin.get_value()),
            seed=int(self._seed_spin.get_value()),
            size=self._size_combo.get_active_id() or 'medium',
            custom_width=int(self._custom_width_spin.get_value()),
            custom_height=int(self._custom_height_spin.get_value()),
            aspect_ratio=self._ratio_combo.get_active_id() or 'square',
            style_hint=self._style_combo.get_active_id() or 'none',
            complexity=self._complexity_combo.get_active_id() or 'medium',
            color_scheme=self._color_combo.get_active_id() or 'any',
            stroke_style=self._stroke_combo.get_active_id() or 'any',
            include_gradients=self._gradients_check.get_active(),
            add_group=self._add_group_check.get_active(),
            group_name=self._group_name_entry.get_text().strip(),
            position=self._position_combo.get_active_id() or 'center',
            include_animations=self._animations_check.get_active(),
            add_accessibility=self._accessibility_check.get_active(),
            optimize_paths=self._optimize_check.get_active(),
            variations=int(self._variations_spin.get_value()),
            save_to_history=self._save_history_check.get_active(),
            save_to_disk=self._save_to_disk_check.get_active(),
            save_directory=save_dir,
            filename_prefix=self._filename_prefix_entry.get_text().strip() or 'svg_image',
            embed_in_svg=self._embed_check.get_active(),
            include_selection_svg=self._include_svg_check.get_active(),
            negative_prompt=self._negative_prompt_entry.get_text().strip(),
            system_prompt=_tv_text(self._system_prompt_text),
            use_custom_system_prompt=self._use_custom_system_check.get_active(),
            target_layer=self._layer_combo.get_active_id() or "",
            auto_fit_page=self._auto_fit_check.get_active(),
        )

    def _save_defaults_to_config(self, opts: 'GenerationOptions'):
        """Persist provider and model as defaults so next run pre-fills them."""
        try:
            self.config['default_provider'] = opts.provider
            self.config['default_model'] = opts.model
            save_dir = opts.save_directory
            if save_dir:
                self.config['default_save_directory'] = save_dir
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2)
        except Exception:
            pass  # non-critical, ignore silently


# ==================== PROGRESS DIALOG ====================

# ── SVG Preview Window ────────────────────────────────────────────────────────

class SVGPreviewWindow(Gtk.Window):
    """Standalone window showing an SVG preview (via librsvg) + raw source tab."""

    def __init__(self, svg_code, saved_path=None):
        super().__init__(title="SVG Preview")
        self.set_default_size(580, 520)
        self.set_border_width(8)
        self._svg_code = svg_code
        self._saved_path = saved_path
        self._handle = None  # Rsvg.Handle if available
        self._build_ui()
        self.show_all()

    def _build_ui(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add(vbox)

        notebook = Gtk.Notebook()
        vbox.pack_start(notebook, True, True, 0)

        # ── Preview tab ──────────────────────────────────────
        preview_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        if _HAS_RSVG and _Rsvg is not None:
            try:
                import gi
                from gi.repository import GLib as _GLib
                data = self._svg_code.encode('utf-8')
                self._handle = _Rsvg.Handle.new_from_data(data)
            except Exception:
                self._handle = None

        if self._handle is not None:
            drawing_area = Gtk.DrawingArea()
            drawing_area.set_size_request(400, 400)
            drawing_area.connect('draw', self._on_draw)
            sw = Gtk.ScrolledWindow()
            sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            sw.add(drawing_area)
            preview_vbox.pack_start(sw, True, True, 0)
        else:
            lbl = Gtk.Label(
                label="Preview not available.\n\nInstall librsvg (gi.repository.Rsvg) for live rendering.",
                xalign=0.5
            )
            lbl.set_line_wrap(True)
            preview_vbox.pack_start(lbl, True, True, 0)
        notebook.append_page(preview_vbox, Gtk.Label(label='Preview'))

        # ── Source tab ───────────────────────────────────────
        src_buf = Gtk.TextBuffer()
        src_buf.set_text(self._svg_code)
        src_view = Gtk.TextView(buffer=src_buf)
        src_view.set_editable(False)
        src_view.set_monospace(True)
        src_view.set_wrap_mode(Gtk.WrapMode.NONE)
        src_sw = Gtk.ScrolledWindow()
        src_sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        src_sw.add(src_view)
        notebook.append_page(src_sw, Gtk.Label(label='SVG Source'))

        # ── Bottom bar ───────────────────────────────────────
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        vbox.pack_start(btn_box, False, False, 0)

        if self._saved_path:
            lbl_path = Gtk.Label(label=self._saved_path, xalign=0)
            lbl_path.get_style_context().add_class('dim-label')
            lbl_path.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
            btn_box.pack_start(lbl_path, True, True, 0)

            open_btn = Gtk.Button(label='Open Folder')
            open_btn.connect('clicked', self._on_open_folder)
            btn_box.pack_end(open_btn, False, False, 0)

        close_btn = Gtk.Button(label='Close')
        close_btn.connect('clicked', lambda _: self.destroy())
        btn_box.pack_end(close_btn, False, False, 0)

    def _on_draw(self, widget, cr):
        if self._handle is None:
            return
        alloc = widget.get_allocation()
        w, h = alloc.width, alloc.height
        try:
            # librsvg >= 2.52 API
            ok, iw, ih = self._handle.get_intrinsic_size_in_pixels()
            if not ok or iw <= 0 or ih <= 0:
                raise ValueError('no intrinsic size')
        except Exception:
            try:
                dim = self._handle.get_dimensions()
                iw, ih = dim.width, dim.height
            except Exception:
                return
        if iw <= 0 or ih <= 0:
            return
        scale = min(w / iw, h / ih, 1.0)
        ox = (w - iw * scale) / 2
        oy = (h - ih * scale) / 2
        cr.translate(ox, oy)
        cr.scale(scale, scale)
        try:
            from gi.repository import Rsvg as _R
            vp = _R.Rectangle()
            vp.x, vp.y, vp.width, vp.height = 0, 0, iw, ih
            self._handle.render_document(cr, vp)
        except Exception:
            try:
                self._handle.render_cairo(cr)
            except Exception:
                pass

    def _on_open_folder(self, _btn):
        folder = os.path.dirname(self._saved_path) if self._saved_path else None
        if not folder or not os.path.isdir(folder):
            return
        try:
            if sys.platform == 'win32':
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', folder])
            else:
                subprocess.Popen(['xdg-open', folder])
        except Exception:
            pass


class GenerationProgressDialog(Gtk.Window):
    """
    Non-modal progress window shown while API calls run in a background thread.

    Usage::

        prog = GenerationProgressDialog(total_variations)
        prog.start(lambda i: generator.call_api_with_retry(prompt, key, i))
        prog.show()
        Gtk.main()  # blocks until done or cancelled
        prog.destroy()
        if not prog._done_ok or prog.cancelled:
            return
        for svg_str, error_str in prog.results:
            ...
    """

    def __init__(self, total_variations):
        super().__init__(title="Generating SVG\u2026")
        self.set_modal(True)
        self.set_keep_above(True)
        self.total = total_variations
        self.cancelled = False
        self._done = False
        self._done_ok = False
        self.results = []        # list of (svg_str | None, error_str | None)
        self._pulse_id = None
        self._gen_fn = None
        self.set_default_size(480, 230)
        self.set_border_width(12)
        self._build_ui()
        self.connect("delete-event", self._on_delete)
        self.show_all()

    def _on_delete(self, widget, event):
        self._on_cancel_clicked(None)
        return False

    def _on_cancel_clicked(self, btn):
        self.cancelled = True
        self._done = True
        if self._pulse_id is not None:
            GLib.source_remove(self._pulse_id)
            self._pulse_id = None
        Gtk.main_quit()

    # ── UI ───────────────────────────────────────────────────

    def _build_ui(self):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add(content)

        self._status_lbl = Gtk.Label(label="Preparing\u2026", xalign=0)
        content.pack_start(self._status_lbl, False, False, 0)

        self._bar = Gtk.ProgressBar()
        self._bar.set_pulse_step(0.08)
        content.pack_start(self._bar, False, False, 0)

        self._log_buf = Gtk.TextBuffer()
        log_view = Gtk.TextView(buffer=self._log_buf)
        log_view.set_editable(False)
        log_view.set_wrap_mode(Gtk.WrapMode.WORD)
        log_sw = Gtk.ScrolledWindow()
        log_sw.set_min_content_height(90)
        log_sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        log_sw.add(log_view)
        content.pack_start(log_sw, True, True, 0)

        self._cancel_btn = Gtk.Button(label="Cancel")
        self._cancel_btn.connect("clicked", self._on_cancel_clicked)
        self._copy_btn = Gtk.Button(label="Copy SVG to Clipboard")
        self._copy_btn.connect("clicked", self._on_copy_svg)
        self._copy_btn.set_no_show_all(True)  # hidden until done
        self._preview_btn = Gtk.Button(label="Preview SVG")
        self._preview_btn.connect("clicked", self._on_preview_svg)
        self._preview_btn.set_no_show_all(True)  # hidden until done
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        btn_box.pack_end(self._cancel_btn, False, False, 0)
        btn_box.pack_end(self._copy_btn, False, False, 0)
        btn_box.pack_end(self._preview_btn, False, False, 0)
        content.pack_start(btn_box, False, False, 0)

    # ── Public API ───────────────────────────────────────────

    def start(self, gen_fn):
        """Begin generation. gen_fn(variation_idx: int) -> svg_str."""
        self._gen_fn = gen_fn
        self._pulse_id = GLib.timeout_add(80, self._on_pulse)
        threading.Thread(target=self._worker, daemon=True).start()

    # ── Internal ─────────────────────────────────────────────

    def _on_pulse(self):
        self._bar.pulse()
        return True

    def _log(self, text):
        GLib.idle_add(self._append_log_idle, text)

    def _append_log_idle(self, text):
        end = self._log_buf.get_end_iter()
        self._log_buf.insert(end, text + "\n")
        return False

    def _set_status(self, text):
        GLib.idle_add(lambda: self._status_lbl.set_text(text) or False)

    def _worker(self):
        for i in range(self.total):
            if self.cancelled:
                self._log("Cancelled.")
                break
            self._set_status(
                f"Calling API \u2014 variation {i + 1} of {self.total}\u2026"
            )
            self._log(f"\u25b6 Variation {i + 1}/{self.total}\u2026")
            try:
                svg = self._gen_fn(i)
                self.results.append((svg, None))
                self._log(f"  \u2713 {len(svg)} chars received")
            except Exception as exc:
                self.results.append((None, str(exc)))
                self._log(f"  \u2717 {exc}")
        GLib.idle_add(self._finish_idle)

    def _finish_idle(self):
        if self._pulse_id is not None:
            GLib.source_remove(self._pulse_id)
            self._pulse_id = None
        self._bar.set_fraction(1.0)
        if not self.cancelled and not self._done:
            self._done = True
            self._done_ok = True
            self._set_status("Done.")
            # Show copy / preview buttons if any SVG was generated
            successful = [svg for svg, err in self.results if svg and not err]
            if successful:
                GLib.idle_add(lambda: (self._copy_btn.show(), False)[1])
                if _HAS_RSVG:
                    GLib.idle_add(lambda: (self._preview_btn.show(), False)[1])
            GLib.idle_add(lambda: self._cancel_btn.set_label("Close") or False)
            GLib.idle_add(lambda: Gtk.main_quit() or False)
        return False

    def _on_preview_svg(self, _btn):
        """Open SVGPreviewWindow for the last successfully generated SVG."""
        successful = [svg for svg, err in self.results if svg and not err]
        if not successful:
            return
        SVGPreviewWindow(successful[-1])

    def _on_copy_svg(self, _btn):
        """Copy the last successfully generated SVG text to the system clipboard."""
        successful = [svg for svg, err in self.results if svg and not err]
        if not successful:
            return
        svg_text = successful[-1]
        try:
            from gi.repository import Gdk
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            clipboard.set_text(svg_text, -1)
            clipboard.store()
            self._log("SVG copied to clipboard \u2713")
        except Exception as exc:
            self._log(f"Could not copy to clipboard: {exc}")


# ==================== RESULT DIALOG ====================

class GenerationResultDialog(Gtk.Window):
    """
    Modal summary dialog shown after all SVG results have been processed.

    Pass a list of result dicts::

        {
            'variation': int,          # 1-based
            'status':    'ok'|'error', # outcome
            'error':     str|None,     # error message
            'saved_path': str|None,    # path on disk (if saved)
            'svg_size':  int|None,     # byte length of SVG
        }

    Usage::

        dlg = GenerationResultDialog(result_entries)
        dlg.present()
        Gtk.main()
        dlg.destroy()
    """

    def __init__(self, result_entries):
        super().__init__(title="Generation Results")
        self.set_modal(True)
        self.set_keep_above(True)
        self.set_default_size(520, 340)
        self.set_border_width(12)
        self._entries = result_entries
        self._saved_folder = None
        for r in result_entries:
            if r.get('saved_path'):
                self._saved_folder = os.path.dirname(r['saved_path'])
                break
        self._build_ui()
        self.connect("delete-event", self._on_close)
        self.show_all()

    def _on_close(self, *_):
        Gtk.main_quit()
        return False

    def _build_ui(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(vbox)

        ok_count = sum(1 for r in self._entries if r['status'] == 'ok')
        total = len(self._entries)
        err_count = total - ok_count

        # ── Summary banner ────────────────────────────────────
        summary_lbl = Gtk.Label(xalign=0)
        if err_count == 0:
            summary_lbl.set_markup(
                f'<b><span foreground="#2e7d32">\u2714 {ok_count} of {total} '
                f'variation{"s" if total != 1 else ""} generated successfully.</span></b>'
            )
        elif ok_count == 0:
            summary_lbl.set_markup(
                f'<b><span foreground="#c62828">\u2718 All {total} '
                f'variation{"s" if total != 1 else ""} failed.</span></b>'
            )
        else:
            summary_lbl.set_markup(
                f'<b>{ok_count} succeeded, '
                f'<span foreground="#c62828">{err_count} failed</span> '
                f'out of {total}.</b>'
            )
        vbox.pack_start(summary_lbl, False, False, 0)
        vbox.pack_start(Gtk.Separator(), False, False, 0)

        # ── Per-variation rows ────────────────────────────────
        grid = Gtk.Grid()
        grid.set_column_spacing(10)
        grid.set_row_spacing(6)

        headers = ["#", "Status", "SVG size", "Saved path / Error"]
        for col, h in enumerate(headers):
            lbl = Gtk.Label(xalign=0)
            lbl.set_markup(f"<b>{h}</b>")
            grid.attach(lbl, col, 0, 1, 1)

        for row_idx, r in enumerate(self._entries, start=1):
            var_lbl = Gtk.Label(label=str(r['variation']), xalign=0)
            grid.attach(var_lbl, 0, row_idx, 1, 1)

            if r['status'] == 'ok':
                status_lbl = Gtk.Label(xalign=0)
                status_lbl.set_markup('<span foreground="#2e7d32">\u2714 OK</span>')
            else:
                status_lbl = Gtk.Label(xalign=0)
                status_lbl.set_markup('<span foreground="#c62828">\u2718 Error</span>')
            grid.attach(status_lbl, 1, row_idx, 1, 1)

            size_text = f"{r['svg_size']:,} B" if r.get('svg_size') else "—"
            size_lbl = Gtk.Label(label=size_text, xalign=0)
            grid.attach(size_lbl, 2, row_idx, 1, 1)

            if r['status'] == 'ok' and r.get('saved_path'):
                detail_lbl = Gtk.Label(label=os.path.basename(r['saved_path']), xalign=0)
                detail_lbl.set_tooltip_text(r['saved_path'])
                detail_lbl.set_selectable(True)
            elif r['status'] == 'ok':
                detail_lbl = Gtk.Label(label="Embedded in document", xalign=0)
            else:
                detail_lbl = Gtk.Label(label=str(r.get('error', 'Unknown error')), xalign=0)
                detail_lbl.set_line_wrap(True)
                detail_lbl.set_max_width_chars(50)
                detail_lbl.set_selectable(True)
                detail_lbl.get_style_context().add_class("dim-label")
            grid.attach(detail_lbl, 3, row_idx, 1, 1)

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.add(grid)
        vbox.pack_start(sw, True, True, 0)

        # ── Button bar ────────────────────────────────────────
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        vbox.pack_start(btn_box, False, False, 0)

        if self._saved_folder and os.path.isdir(self._saved_folder):
            open_btn = Gtk.Button(label="Open Save Folder")
            open_btn.connect("clicked", self._on_open_folder)
            btn_box.pack_start(open_btn, False, False, 0)

        close_btn = Gtk.Button(label="Close")
        close_btn.connect("clicked", self._on_close)
        close_btn.get_style_context().add_class("suggested-action")
        btn_box.pack_end(close_btn, False, False, 0)

    def _on_open_folder(self, _btn):
        if not self._saved_folder or not os.path.isdir(self._saved_folder):
            return
        try:
            if sys.platform == 'win32':
                os.startfile(self._saved_folder)  # type: ignore[attr-defined]
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', self._saved_folder])
            else:
                subprocess.Popen(['xdg-open', self._saved_folder])
        except Exception:
            pass

