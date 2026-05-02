#!/usr/bin/env python3
"""
Inkscape extension to generate SVG objects using multiple AI providers.
Supports OpenAI, Anthropic, Google Gemini, and Ollama (local).
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
        'generate_url': 'https://api.openai.com/v1/chat/completions',
        'env_key': 'OPENAI_API_KEY',
        'config_key': 'openai_api_key',
        'models': ['gpt-4-turbo', 'gpt-4o', 'gpt-4o-mini', 'gpt-3.5-turbo'],
        'sizes': ['1024x1024', '1024x1792', '1792x1024', '512x512', '256x256']
    },
    'anthropic': {
        'name': 'Anthropic Claude',
        'generate_url': 'https://api.anthropic.com/v1/messages',
        'env_key': 'ANTHROPIC_API_KEY',
        'config_key': 'anthropic_api_key',
        'models': ['claude-3-5-sonnet-20241022', 'claude-3-opus-20240229', 'claude-3-haiku-20240307'],
        'sizes': ['1024x1024']
    },
    'google': {
        'name': 'Google Gemini',
        'generate_url': 'https://generativelanguage.googleapis.com/v1beta/models',
        'env_key': 'GOOGLE_API_KEY',
        'config_key': 'google_api_key',
        'models': ['gemini-1.5-pro', 'gemini-1.5-flash'],
        'sizes': ['1024x1024']
    },
    'azure': {
        'name': 'Azure OpenAI',
        'generate_url': '',  # Constructed from endpoint at call time
        'env_key': 'AZURE_OPENAI_API_KEY',
        'config_key': 'azure_openai_api_key',
        'models': ['gpt-4o', 'gpt-4-turbo', 'gpt-35-turbo'],
        'sizes': ['1024x1024']
    },
    'ollama': {
        'name': 'Ollama (Local)',
        'generate_url': 'http://localhost:11434/api/generate',
        'env_key': '',
        'config_key': '',
        'models': ['llama3.1', 'codellama', 'mistral'],
        'sizes': ['1024x1024', '768x768', '512x512']
    }
}


    def __init__(self):
        super().__init__()
        self.config_path = os.path.join(os.path.dirname(__file__), self.CONFIG_FILENAME)
        self.history_path = os.path.join(os.path.dirname(__file__), self.HISTORY_FILENAME)
        self.templates_path = os.path.join(os.path.dirname(__file__), self.TEMPLATES_FILENAME)
        self.prompt_loader = _PromptLoader(os.path.dirname(__file__)) if _PromptLoader else None
    
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
        # Azure uses a custom deployment name â€” any value is valid
        if provider == 'azure':
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
        """Route to appropriate API based on provider."""
        provider = self.gen_options.provider.lower()
        
        if provider == "openai":
            return self.call_openai_api(prompt, api_key)
        elif provider == "anthropic":
            return self.call_anthropic_api(prompt, api_key)
        elif provider == "google":
            return self.call_google_api(prompt, api_key)
        elif provider == "azure":
            return self.call_azure_api(prompt, api_key)
        elif provider == "ollama":
            return self.call_ollama_api(prompt)
        else:
            raise Exception(f"Unknown provider: {provider}")
    
    def call_openai_api(self, prompt, api_key):
        """Call OpenAI API to generate SVG code."""
        url = "https://api.openai.com/v1/chat/completions"
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}'
        }
        
        data = {
            'model': self.gen_options.model,
            'messages': [
                {
                    'role': 'system',
                    'content': self.get_system_prompt()
                },
                {
                    'role': 'user',
                    'content': prompt
                }
            ],
            'temperature': self.gen_options.temperature,
            'max_tokens': self.gen_options.max_tokens
        }
        
        # Add seed if specified
        if self.gen_options.seed >= 0:
            data['seed'] = self.gen_options.seed
        
        return self._make_api_request(url, headers, data)
    
    def call_anthropic_api(self, prompt, api_key):
        """Call Anthropic Claude API to generate SVG code."""
        url = "https://api.anthropic.com/v1/messages"
        
        headers = {
            'Content-Type': 'application/json',
            'x-api-key': api_key,
            'anthropic-version': '2023-06-01'
        }
        
        # Map model names
        model = self.gen_options.model
        if not model.startswith('claude'):
            model = 'claude-3-5-sonnet-20241022'  # Default Claude model
        
        data = {
            'model': model,
            'max_tokens': self.gen_options.max_tokens,
            'messages': [
                {
                    'role': 'user',
                    'content': f"{self.get_system_prompt()}\n\n{prompt}"
                }
            ]
        }
        
        return self._make_api_request(url, headers, data, response_parser='anthropic')
    
    def call_google_api(self, prompt, api_key):
        """Call Google Gemini API to generate SVG code."""
        model = self.gen_options.model
        if not model.startswith('gemini'):
            model = 'gemini-1.5-flash'  # Default Gemini model
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        
        headers = {
            'Content-Type': 'application/json'
        }
        
        generation_config = {
            'temperature': self.gen_options.temperature,
            'maxOutputTokens': self.gen_options.max_tokens
        }
        if self.gen_options.seed >= 0:
            generation_config['seed'] = self.gen_options.seed

        data = {
            'contents': [{
                'parts': [{
                    'text': f"{self.get_system_prompt()}\n\n{prompt}"
                }]
            }],
            'generationConfig': generation_config
        }

        return self._make_api_request(url, headers, data, response_parser='google')
    
    def call_ollama_api(self, prompt):
        """Call local Ollama API to generate SVG code."""
        endpoint = (self.gen_options.api_endpoint or "http://localhost:11434").rstrip('/')
        if not endpoint.startswith(('http://', 'https://')):
            raise Exception(
                f"Invalid Ollama endpoint: '{endpoint}'. Must start with http:// or https://"
            )
        url = f"{endpoint}/api/generate"

        headers = {
            'Content-Type': 'application/json'
        }

        model = self.gen_options.model
        if model.startswith('gpt') or model.startswith('claude') or model.startswith('gemini'):
            model = 'llama3.1'

        ollama_options = {
            'temperature': self.gen_options.temperature,
            'num_predict': self.gen_options.max_tokens
        }
        if self.gen_options.seed >= 0:
            ollama_options['seed'] = self.gen_options.seed

        data = {
            'model': model,
            'prompt': f"{self.get_system_prompt()}\n\n{prompt}",
            'stream': False,
            'options': ollama_options
        }

        return self._make_api_request(url, headers, data, response_parser='ollama')

    def call_azure_api(self, prompt, api_key):
        """Call Azure OpenAI API (same schema as OpenAI, different URL and auth header)."""
        endpoint = (self.gen_options.api_endpoint or '').rstrip('/')
        if not endpoint.startswith(('http://', 'https://')):
            raise Exception(
                "Azure OpenAI requires a valid endpoint URL in the 'Endpoint' field "
                "(e.g. https://your-resource.openai.azure.com)"
            )
        deployment = self.gen_options.model  # deployment name = model name by convention
        api_version = "2024-08-01-preview"
        url = (
            f"{endpoint}/openai/deployments/{deployment}"
            f"/chat/completions?api-version={api_version}"
        )
        headers = {
            'Content-Type': 'application/json',
            'api-key': api_key,
        }
        data = {
            'messages': [
                {'role': 'system', 'content': self.get_system_prompt()},
                {'role': 'user', 'content': prompt},
            ],
            'temperature': self.gen_options.temperature,
            'max_tokens': self.gen_options.max_tokens,
        }
        if self.gen_options.seed >= 0:
            data['seed'] = self.gen_options.seed
        return self._make_api_request(url, headers, data)

    def _make_api_request(self, url, headers, data, response_parser='openai'):
        """Make HTTP request to API with certificate-verified SSL."""
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode('utf-8'),
            headers=headers,
            method='POST'
        )

        try:
            with urllib.request.urlopen(req, timeout=self.gen_options.timeout,
                                        context=_SSL_CONTEXT) as response:
                result = json.loads(response.read().decode('utf-8'))
                return self._parse_response(result, response_parser)

        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            try:
                error_data = json.loads(error_body)
                error_message = error_data.get('error', {}).get('message', str(e))
            except Exception:
                error_message = str(e)
            raise Exception(f"API Error ({e.code}): {error_message}")

        except urllib.error.URLError as e:
            raise Exception(f"Network Error: {str(e)}")
    
    def _parse_response(self, result, parser_type):
        """Parse API response based on provider."""
        svg_code = None
        
        if parser_type == 'openai':
            if 'choices' in result and len(result['choices']) > 0:
                svg_code = result['choices'][0]['message']['content'].strip()
        
        elif parser_type == 'anthropic':
            if 'content' in result and len(result['content']) > 0:
                svg_code = result['content'][0]['text'].strip()
        
        elif parser_type == 'google':
            if 'candidates' in result and len(result['candidates']) > 0:
                parts = result['candidates'][0].get('content', {}).get('parts', [])
                if parts:
                    svg_code = parts[0].get('text', '').strip()
        
        elif parser_type == 'ollama':
            svg_code = result.get('response', '').strip()
        
        if not svg_code:
            raise Exception("No response from API")

        return self.clean_svg_response(svg_code)
    
    # ==================== SVG Processing ====================
    
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
        """Validate and attempt to fix common SVG issues."""
        # Ensure it starts with <svg
        if not svg_code.startswith('<svg'):
            # Try to extract SVG from response
            svg_match = re.search(r'<svg[^>]*>.*</svg>', svg_code, re.DOTALL)
            if svg_match:
                svg_code = svg_match.group(0)
            else:
                # Wrap content in SVG tags
                svg_code = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">{svg_code}</svg>'
        
        # Ensure xmlns is present
        if 'xmlns=' not in svg_code:
            svg_code = svg_code.replace('<svg', '<svg xmlns="http://www.w3.org/2000/svg"', 1)
        
        # Ensure viewBox is present
        if 'viewBox=' not in svg_code:
            svg_code = svg_code.replace('<svg', f'<svg viewBox="0 0 {width} {height}"', 1)
        
        return svg_code
    
    def add_svg_to_document(self, svg_code, target_width, target_height, offset_x=0, variation_num=1):
        """Parse SVG code and add it to the document."""
        try:
            # Parse the SVG code
            svg_root = ET.fromstring(svg_code)
            
            # Get document dimensions
            doc_width = self.svg.viewport_width
            doc_height = self.svg.viewport_height
            
            # Calculate position based on option
            if self.gen_options.position == "origin":
                pos_x, pos_y = 0, 0
            elif self.gen_options.position == "selection" and self.svg.selection:
                # Get selection bounding box
                bbox = None
                for elem in self.svg.selection.values():
                    elem_bbox = elem.bounding_box()
                    if elem_bbox:
                        if bbox is None:
                            bbox = elem_bbox
                        else:
                            bbox = bbox | elem_bbox
                if bbox:
                    pos_x = bbox.right + 20
                    pos_y = bbox.top
                else:
                    pos_x = (doc_width - target_width) / 2
                    pos_y = (doc_height - target_height) / 2
            else:  # center
                pos_x = (doc_width - target_width) / 2
                pos_y = (doc_height - target_height) / 2
            
            # Apply offset for variations
            pos_x += offset_x
            
            # Create a group if requested
            if self.gen_options.add_group:
                group = Group()
                
                # Set group ID
                if self.gen_options.group_name:
                    group_id = f"{self.gen_options.group_name}-{variation_num}" if self.gen_options.variations > 1 else self.gen_options.group_name
                else:
                    group_id = self.svg.get_unique_id(f'ai-generated-{variation_num}')
                
                group.set('id', group_id)
                group.set('transform', f'translate({pos_x}, {pos_y})')
                
                # Add accessibility elements if requested
                if self.gen_options.add_accessibility:
                    title = inkex.Title()
                    title.text = self.gen_options.prompt[:100]
                    group.append(title)
                    
                    desc = inkex.Desc()
                    desc.text = f"AI-generated SVG using {self.gen_options.provider}/{self.gen_options.model}"
                    group.append(desc)
                
                # Import defs first if present
                for child in svg_root:
                    tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                    if tag == 'defs':
                        self.import_defs(child)
                
                # Import all other children from parsed SVG
                for child in svg_root:
                    tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                    if tag != 'defs':
                        new_elem = self.import_element(child)
                        if new_elem is not None:
                            group.append(new_elem)
                
                # Add the group to target layer
                self._get_target_layer().append(group)
            else:
                # Add elements directly with translation
                for child in svg_root:
                    new_elem = self.import_element(child)
                    if new_elem is not None:
                        existing_transform = new_elem.get('transform', '')
                        if existing_transform:
                            new_elem.set('transform', f'translate({pos_x}, {pos_y}) {existing_transform}')
                        else:
                            new_elem.set('transform', f'translate({pos_x}, {pos_y})')
                        
                        self._get_target_layer().append(new_elem)
        
        except ET.ParseError as e:
            inkex.errormsg(f"Failed to parse SVG code: {str(e)}\n\nReceived code:\n{svg_code[:500]}...")
            return
        except Exception as e:
            inkex.errormsg(f"Error adding SVG to document: {str(e)}")
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