#!/usr/bin/env python3
"""
Inkscape extension to generate SVG objects using multiple AI providers.
Supports OpenAI, Anthropic, Google Gemini, and Ollama (local).
"""

import inkex
from inkex import Group
import re
import urllib.request
import json
import xml.etree.ElementTree as ET
import ssl
import os
from datetime import datetime


class SVGLLMGenerator(inkex.EffectExtension):
    """Extension to generate SVG using various LLM providers."""
    
    CONFIG_FILENAME = '.config.json'
    HISTORY_FILENAME = '.svg_llm_history.json'
    MAX_HISTORY = 50
    
    def __init__(self):
        super().__init__()
        self.config_path = os.path.join(os.path.dirname(__file__), self.CONFIG_FILENAME)
        self.history_path = os.path.join(os.path.dirname(__file__), self.HISTORY_FILENAME)
    
    def add_arguments(self, pars):
        # Tab
        pars.add_argument("--tab", type=str, default="prompt", help="Active tab")
        
        # Provider settings
        pars.add_argument("--provider", type=str, default="openai", 
            help="API provider (openai, anthropic, google, ollama)")
        pars.add_argument("--api_key", type=str, default="", help="API key")
        pars.add_argument("--api_endpoint", type=str, default="", 
            help="Custom API endpoint (for Ollama or self-hosted)")
        pars.add_argument("--save_api_key", type=inkex.Boolean, default=False, 
            help="Save API key for future use")
        
        # Prompt settings
        pars.add_argument("--prompt", type=str, default="", help="User prompt")
        pars.add_argument("--use_selection_context", type=inkex.Boolean, default=False,
            help="Include selected elements as context")
        pars.add_argument("--prompt_preset", type=str, default="none",
            help="Prompt preset (icon, illustration, diagram, pattern, logo)")
        
        # Model settings
        pars.add_argument("--model", type=str, default="gpt-4-turbo", help="Model to use")
        pars.add_argument("--temperature", type=float, default=0.7, help="Temperature")
        pars.add_argument("--max_tokens", type=int, default=4000, help="Max tokens")
        pars.add_argument("--timeout", type=int, default=60, help="Request timeout in seconds")
        pars.add_argument("--retry_count", type=int, default=2, help="Number of retries on failure")
        
        # Size settings
        pars.add_argument("--size", type=str, default="medium", help="Object size")
        pars.add_argument("--custom_width", type=int, default=400, help="Custom width")
        pars.add_argument("--custom_height", type=int, default=400, help="Custom height")
        pars.add_argument("--aspect_ratio", type=str, default="square",
            help="Aspect ratio (square, landscape, portrait, widescreen)")
        
        # Style settings
        pars.add_argument("--style_hint", type=str, default="none", help="Style hint")
        pars.add_argument("--color_scheme", type=str, default="any", help="Color scheme")
        pars.add_argument("--complexity", type=str, default="medium",
            help="Complexity level (simple, medium, complex)")
        pars.add_argument("--stroke_style", type=str, default="any",
            help="Stroke style (any, thin, medium, thick, none)")
        
        # Output settings
        pars.add_argument("--add_group", type=inkex.Boolean, default=True, help="Add group")
        pars.add_argument("--group_name", type=str, default="", help="Custom group name")
        pars.add_argument("--position", type=str, default="center",
            help="Position (center, cursor, origin, selection)")
        pars.add_argument("--include_animations", type=inkex.Boolean, default=False,
            help="Include CSS/SMIL animations")
        pars.add_argument("--include_gradients", type=inkex.Boolean, default=True,
            help="Allow gradients in output")
        pars.add_argument("--add_accessibility", type=inkex.Boolean, default=False,
            help="Add title/desc for accessibility")
        pars.add_argument("--optimize_paths", type=inkex.Boolean, default=True,
            help="Request optimized paths")
        
        # Advanced settings
        pars.add_argument("--variations", type=int, default=1,
            help="Number of variations to generate (1-4)")
        pars.add_argument("--seed", type=int, default=-1,
            help="Random seed (-1 for random)")
        pars.add_argument("--save_to_history", type=inkex.Boolean, default=True,
            help="Save prompt to history")
    
    def effect(self):
        """Main effect function."""
        # Load config and potentially saved API key
        config = self.load_config()
        
        # Get API key (from argument or saved config)
        api_key = self.options.api_key
        if (not api_key or api_key == "sk-...") and self.options.provider in config.get('api_keys', {}):
            api_key = config['api_keys'][self.options.provider]
        
        # Validate API key (not needed for local Ollama)
        if self.options.provider != "ollama":
            if not api_key or api_key.startswith("sk-..."):
                inkex.errormsg(f"Please provide a valid API key for {self.options.provider}.")
                return
        
        # Save API key if requested
        if self.options.save_api_key and api_key:
            self.save_api_key(api_key)
        
        # Validate prompt
        if not self.options.prompt or len(self.options.prompt.strip()) < 3:
            inkex.errormsg("Please provide a description of what you want to generate.")
            return
        
        # Get size
        width, height = self.get_size()
        
        # Get selection context if enabled
        selection_context = ""
        if self.options.use_selection_context and self.svg.selection:
            selection_context = self.get_selection_context()
        
        # Build the enhanced prompt
        enhanced_prompt = self.build_prompt(width, height, selection_context)
        
        # Generate variations
        variations = min(max(1, self.options.variations), 4)
        
        for i in range(variations):
            try:
                svg_code = self.call_api_with_retry(enhanced_prompt, api_key, i)
                
                if not svg_code:
                    inkex.errormsg(f"No SVG code generated for variation {i+1}. Please try again.")
                    continue
                
                # Validate SVG
                svg_code = self.validate_and_fix_svg(svg_code, width, height)
                
                # Parse and add SVG to document
                offset_x = i * (width + 20) if variations > 1 else 0
                self.add_svg_to_document(svg_code, width, height, offset_x, variation_num=i+1)
                
            except Exception as e:
                inkex.errormsg(f"Error generating variation {i+1}: {str(e)}")
                continue
        
        # Save to history
        if self.options.save_to_history:
            self.save_to_history(self.options.prompt, width, height)
    
    # ==================== Configuration Management ====================
    
    def load_config(self):
        """Load saved configuration."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {'api_keys': {}, 'last_provider': 'openai'}
    
    def save_config(self, config):
        """Save configuration."""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            inkex.errormsg(f"Warning: Could not save config: {e}")
    
    def save_api_key(self, api_key):
        """Save API key for the current provider."""
        config = self.load_config()
        if 'api_keys' not in config:
            config['api_keys'] = {}
        config['api_keys'][self.options.provider] = api_key
        config['last_provider'] = self.options.provider
        self.save_config(config)
    
    def load_history(self):
        """Load prompt history."""
        if os.path.exists(self.history_path):
            try:
                with open(self.history_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
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
            'provider': self.options.provider,
            'model': self.options.model,
            'style': self.options.style_hint,
            'color_scheme': self.options.color_scheme
        }
        history.insert(0, entry)
        history = history[:self.MAX_HISTORY]  # Keep only last N entries
        
        try:
            with open(self.history_path, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=2)
        except:
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
        
        if self.options.size == 'custom':
            return (self.options.custom_width, self.options.custom_height)
        
        base = base_sizes.get(self.options.size, 400)
        ratio = aspect_ratios.get(self.options.aspect_ratio, (1, 1))
        
        # Calculate dimensions maintaining aspect ratio
        if ratio[0] >= ratio[1]:
            width = base
            height = int(base * ratio[1] / ratio[0])
        else:
            height = base
            width = int(base * ratio[0] / ratio[1])
        
        return (width, height)
    
    # ==================== Selection Context ====================
    
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
        preset_prompts = {
            'icon': "Create a simple, recognizable icon suitable for UI/UX. Use clear shapes and minimal detail.",
            'illustration': "Create an artistic illustration with visual appeal and appropriate detail.",
            'diagram': "Create a clear, informative diagram with proper labels and connections.",
            'pattern': "Create a seamless repeating pattern that tiles correctly.",
            'logo': "Create a professional logo design that is scalable and memorable.",
            'flowchart': "Create a flowchart with clear boxes, arrows, and labels.",
            'infographic': "Create an informative graphic with data visualization elements."
        }
        
        if self.options.prompt_preset != "none" and self.options.prompt_preset in preset_prompts:
            prompt_parts.append(preset_prompts[self.options.prompt_preset])
        
        # Main prompt
        prompt_parts.append(f"\nGenerate SVG code for: {self.options.prompt}")
        prompt_parts.append(f"\nCanvas size: {width}x{height} pixels")
        
        # Selection context
        if selection_context:
            prompt_parts.append(f"\n{selection_context}")
            prompt_parts.append("Try to match the style of the selected elements.")
        
        # Complexity
        complexity_hints = {
            'simple': 'Use minimal elements, basic shapes only. Maximum 10-15 elements.',
            'medium': 'Use moderate complexity with some detail. Around 20-40 elements.',
            'complex': 'Include rich detail and many elements. Can be intricate.'
        }
        if self.options.complexity in complexity_hints:
            prompt_parts.append(f"\nComplexity: {complexity_hints[self.options.complexity]}")
        
        # Style hint
        if self.options.style_hint != "none":
            style_descriptions = {
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
            prompt_parts.append(f"\nStyle: {style_descriptions.get(self.options.style_hint, '')}")
        
        # Color scheme
        if self.options.color_scheme != "any":
            color_descriptions = {
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
            prompt_parts.append(f"\nColor palette: {color_descriptions.get(self.options.color_scheme, '')}")
        
        # Stroke style
        if self.options.stroke_style != "any":
            stroke_hints = {
                'thin': 'Use thin strokes (1-2px)',
                'medium': 'Use medium strokes (2-4px)',
                'thick': 'Use thick, bold strokes (4-8px)',
                'none': 'Do not use strokes, only fills',
                'variable': 'Use variable stroke widths for emphasis'
            }
            if self.options.stroke_style in stroke_hints:
                prompt_parts.append(f"\nStrokes: {stroke_hints[self.options.stroke_style]}")
        
        # Gradients
        if not self.options.include_gradients:
            prompt_parts.append("\nDo NOT use gradients - solid colors only.")
        
        # Animations
        if self.options.include_animations:
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
        
        if self.options.optimize_paths:
            prompt_parts.append("9. Optimize paths - use shorthand commands, remove unnecessary precision")
        
        if self.options.add_accessibility:
            prompt_parts.append("10. Add <title> and <desc> elements for accessibility")
        
        return "\n".join(prompt_parts)
    
    # ==================== API Calls ====================
    
    def call_api_with_retry(self, prompt, api_key, variation_index=0):
        """Call API with retry logic."""
        last_error = None
        
        for attempt in range(self.options.retry_count + 1):
            try:
                # Add variation hint if generating multiple
                if self.options.variations > 1:
                    variation_prompt = f"{prompt}\n\n(Variation {variation_index + 1} - create a unique interpretation)"
                else:
                    variation_prompt = prompt
                
                return self.call_api(variation_prompt, api_key)
                
            except Exception as e:
                last_error = e
                if attempt < self.options.retry_count:
                    continue
        
        raise last_error
    
    def call_api(self, prompt, api_key):
        """Route to appropriate API based on provider."""
        provider = self.options.provider.lower()
        
        if provider == "openai":
            return self.call_openai_api(prompt, api_key)
        elif provider == "anthropic":
            return self.call_anthropic_api(prompt, api_key)
        elif provider == "google":
            return self.call_google_api(prompt, api_key)
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
            'model': self.options.model,
            'messages': [
                {
                    'role': 'system',
                    'content': 'You are an expert SVG code generator. You only respond with valid, clean SVG code without any explanation or markdown formatting. Never include ```svg or ``` markers. Always produce well-formed, valid SVG.'
                },
                {
                    'role': 'user',
                    'content': prompt
                }
            ],
            'temperature': self.options.temperature,
            'max_tokens': self.options.max_tokens
        }
        
        # Add seed if specified
        if self.options.seed >= 0:
            data['seed'] = self.options.seed
        
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
        model = self.options.model
        if not model.startswith('claude'):
            model = 'claude-3-5-sonnet-20241022'  # Default Claude model
        
        data = {
            'model': model,
            'max_tokens': self.options.max_tokens,
            'messages': [
                {
                    'role': 'user',
                    'content': f"You are an expert SVG code generator. Generate ONLY valid SVG code without any explanation or markdown. Never include ```svg or ``` markers.\n\n{prompt}"
                }
            ]
        }
        
        return self._make_api_request(url, headers, data, response_parser='anthropic')
    
    def call_google_api(self, prompt, api_key):
        """Call Google Gemini API to generate SVG code."""
        model = self.options.model
        if not model.startswith('gemini'):
            model = 'gemini-1.5-flash'  # Default Gemini model
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        
        headers = {
            'Content-Type': 'application/json'
        }
        
        data = {
            'contents': [{
                'parts': [{
                    'text': f"You are an expert SVG code generator. Generate ONLY valid SVG code without any explanation or markdown. Never include ```svg or ``` markers.\n\n{prompt}"
                }]
            }],
            'generationConfig': {
                'temperature': self.options.temperature,
                'maxOutputTokens': self.options.max_tokens
            }
        }
        
        return self._make_api_request(url, headers, data, response_parser='google')
    
    def call_ollama_api(self, prompt):
        """Call local Ollama API to generate SVG code."""
        endpoint = self.options.api_endpoint or "http://localhost:11434"
        url = f"{endpoint}/api/generate"
        
        headers = {
            'Content-Type': 'application/json'
        }
        
        model = self.options.model
        if model.startswith('gpt') or model.startswith('claude') or model.startswith('gemini'):
            model = 'llama3.1'  # Default Ollama model
        
        data = {
            'model': model,
            'prompt': f"You are an expert SVG code generator. Generate ONLY valid SVG code without any explanation or markdown. Never include ```svg or ``` markers.\n\n{prompt}",
            'stream': False,
            'options': {
                'temperature': self.options.temperature,
                'num_predict': self.options.max_tokens
            }
        }
        
        return self._make_api_request(url, headers, data, response_parser='ollama', use_ssl=False)
    
    def _make_api_request(self, url, headers, data, response_parser='openai', use_ssl=True):
        """Make HTTP request to API."""
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode('utf-8'),
            headers=headers,
            method='POST'
        )
        
        context = ssl._create_unverified_context() if use_ssl else None
        
        try:
            with urllib.request.urlopen(req, timeout=self.options.timeout, context=context) as response:
                result = json.loads(response.read().decode('utf-8'))
                return self._parse_response(result, response_parser)
        
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            try:
                error_data = json.loads(error_body)
                if response_parser == 'anthropic':
                    error_message = error_data.get('error', {}).get('message', str(e))
                elif response_parser == 'google':
                    error_message = error_data.get('error', {}).get('message', str(e))
                else:
                    error_message = error_data.get('error', {}).get('message', str(e))
            except:
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
            if self.options.position == "origin":
                pos_x, pos_y = 0, 0
            elif self.options.position == "selection" and self.svg.selection:
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
            if self.options.add_group:
                group = Group()
                
                # Set group ID
                if self.options.group_name:
                    group_id = f"{self.options.group_name}-{variation_num}" if self.options.variations > 1 else self.options.group_name
                else:
                    group_id = self.svg.get_unique_id(f'ai-generated-{variation_num}')
                
                group.set('id', group_id)
                group.set('transform', f'translate({pos_x}, {pos_y})')
                
                # Add accessibility elements if requested
                if self.options.add_accessibility:
                    title = inkex.Title()
                    title.text = self.options.prompt[:100]
                    group.append(title)
                    
                    desc = inkex.Desc()
                    desc.text = f"AI-generated SVG using {self.options.provider}/{self.options.model}"
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
                
                # Add the group to current layer
                self.svg.get_current_layer().append(group)
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
                        
                        self.svg.get_current_layer().append(new_elem)
        
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
                    return new_elem
                except:
                    return None
        
        except Exception as e:
            # Silently skip problematic elements
            return None


if __name__ == '__main__':
    SVGLLMGenerator().run()