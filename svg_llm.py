#!/usr/bin/env python3
"""
Inkscape extension to generate SVG objects using multiple AI providers.
Supports OpenAI, Anthropic, Google Gemini, Azure OpenAI, Ollama, and
any custom OpenAI-compatible endpoint.
"""

import inkex
from inkex import Group
import re
import ssl
import urllib.request
import json
import xml.etree.ElementTree as ET
import os
import time
from datetime import datetime

try:
    from svg_llm_prompts import PromptLoader as _PromptLoader
except Exception:
    _PromptLoader = None

# ── Provider modules ──────────────────────────────────────────────────────────
try:
    import svg_llm_openai   as _prov_openai
    import svg_llm_anthropic as _prov_anthropic
    import svg_llm_google    as _prov_google
    import svg_llm_ollama    as _prov_ollama
    import svg_llm_azure     as _prov_azure
    import svg_llm_custom    as _prov_custom
    _PROVIDERS_LOADED = True
except Exception as _prov_err:
    _PROVIDERS_LOADED = False
    _prov_openai = _prov_anthropic = _prov_google = None
    _prov_ollama = _prov_azure = _prov_custom = None


def _build_ssl_context():
    """
    Return an SSL context that performs full certificate verification.
    Strategy (in order):
      1. certifi â€” ships its own CA bundle, works everywhere
      2. Windows cert store (ssl.create_default_context loads it automatically on Windows)
      3. Default context with no explicit cafile (works on most Linux/macOS)
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    return ssl.create_default_context()


_SSL_CONTEXT = _build_ssl_context()


class SVGLLMGenerator(inkex.EffectExtension):
    """Extension to generate SVG using various LLM providers."""
    
    CONFIG_FILENAME = 'config.json'
    HISTORY_FILENAME = 'svg_llm_history.json'
    TEMPLATES_FILENAME = 'svg_llm_templates.json'
    MAX_HISTORY = 50
    
    PROVIDERS = {
        'openai': {
            'name': 'OpenAI',
            'env_key': 'OPENAI_API_KEY',
            'config_key': 'openai_api_key',
            'models': ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-3.5-turbo',
                       'o1', 'o1-mini', 'o3-mini'],
        },
        'anthropic': {
            'name': 'Anthropic Claude',
            'env_key': 'ANTHROPIC_API_KEY',
            'config_key': 'anthropic_api_key',
            'models': ['claude-opus-4-5', 'claude-sonnet-4-5',
                       'claude-3-5-sonnet-20241022', 'claude-3-haiku-20240307'],
        },
        'google': {
            'name': 'Google Gemini',
            'env_key': 'GOOGLE_API_KEY',
            'config_key': 'google_api_key',
            'models': ['gemini-2.0-flash', 'gemini-1.5-pro', 'gemini-1.5-flash'],
        },
        'azure': {
            'name': 'Azure OpenAI',
            'env_key': 'AZURE_OPENAI_API_KEY',
            'config_key': 'azure_openai_api_key',
            'models': ['gpt-4o', 'gpt-4-turbo', 'gpt-35-turbo'],
        },
        'ollama': {
            'name': 'Ollama (Local)',
            'env_key': '',
            'config_key': '',
            'models': ['llama3.2', 'llama3.1', 'qwen2.5-coder', 'codellama', 'mistral'],
        },
        'custom_openai': {
            'name': 'Custom (OpenAI-compatible)',
            'env_key': 'CUSTOM_OPENAI_API_KEY',
            'config_key': 'custom_openai_api_key',
            'models': ['custom-model'],
        },
    }


    # Maximum SVG size (bytes) we will attempt to parse and insert
    MAX_SVG_BYTES = 2 * 1024 * 1024  # 2 MB

    def __init__(self):
        super().__init__()
        # Use abspath so prompt files are always found regardless of cwd
        _ext_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_path = os.path.join(_ext_dir, self.CONFIG_FILENAME)
        self.history_path = os.path.join(_ext_dir, self.HISTORY_FILENAME)
        self.templates_path = os.path.join(_ext_dir, self.TEMPLATES_FILENAME)
        self.prompt_loader = _PromptLoader(_ext_dir) if _PromptLoader else None
    
    def effect(self):
        """Main effect function."""
        # â”€â”€ GTK is required â€” no INX fallback â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        try:
            import gi
            gi.require_version('Gtk', '3.0')
            from gi.repository import Gtk
            from svg_llm_dialog import SVGLLMDialog, GenerationProgressDialog, GenerationResultDialog
        except Exception as _gtk_err:
            inkex.errormsg(
                f"AI SVG Generator requires GTK 3 which could not be loaded:\n"
                f"{_gtk_err}\n\n"
                "Make sure you are running Inkscape with its bundled Python "
                "(not a standalone Python environment)."
            )
            return

        self.config = self.load_config()

        layers = self._get_layers()
        dialog = SVGLLMDialog(
            config=self.config,
            config_path=self.config_path,
            history_path=self.history_path,
            templates_path=self.templates_path,
            has_selection=bool(self.svg.selection),
            layers=layers,
        )
        dialog.present()
        Gtk.main()
        if not dialog._accepted:
            dialog.destroy()
            return
        self.gen_options = dialog.get_options()
        dialog._save_defaults_to_config(self.gen_options)
        dialog.destroy()

        # â”€â”€ Common validation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        api_key = self.get_api_key()

        if self.gen_options.save_api_key and api_key:
            self.save_api_key(api_key)

        self._validate_model_for_provider()

        if not self.gen_options.prompt or len(self.gen_options.prompt.strip()) < 3:
            inkex.errormsg("Please provide a description of what you want to generate.")
            return

        if not self.gen_options.embed_in_svg and not self.gen_options.save_to_disk:
            inkex.errormsg(
                "'Link (not embed)' requires 'Save to disk' to be enabled. "
                "Switching to inline embed."
            )
            self.gen_options.embed_in_svg = True

        width, height = self.get_size()

        selection_context = ""
        if self.gen_options.use_selection_context and self.svg.selection:
            selection_context = self.get_selection_context()

        enhanced_prompt = self.build_prompt(width, height, selection_context)
        variations = min(max(1, self.gen_options.variations), 4)

        # â”€â”€ Run API calls â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        def gen_fn(variation_idx):
            return self.call_api_with_retry(enhanced_prompt, api_key, variation_idx)

        prog = GenerationProgressDialog(variations)
        prog.start(gen_fn)
        prog.present()
        Gtk.main()
        prog.destroy()
        if not prog._done_ok or prog.cancelled:
            return
        svg_results = prog.results

        # â”€â”€ Process results â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        inkex.utils.debug("Parsing and inserting generated SVG(s)â€¦")
        result_entries = []
        for i, (svg_code, error) in enumerate(svg_results):
            entry = {
                'variation': i + 1,
                'status': 'error',
                'error': None,
                'saved_path': None,
                'svg_size': None,
            }
            if error:
                entry['error'] = error
                result_entries.append(entry)
                continue
            if not svg_code:
                entry['error'] = 'No SVG code returned by the model.'
                result_entries.append(entry)
                continue

            svg_code = self.validate_and_fix_svg(svg_code, width, height)
            entry['svg_size'] = len(svg_code.encode('utf-8'))

            saved_path = None
            if self.gen_options.save_to_disk:
                saved_path = self.save_svg_to_disk(svg_code)
            entry['saved_path'] = saved_path

            offset_x = i * (width + 20) if variations > 1 else 0
            if not self.gen_options.embed_in_svg and saved_path:
                self._insert_image_link(saved_path, width, height, offset_x, variation_num=i + 1)
            else:
                self.add_svg_to_document(svg_code, width, height, offset_x, variation_num=i + 1)

            entry['status'] = 'ok'
            result_entries.append(entry)

        # Show result summary dialog
        result_dlg = GenerationResultDialog(result_entries)
        result_dlg.present()
        Gtk.main()
        result_dlg.destroy()

        # â”€â”€ Canvas / page handling â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if variations > 1:
            total_width = variations * (width + 20)
            if getattr(self.gen_options, 'auto_fit_page', False):
                self._auto_fit_page(width, height, variations)
            elif total_width > self.svg.viewport_width * 1.5:
                inkex.errormsg(
                    f"Note: {variations} variations at {width}px each "
                    f"({total_width}px total) extend beyond the canvas. "
                    "Use View \u203a Zoom \u203a Fit Page to see all."
                )

        # â”€â”€ History â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if self.gen_options.save_to_history:
            self.save_to_history(self.gen_options.prompt, width, height)
    
    # ==================== Configuration Management ====================
    
    def get_save_directory(self):
        """Get save directory from options or config."""
        if self.gen_options.save_directory and self.gen_options.save_directory.strip():
            return self.gen_options.save_directory
        return self.get_config_value('default_save_directory', os.path.expanduser('~/Pictures/AI_Images'))
    




    
    def get_api_key(self):
            """
            Get API key with priority:
            1. Direct input (if provided and not placeholder)
            2. Environment variable (if use_env_key is True)
            3. Config file (if use_config_key is True)
            """
            provider = self.gen_options.provider


            # Skip API key for local provider
            if provider == 'local':
                return ''

            # 1. Check direct input first
            if self.gen_options.api_key and self.gen_options.api_key not in ['', 'sk-...', 'sk-your-key-here']:
                # Save to config if requested
                if self.gen_options.save_api_key:
                    config_key = self.PROVIDERS.get(provider, {}).get('config_key', '')
                    if config_key:
                        self.set_config_value(config_key, self.gen_options.api_key)
                return self.gen_options.api_key
            
            # 2. Check environment variable
            if self.gen_options.use_env_key:
                env_key = self.PROVIDERS.get(provider, {}).get('env_key', '')
                if env_key:
                    env_value = os.environ.get(env_key, '')
                    if env_value:
                        return env_value
            
            # 3. Check config file
            if self.gen_options.use_config_key:
                config_key = self.PROVIDERS.get(provider, {}).get('config_key', '')
                if config_key:
                    config_value = self.config.get(config_key, '')
                    if config_value and config_value not in ['sk-your-key-here', 'r8_your-token-here']:
                        return config_value
            
            return ''
    



    def save_svg_to_disk(self, image_data):
        """Save image data to disk."""
        if not self.gen_options.save_to_disk:
            return None
        save_dir = self.get_save_directory()
        
        try:
            os.makedirs(save_dir, exist_ok=True)
        except Exception:
            inkex.errormsg(f"Could not create directory: {save_dir}")
            return None
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        seed_str = f"_seed{self.gen_options.seed}" if self.gen_options.seed != -1 else ""
        filename = f"{self.gen_options.filename_prefix}_{timestamp}{seed_str}.svg"
        filepath = os.path.join(save_dir, filename)
        
        try:
            with open(filepath, 'w') as f:
                f.write(image_data)
            return filepath
        except Exception as e:
            inkex.errormsg(f"Error saving image: {str(e)}")
            return None




    def load_config(self):
        """Load saved configuration."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}
    
    def save_config(self, config):
        """Save configuration."""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            inkex.errormsg(f"Warning: Could not save config: {e}")
    
    def save_api_key(self, api_key):
        """Save API key for the current provider using flat key schema."""
        config = self.load_config()
        config_key = self.PROVIDERS.get(self.gen_options.provider, {}).get('config_key', '')
        if config_key:
            config[config_key] = api_key
        self.save_config(config)
    
    def get_config_value(self, key, default=None):
        """Get a value from the loaded config."""
        return self.config.get(key, default)

    def set_config_value(self, key, value):
        """Set a value in the config and persist it."""
        self.config[key] = value
        self.save_config(self.config)

    def _get_layers(self):
        """Return list of (id, label) tuples for all Inkscape layers in the document."""
        layers = []
        try:
            for layer in self.svg.xpath(
                '//svg:g[@inkscape:groupmode="layer"]',
                namespaces=inkex.NSS
            ):
                layer_id = layer.get('id', '')
                layer_label = layer.get(
                    '{http://www.inkscape.org/namespaces/inkscape}label',
                    layer_id
                )
                if layer_id:
                    layers.append((layer_id, layer_label))
        except Exception:
            pass
        return layers

    def get_system_prompt(self):
        """Return the system prompt to send to the model."""
        if getattr(self.gen_options, 'use_custom_system_prompt', False) and \
                getattr(self.gen_options, 'system_prompt', ''):
            return self.gen_options.system_prompt
        if self.prompt_loader:
            return self.prompt_loader.get_system_prompt()
        return (
            "You are an expert SVG code generator. You only respond with valid, clean SVG code "
            "without any explanation or markdown formatting. Never include ```svg or ``` markers. "
            "Always produce well-formed, valid SVG."
        )

    def _auto_fit_page(self, width, height, variations):
        """Expand the SVG page so all generated variations are visible."""
        try:
            doc_width = self.svg.viewport_width
            doc_height = self.svg.viewport_height
            total_w = variations * (width + 20) - 20
            base_x = (doc_width - width) / 2  # leftmost variation start
            right_edge = base_x + total_w + 20
            bottom_edge = (doc_height - height) / 2 + height + 20
            new_w = max(doc_width, right_edge)
            new_h = max(doc_height, bottom_edge)
            if new_w > doc_width or new_h > doc_height:
                self.svg.set('width', f'{new_w}px')
                self.svg.set('height', f'{new_h}px')
                self.svg.set('viewBox', f'0 0 {new_w} {new_h}')
                inkex.utils.debug(
                    f"Page expanded to {new_w}Ã—{new_h}px to fit {variations} variation(s)."
                )
        except Exception as exc:
            inkex.utils.debug(f"auto_fit_page: {exc}")

    def _validate_model_for_provider(self):
        """Warn if the selected model is not known for the selected provider."""
        provider = self.gen_options.provider
        model = self.gen_options.model
        # Azure and custom_openai use user-defined names — always valid
        if provider in ('azure', 'custom_openai'):
            return
        provider_models = self.PROVIDERS.get(provider, {}).get('models', [])
        if provider_models and model not in provider_models:
            inkex.errormsg(
                f"Warning: '{model}' is not a known {provider} model. "
                f"Expected one of: {', '.join(provider_models)}. Proceeding anyway."
            )

    def _get_target_layer(self):
        """Return the layer element to place generated content on."""
        lid = getattr(self.gen_options, 'target_layer', '')
        if lid:
            matches = self.svg.xpath(
                f'//svg:g[@id="{lid}"]', namespaces=inkex.NSS
            )
            if matches:
                return matches[0]
        return self.svg.get_current_layer()

    def _insert_image_link(self, filepath, width, height, offset_x=0, variation_num=1):
        """Insert an SVG <image> element linking to an external SVG file."""
        doc_width = self.svg.viewport_width
        doc_height = self.svg.viewport_height
        pos_x = (doc_width - width) / 2 + offset_x
        pos_y = (doc_height - height) / 2
        img = inkex.Image()
        img.set('x', str(pos_x))
        img.set('y', str(pos_y))
        img.set('width', str(width))
        img.set('height', str(height))
        img.set('href', filepath)
        if self.gen_options.add_group:
            group = inkex.Group()
            group_id = self.svg.get_unique_id(f'ai-linked-{variation_num}')
            group.set('id', group_id)
            group.append(img)
            self._get_target_layer().append(group)
        else:
            self._get_target_layer().append(img)

    def load_history(self):
        """Load prompt history."""
        if os.path.exists(self.history_path):
            try:
                with open(self.history_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return []
    
    def save_to_history(self, prompt, width, height):
        """Save prompt to history."""
        history = self.load_history()
        entry = {
            'prompt': prompt,
            'timestamp': datetime.now().isoformat(),
            'width': width,
            'height': height,
            'provider': self.gen_options.provider,
            'model': self.gen_options.model,
            'style': self.gen_options.style_hint,
            'color_scheme': self.gen_options.color_scheme
        }
        history.insert(0, entry)
        history = history[:self.MAX_HISTORY]  # Keep only last N entries
        
        try:
            with open(self.history_path, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=2)
        except Exception:
            pass
    
    # ==================== Size Calculation ====================
    
    def get_size(self):
        """Get width and height based on size and aspect ratio options."""
        base_sizes = {
            'small': 200,
            'medium': 400,
            'large': 600,
            'xlarge': 800
        }
        
        aspect_ratios = {
            'square': (1, 1),
            'landscape': (4, 3),
            'portrait': (3, 4),
            'widescreen': (16, 9),
            'banner': (3, 1),
            'icon': (1, 1)
        }
        
        if self.gen_options.size == 'custom':
            return (self.gen_options.custom_width, self.gen_options.custom_height)
        
        base = base_sizes.get(self.gen_options.size, 400)
        ratio = aspect_ratios.get(self.gen_options.aspect_ratio, (1, 1))
        
        # Calculate dimensions maintaining aspect ratio
        if ratio[0] >= ratio[1]:
            width = base
            height = int(base * ratio[1] / ratio[0])
        else:
            height = base
            width = int(base * ratio[0] / ratio[1])
        
        return (width, height)
    
    # ==================== Selection Context ====================
    
    def _get_selection_as_svg(self):
        """Serialize selected elements to an SVG string for refine context."""
        if not self.svg.selection:
            return ""
        try:
            import lxml.etree as letree
            parts = []
            for elem in self.svg.selection.values():
                parts.append(letree.tostring(elem, encoding='unicode', pretty_print=True))
            if not parts:
                return ""
            width, height = self.get_size()
            return (
                f'<svg xmlns="http://www.w3.org/2000/svg" '
                f'viewBox="0 0 {width} {height}">\n'
                + "".join(parts)
                + "\n</svg>"
            )
        except Exception:
            return ""

    def get_selection_context(self):
        """Extract context from selected elements."""
        if not self.svg.selection:
            return ""
        
        context_parts = ["Selected elements for context:"]
        
        for elem in self.svg.selection.values():
            elem_info = self.describe_element(elem)
            if elem_info:
                context_parts.append(f"- {elem_info}")
        
        return "\n".join(context_parts)
    
    def describe_element(self, elem):
        """Generate a text description of an element."""
        tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
        
        info_parts = [tag]
        
        # Get fill and stroke
        style = elem.get('style', '')
        fill = elem.get('fill', '')
        stroke = elem.get('stroke', '')
        
        if 'fill:' in style:
            fill_match = re.search(r'fill:\s*([^;]+)', style)
            if fill_match:
                fill = fill_match.group(1)
        
        if fill and fill != 'none':
            info_parts.append(f"fill={fill}")
        
        if stroke and stroke != 'none':
            info_parts.append(f"stroke={stroke}")
        
        # Get dimensions for shapes
        if tag == 'rect':
            w = elem.get('width', '?')
            h = elem.get('height', '?')
            info_parts.append(f"size={w}x{h}")
        elif tag == 'circle':
            r = elem.get('r', '?')
            info_parts.append(f"radius={r}")
        elif tag == 'text':
            text_content = elem.text or ''.join(t.text or '' for t in elem.iter())
            if text_content:
                info_parts.append(f'text="{text_content[:30]}"')
        
        return " ".join(info_parts)
    
    # ==================== Prompt Building ====================
    
    def build_prompt(self, width, height, selection_context=""):
        """Build enhanced prompt with all options."""
        prompt_parts = []
        
        # Add preset context
        if self.gen_options.prompt_preset != "none":
            _preset_text = (
                self.prompt_loader.get_preset(self.gen_options.prompt_preset)
                if self.prompt_loader else None
            )
            if _preset_text:
                prompt_parts.append(_preset_text)
        
        # Main prompt
        prompt_parts.append(f"\nGenerate SVG code for: {self.gen_options.prompt}")
        prompt_parts.append(f"\nCanvas size: {width}x{height} pixels")
        
        # Selection context (text description)
        if selection_context:
            prompt_parts.append(f"\n{selection_context}")
            prompt_parts.append("Try to match the style of the selected elements.")

        # Refine mode â€” include raw SVG code of selection
        if getattr(self.gen_options, 'include_selection_svg', False):
            selected_svg = self._get_selection_as_svg()
            if selected_svg:
                prompt_parts.append(
                    "\n\n=== EXISTING SVG (modify / refine this) ==="
                )
                prompt_parts.append(selected_svg)
                prompt_parts.append("=== END EXISTING SVG ===")
                prompt_parts.append(
                    "Return the complete, updated SVG incorporating the changes "
                    "described above. Keep unchanged elements intact."
                )
        
        # Complexity
        _complexity_text = (
            self.prompt_loader.get_complexity(self.gen_options.complexity)
            if self.prompt_loader else None
        )
        if not _complexity_text:
            _complexity_fallback = {
                'simple': 'Use minimal elements, basic shapes only. Maximum 10-15 elements.',
                'medium': 'Use moderate complexity with some detail. Around 20-40 elements.',
                'complex': 'Include rich detail and many elements. Can be intricate.'
            }
            _complexity_text = _complexity_fallback.get(self.gen_options.complexity)
        if _complexity_text:
            prompt_parts.append(f"\nComplexity: {_complexity_text}")
        
        # Style hint
        if self.gen_options.style_hint != "none":
            _style_text = (
                self.prompt_loader.get_style(self.gen_options.style_hint)
                if self.prompt_loader else None
            )
            if not _style_text:
                _style_fallback = {
                    'minimal': 'Use a minimal, clean design with simple shapes and whitespace',
                    'detailed': 'Include detailed elements and visual complexity',
                    'flat': 'Use flat design principles with solid colors, no shadows or gradients',
                    'outline': 'Use only outlines/strokes, no fills (line art style)',
                    'filled': 'Use filled shapes with no or minimal strokes',
                    'geometric': 'Use geometric shapes and mathematical patterns',
                    'organic': 'Use organic, natural flowing curves and shapes',
                    'hand_drawn': 'Give it a hand-drawn, sketchy appearance',
                    'isometric': 'Use isometric 3D perspective',
                    'cartoon': 'Use a cartoon/comic style with bold outlines'
                }
                _style_text = _style_fallback.get(self.gen_options.style_hint, '')
            if _style_text:
                prompt_parts.append(f"\nStyle: {_style_text}")
        
        # Color scheme
        if self.gen_options.color_scheme != "any":
            _color_text = (
                self.prompt_loader.get_color(self.gen_options.color_scheme)
                if self.prompt_loader else None
            )
            if not _color_text:
                _color_fallback = {
                    'monochrome': 'Use only one color in different shades/tints',
                    'warm': 'Use warm colors (reds, oranges, yellows, warm browns)',
                    'cool': 'Use cool colors (blues, greens, purples, teals)',
                    'pastel': 'Use soft pastel colors with low saturation',
                    'vibrant': 'Use bright, saturated, vibrant colors',
                    'grayscale': 'Use only black, white, and shades of gray',
                    'earth': 'Use earthy, natural tones (browns, greens, tans)',
                    'neon': 'Use bright neon/fluorescent colors',
                    'complementary': 'Use complementary color pairs for contrast'
                }
                _color_text = _color_fallback.get(self.gen_options.color_scheme, '')
            if _color_text:
                prompt_parts.append(f"\nColor palette: {_color_text}")
        
        # Stroke style
        if self.gen_options.stroke_style != "any":
            _stroke_text = (
                self.prompt_loader.get_stroke(self.gen_options.stroke_style)
                if self.prompt_loader else None
            )
            if not _stroke_text:
                _stroke_fallback = {
                    'thin': 'Use thin strokes (1-2px)',
                    'medium': 'Use medium strokes (2-4px)',
                    'thick': 'Use thick, bold strokes (4-8px)',
                    'none': 'Do not use strokes, only fills',
                    'variable': 'Use variable stroke widths for emphasis'
                }
                _stroke_text = _stroke_fallback.get(self.gen_options.stroke_style, '')
            if _stroke_text:
                prompt_parts.append(f"\nStrokes: {_stroke_text}")
        
        # Gradients
        if not self.gen_options.include_gradients:
            prompt_parts.append("\nDo NOT use gradients - solid colors only.")
        
        # Animations
        if self.gen_options.include_animations:
            prompt_parts.append("\nInclude subtle CSS or SMIL animations where appropriate.")
        
        # Technical instructions
        prompt_parts.extend([
            f"\n\n=== TECHNICAL REQUIREMENTS ===",
            f"1. Return ONLY valid SVG code, no explanations or markdown",
            f"2. Do not include <?xml?> declaration or <!DOCTYPE>",
            f"3. Start with <svg> and end with </svg>",
            f"4. Set viewBox=\"0 0 {width} {height}\"",
            f"5. Include xmlns=\"http://www.w3.org/2000/svg\"",
            f"6. Use absolute positioning within the viewBox",
            f"7. Ensure all elements are properly closed",
            f"8. Valid elements: svg, g, path, rect, circle, ellipse, line, polyline, polygon, text, tspan, defs, use, clipPath, mask, linearGradient, radialGradient, stop"
        ])
        
        if self.gen_options.optimize_paths:
            prompt_parts.append("9. Optimize paths - use shorthand commands, remove unnecessary precision")
        
        if self.gen_options.add_accessibility:
            prompt_parts.append("10. Add <title> and <desc> elements for accessibility")

        # Negative prompt
        negative = getattr(self.gen_options, 'negative_prompt', '')
        if negative and negative.strip():
            prompt_parts.append(f"\n\nDo NOT include any of the following: {negative.strip()}")
        
        return "\n".join(prompt_parts)
    
    # ==================== API Calls ====================
    
    def call_api_with_retry(self, prompt, api_key, variation_index=0):
        """Call API with retry logic and exponential back-off."""
        last_error = None

        for attempt in range(self.gen_options.retry_count + 1):
            try:
                if self.gen_options.variations > 1:
                    variation_prompt = f"{prompt}\n\n(Variation {variation_index + 1} - create a unique interpretation)"
                else:
                    variation_prompt = prompt

                return self.call_api(variation_prompt, api_key)

            except Exception as e:
                last_error = e
                if attempt < self.gen_options.retry_count:
                    inkex.utils.debug(f"API call failed (attempt {attempt+1}), retrying in {2**attempt}s...")
                    time.sleep(2 ** attempt)

        raise last_error
    
    def call_api(self, prompt, api_key):
        """Route to the appropriate provider module."""
        provider = self.gen_options.provider.lower()
        opts = {
            'model':       self.gen_options.model,
            'temperature': self.gen_options.temperature,
            'max_tokens':  self.gen_options.max_tokens,
            'timeout':     self.gen_options.timeout,
            'seed':        self.gen_options.seed,
            'endpoint':    self.gen_options.api_endpoint,
        }
        sys_prompt = self.get_system_prompt()

        if not _PROVIDERS_LOADED:
            return self._fallback_openai_call(prompt, sys_prompt, opts, api_key)

        if provider == 'openai':
            return _prov_openai.generate(prompt, sys_prompt, opts, api_key, _SSL_CONTEXT)
        elif provider == 'anthropic':
            return _prov_anthropic.generate(prompt, sys_prompt, opts, api_key, _SSL_CONTEXT)
        elif provider == 'google':
            return _prov_google.generate(prompt, sys_prompt, opts, api_key, _SSL_CONTEXT)
        elif provider == 'ollama':
            return _prov_ollama.generate(prompt, sys_prompt, opts, api_key, _SSL_CONTEXT)
        elif provider == 'azure':
            return _prov_azure.generate(prompt, sys_prompt, opts, api_key, _SSL_CONTEXT)
        elif provider == 'custom_openai':
            return _prov_custom.generate(prompt, sys_prompt, opts, api_key, _SSL_CONTEXT)
        else:
            raise Exception(f"Unknown provider: {provider}")

    def _fallback_openai_call(self, prompt, system_prompt, opts, api_key):
        """Minimal inline OpenAI call used when provider modules failed to import."""
        import json as _json
        url = 'https://api.openai.com/v1/chat/completions'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
        }
        data = {
            'model': opts.get('model', 'gpt-4o'),
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user',   'content': prompt},
            ],
            'temperature': float(opts.get('temperature', 0.7)),
            'max_tokens':  int(opts.get('max_tokens', 4000)),
        }
        req = urllib.request.Request(
            url, data=_json.dumps(data).encode(), headers=headers, method='POST'
        )
        with urllib.request.urlopen(req, timeout=int(opts.get('timeout', 60)),
                                    context=_SSL_CONTEXT) as r:
            result = _json.loads(r.read().decode())
        choices = result.get('choices', [])
        if choices:
            return choices[0]['message']['content'].strip()
        raise Exception('No response from fallback OpenAI call')

    def clean_svg_response(self, svg_code):
        """Clean up SVG code from API response."""
        # Remove markdown code blocks if present
        svg_code = re.sub(r'^```(?:svg|xml)?\s*\n?', '', svg_code, flags=re.MULTILINE)
        svg_code = re.sub(r'\n?```\s*$', '', svg_code, flags=re.MULTILINE)
        
        # Remove XML declaration if present
        svg_code = re.sub(r'<\?xml[^>]+\?>\s*', '', svg_code)
        svg_code = re.sub(r'<!DOCTYPE[^>]+>\s*', '', svg_code)
        
        # Fix common AI mistakes
        svg_code = re.sub(r'xmlns=""', '', svg_code)
        svg_code = svg_code.replace('&nbsp;', ' ')
        
        # Trim whitespace
        svg_code = svg_code.strip()
        
        return svg_code
    
    def validate_and_fix_svg(self, svg_code, width, height):
        """
        Validate and fix common SVG issues.

        Ensures:
        - The code starts with <svg
        - xmlns is present
        - viewBox is set to "0 0 {width} {height}"
        - width and height attributes are set to {width} and {height} (in px)
          so the viewBox-to-pixel mapping is always 1:1 when imported.
        """
        if not svg_code.startswith('<svg'):
            svg_match = re.search(r'<svg[^>]*>.*</svg>', svg_code, re.DOTALL)
            if svg_match:
                svg_code = svg_match.group(0)
            else:
                svg_code = (
                    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">' + svg_code + '</svg>'
                )

        if 'xmlns=' not in svg_code:
            svg_code = svg_code.replace('<svg', '<svg xmlns="http://www.w3.org/2000/svg"', 1)

        # Normalise viewBox to the target dimensions so elements always span 0..width, 0..height
        if 'viewBox=' not in svg_code:
            svg_code = svg_code.replace('<svg', f'<svg viewBox="0 0 {width} {height}"', 1)

        # Force width / height to match target so the viewBox ratio is 1:1
        svg_code = re.sub(r'width="[^"]*"', f'width="{width}"', svg_code, count=1)
        svg_code = re.sub(r'height="[^"]*"', f'height="{height}"', svg_code, count=1)
        if 'width="' not in svg_code[:300]:
            svg_code = svg_code.replace('<svg', f'<svg width="{width}" height="{height}"', 1)

        return svg_code
    
    def add_svg_to_document(self, svg_code, target_width, target_height, offset_x=0, variation_num=1):
        """
        Parse SVG code and insert it into the Inkscape document.

        Fixes applied:
        - Guards against excessively large SVG strings that would crash ET.
        - Computes a scale transform from the SVG viewBox to the target pixel size
          so the result always fills the requested area regardless of what the AI
          used as its own coordinate system.
        - Centers correctly by reading the SVG viewBox origin, not just viewport_width.
        """
        # Guard against huge responses that could hang or crash
        svg_bytes = len(svg_code.encode('utf-8'))
        if svg_bytes > self.MAX_SVG_BYTES:
            inkex.errormsg(
                f"Generated SVG is very large ({svg_bytes // 1024} KB) and cannot be "
                f"inserted safely. Try reducing complexity or max_tokens."
            )
            return

        try:
            svg_root = ET.fromstring(svg_code)
        except ET.ParseError as e:
            inkex.errormsg(
                f"Failed to parse generated SVG: {e}\n\n"
                f"First 500 chars:\n{svg_code[:500]}"
            )
            return
        except Exception as e:
            inkex.errormsg(f"Unexpected error parsing SVG: {e}")
            return

        try:
            # ── Compute scale from SVG viewBox to target size ─────────────
            scale_x = scale_y = 1.0
            vb_str = svg_root.get('viewBox', '').strip()
            if vb_str:
                parts = vb_str.split()
                if len(parts) == 4:
                    vb_w = float(parts[2])
                    vb_h = float(parts[3])
                    if vb_w > 0:
                        scale_x = target_width  / vb_w
                    if vb_h > 0:
                        scale_y = target_height / vb_h
            # Fall back to using explicit width/height attrs when no viewBox scaling
            if scale_x == 1.0 and scale_y == 1.0:
                svg_w_str = svg_root.get('width', '').rstrip('px')
                svg_h_str = svg_root.get('height', '').rstrip('px')
                try:
                    svg_px_w = float(svg_w_str) if svg_w_str and not svg_w_str.endswith('%') else target_width
                    svg_px_h = float(svg_h_str) if svg_h_str and not svg_h_str.endswith('%') else target_height
                    if svg_px_w > 0:
                        scale_x = target_width  / svg_px_w
                    if svg_px_h > 0:
                        scale_y = target_height / svg_px_h
                except ValueError:
                    pass

            # ── Document position ─────────────────────────────────────────
            # Use viewBox to get the true coordinate origin of the document
            try:
                doc_vb = self.svg.get_viewbox()
                doc_origin_x = doc_vb[0]
                doc_origin_y = doc_vb[1]
                doc_w        = doc_vb[2]
                doc_h        = doc_vb[3]
            except Exception:
                doc_origin_x = doc_origin_y = 0.0
                doc_w = float(self.svg.viewport_width)
                doc_h = float(self.svg.viewport_height)

            if self.gen_options.position == "origin":
                pos_x = doc_origin_x
                pos_y = doc_origin_y
            elif self.gen_options.position == "selection" and self.svg.selection:
                bbox = None
                for elem in self.svg.selection.values():
                    elem_bbox = elem.bounding_box()
                    if elem_bbox:
                        bbox = elem_bbox if bbox is None else (bbox | elem_bbox)
                if bbox:
                    pos_x = bbox.right + 20
                    pos_y = bbox.top
                else:
                    pos_x = doc_origin_x + (doc_w - target_width)  / 2
                    pos_y = doc_origin_y + (doc_h - target_height) / 2
            else:  # center (default)
                pos_x = doc_origin_x + (doc_w - target_width)  / 2
                pos_y = doc_origin_y + (doc_h - target_height) / 2

            pos_x += offset_x

            # ── Build transform string ────────────────────────────────────
            scale_part = (
                f' scale({scale_x:.6g}, {scale_y:.6g})' if (scale_x != 1.0 or scale_y != 1.0) else ''
            )
            transform = f'translate({pos_x:.4g}, {pos_y:.4g}){scale_part}'

            # ── Create / fill group ───────────────────────────────────────
            if self.gen_options.add_group:
                group = Group()
                if self.gen_options.group_name:
                    group_id = (
                        f"{self.gen_options.group_name}-{variation_num}"
                        if self.gen_options.variations > 1
                        else self.gen_options.group_name
                    )
                else:
                    group_id = self.svg.get_unique_id(f'ai-generated-{variation_num}')
                group.set('id', group_id)
                group.set('transform', transform)

                if self.gen_options.add_accessibility:
                    title = inkex.Title()
                    title.text = self.gen_options.prompt[:100]
                    group.append(title)
                    desc = inkex.Desc()
                    desc.text = (
                        f"AI-generated SVG using "
                        f"{self.gen_options.provider}/{self.gen_options.model}"
                    )
                    group.append(desc)

                # Import <defs> first so gradient/clip IDs resolve
                for child in svg_root:
                    tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                    if tag == 'defs':
                        self.import_defs(child)

                for child in svg_root:
                    tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                    if tag != 'defs':
                        new_elem = self.import_element(child)
                        if new_elem is not None:
                            group.append(new_elem)

                self._get_target_layer().append(group)
            else:
                for child in svg_root:
                    new_elem = self.import_element(child)
                    if new_elem is not None:
                        existing = new_elem.get('transform', '')
                        new_elem.set(
                            'transform',
                            f'{transform} {existing}' if existing else transform,
                        )
                        self._get_target_layer().append(new_elem)

        except Exception as e:
            inkex.errormsg(f"Error inserting SVG into document: {e}")
            return
    
    def import_defs(self, defs_element):
        """Import defs (gradients, patterns, etc.) into document."""
        # Get or create defs in document
        doc_defs = self.svg.defs
        
        for child in defs_element:
            new_elem = self.import_element(child)
            if new_elem is not None:
                doc_defs.append(new_elem)
    
    def import_element(self, et_element):
        """Convert ElementTree element to Inkex element."""
        try:
            # Get the tag name without namespace
            tag = et_element.tag.split('}')[-1] if '}' in et_element.tag else et_element.tag
            
            # Extended element map
            element_map = {
                'rect': inkex.Rectangle,
                'circle': inkex.Circle,
                'ellipse': inkex.Ellipse,
                'line': inkex.Line,
                'polyline': inkex.Polyline,
                'polygon': inkex.Polygon,
                'path': inkex.PathElement,
                'text': inkex.TextElement,
                'tspan': inkex.Tspan,
                'g': inkex.Group,
                'defs': inkex.Defs,
                'use': inkex.Use,
                'clipPath': inkex.ClipPath,
                'mask': inkex.Mask,
                'linearGradient': inkex.LinearGradient,
                'radialGradient': inkex.RadialGradient,
                'stop': inkex.Stop,
                'image': inkex.Image,
                'title': inkex.Title,
                'desc': inkex.Desc,
                'symbol': inkex.Symbol,
                'marker': inkex.Marker,
                'pattern': inkex.Pattern,
                'filter': inkex.Filter,
                'style': inkex.StyleElement,
            }
            
            # Create appropriate inkex element
            if tag in element_map:
                elem_class = element_map[tag]
                new_elem = elem_class()
                
                # Copy all attributes
                for key, value in et_element.attrib.items():
                    # Remove namespace from attribute key
                    clean_key = key.split('}')[-1] if '}' in key else key
                    new_elem.set(clean_key, value)
                
                # Copy text content if any
                if et_element.text and et_element.text.strip():
                    new_elem.text = et_element.text

                # Copy tail text (text after closing tag, relevant in <text> elements)
                if et_element.tail and et_element.tail.strip():
                    new_elem.tail = et_element.tail

                # Recursively add children for container elements
                container_tags = {'g', 'defs', 'clipPath', 'mask', 'symbol', 'marker', 
                                  'pattern', 'linearGradient', 'radialGradient', 'filter', 'text'}
                if tag in container_tags:
                    for child in et_element:
                        child_elem = self.import_element(child)
                        if child_elem is not None:
                            new_elem.append(child_elem)
                
                return new_elem
            else:
                # For unsupported elements, create generic element
                try:
                    new_elem = inkex.BaseElement()
                    new_elem.tag = tag
                    for key, value in et_element.attrib.items():
                        new_elem.set(key, value)
                    if et_element.text:
                        new_elem.text = et_element.text
                    if et_element.tail and et_element.tail.strip():
                        new_elem.tail = et_element.tail
                    return new_elem
                except Exception:
                    return None

        except Exception:
            # Silently skip problematic elements
            return None


if __name__ == '__main__':
    SVGLLMGenerator().run()