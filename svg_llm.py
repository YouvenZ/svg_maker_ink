#!/usr/bin/env python3
"""
Inkscape extension to generate SVG objects using OpenAI API.
"""

import inkex
from inkex import Group
import re
import urllib.request
import urllib.parse
import json
import xml.etree.ElementTree as ET
import ssl


class OpenAISVGGenerator(inkex.EffectExtension):
    """Extension to generate SVG using OpenAI."""
    
    def add_arguments(self, pars):
        pars.add_argument("--tab", type=str, default="prompt", help="Active tab")
        pars.add_argument("--api_key", type=str, default="", help="OpenAI API key")
        pars.add_argument("--prompt", type=str, default="", help="User prompt")
        pars.add_argument("--model", type=str, default="gpt-4-turbo", help="Model to use")
        pars.add_argument("--size", type=str, default="medium", help="Object size")
        pars.add_argument("--custom_width", type=int, default=400, help="Custom width")
        pars.add_argument("--custom_height", type=int, default=400, help="Custom height")
        pars.add_argument("--style_hint", type=str, default="none", help="Style hint")
        pars.add_argument("--color_scheme", type=str, default="any", help="Color scheme")
        pars.add_argument("--temperature", type=float, default=0.7, help="Temperature")
        pars.add_argument("--add_group", type=inkex.Boolean, default=True, help="Add group")
        pars.add_argument("--max_tokens", type=int, default=2000, help="Max tokens")
    
    def effect(self):
        """Main effect function."""
        # Validate API key
        if not self.options.api_key or self.options.api_key == "sk-...":
            inkex.errormsg("Please provide a valid OpenAI API key.")
            return
        
        # Validate prompt
        if not self.options.prompt or len(self.options.prompt.strip()) < 3:
            inkex.errormsg("Please provide a description of what you want to generate.")
            return
        
        # Get size
        width, height = self.get_size()
        
        # Build the enhanced prompt
        enhanced_prompt = self.build_prompt(width, height)
        
        # Call OpenAI API
        try:
            svg_code = self.call_openai_api(enhanced_prompt)
            
            if not svg_code:
                inkex.errormsg("No SVG code generated. Please try again.")
                return
            
            # Parse and add SVG to document
            self.add_svg_to_document(svg_code, width, height)
            
        except Exception as e:
            inkex.errormsg(f"Error: {str(e)}")
            return
    
    def get_size(self):
        """Get width and height based on size option."""
        size_map = {
            'small': (200, 200),
            'medium': (400, 400),
            'large': (600, 600),
            'custom': (self.options.custom_width, self.options.custom_height)
        }
        return size_map.get(self.options.size, (400, 400))
    
    def build_prompt(self, width, height):
        """Build enhanced prompt with all options."""
        prompt_parts = [
            f"Generate SVG code for: {self.options.prompt}",
            f"\nSize: {width}x{height}px"
        ]
        
        # Add style hint
        if self.options.style_hint != "none":
            style_descriptions = {
                'minimal': 'Use a minimal, clean design with simple shapes',
                'detailed': 'Include detailed elements and complexity',
                'flat': 'Use flat design principles with solid colors',
                'outline': 'Use only outlines/strokes, no fills',
                'filled': 'Use filled shapes with no or minimal strokes',
                'geometric': 'Use geometric shapes and patterns',
                'organic': 'Use organic, natural flowing shapes'
            }
            prompt_parts.append(f"\nStyle: {style_descriptions.get(self.options.style_hint, '')}")
        
        # Add color scheme
        if self.options.color_scheme != "any":
            color_descriptions = {
                'monochrome': 'Use only one color in different shades',
                'warm': 'Use warm colors (reds, oranges, yellows)',
                'cool': 'Use cool colors (blues, greens, purples)',
                'pastel': 'Use soft pastel colors',
                'vibrant': 'Use bright, vibrant colors',
                'grayscale': 'Use only black, white, and gray'
            }
            prompt_parts.append(f"\nColors: {color_descriptions.get(self.options.color_scheme, '')}")
        
        prompt_parts.extend([
            f"\n\nIMPORTANT INSTRUCTIONS:",
            f"1. Return ONLY valid SVG code, nothing else",
            f"2. Do not include <?xml?> declaration or <!DOCTYPE>",
            f"3. Start with <svg> tag and end with </svg>",
            f"4. Set viewBox=\"0 0 {width} {height}\"",
            f"5. Use absolute positioning within the viewBox",
            f"6. Ensure all elements are properly closed",
            f"7. Use valid SVG elements only (path, rect, circle, ellipse, line, polyline, polygon, text)",
            f"8. Do not use any external resources or images",
            f"9. Keep the SVG clean and well-structured"
        ])
        
        return "\n".join(prompt_parts)
    
    def call_openai_api(self, prompt):
        """Call OpenAI API to generate SVG code."""
        url = "https://api.openai.com/v1/chat/completions"
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.options.api_key}'
        }
        
        data = {
            'model': self.options.model,
            'messages': [
                {
                    'role': 'system',
                    'content': 'You are an expert SVG code generator. You only respond with valid, clean SVG code without any explanation or markdown formatting. Never include ```svg or ``` markers.'
                },
                {
                    'role': 'user',
                    'content': prompt
                }
            ],
            'temperature': self.options.temperature,
            'max_tokens': self.options.max_tokens
        }
        
        # Create request
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode('utf-8'),
            headers=headers,
            method='POST'
        )
        
        # Use unverified SSL context - this is the most reliable method on Windows
        context = ssl._create_unverified_context()
        
        try:
            with urllib.request.urlopen(req, timeout=60, context=context) as response:
                result = json.loads(response.read().decode('utf-8'))
                return self.process_api_response(result)
        
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            try:
                error_data = json.loads(error_body)
                error_message = error_data.get('error', {}).get('message', str(e))
            except:
                error_message = str(e)
            raise Exception(f"API Error: {error_message}")
        
        except urllib.error.URLError as e:
            raise Exception(f"Network Error: {str(e)}")
        
        except Exception as e:
            raise Exception(f"Unexpected Error: {str(e)}")
    
    def process_api_response(self, result):
        """Process the API response and extract SVG code."""
        if 'choices' in result and len(result['choices']) > 0:
            svg_code = result['choices'][0]['message']['content'].strip()
            
            # Clean up the response
            svg_code = self.clean_svg_response(svg_code)
            
            return svg_code
        else:
            raise Exception("No response from API")
    
    def clean_svg_response(self, svg_code):
        """Clean up SVG code from API response."""
        # Remove markdown code blocks if present
        svg_code = re.sub(r'^```svg\s*', '', svg_code, flags=re.MULTILINE)
        svg_code = re.sub(r'^```\s*', '', svg_code, flags=re.MULTILINE)
        svg_code = re.sub(r'\s*```$', '', svg_code, flags=re.MULTILINE)
        
        # Remove XML declaration if present
        svg_code = re.sub(r'<\?xml[^>]+\?>', '', svg_code)
        svg_code = re.sub(r'<!DOCTYPE[^>]+>', '', svg_code)
        
        # Trim whitespace
        svg_code = svg_code.strip()
        
        return svg_code
    
    def add_svg_to_document(self, svg_code, target_width, target_height):
        """Parse SVG code and add it to the document center."""
        try:
            # Parse the SVG code
            svg_root = ET.fromstring(svg_code)
            
            # Get document dimensions
            doc_width = self.svg.viewport_width
            doc_height = self.svg.viewport_height
            
            # Calculate center position
            center_x = (doc_width - target_width) / 2
            center_y = (doc_height - target_height) / 2
            
            # Create a group if requested
            if self.options.add_group:
                group = Group()
                group.set('id', self.svg.get_unique_id('ai-generated'))
                group.set('transform', f'translate({center_x}, {center_y})')
                
                # Import all children from parsed SVG
                for child in svg_root:
                    # Convert ET element to inkex element
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
                        # Add translation to existing transform if any
                        existing_transform = new_elem.get('transform', '')
                        if existing_transform:
                            new_elem.set('transform', f'translate({center_x}, {center_y}) {existing_transform}')
                        else:
                            new_elem.set('transform', f'translate({center_x}, {center_y})')
                        
                        self.svg.get_current_layer().append(new_elem)
        
        except ET.ParseError as e:
            inkex.errormsg(f"Failed to parse SVG code: {str(e)}\n\nReceived code:\n{svg_code[:500]}...")
            return
        except Exception as e:
            inkex.errormsg(f"Error adding SVG to document: {str(e)}")
            return
    
    def import_element(self, et_element):
        """Convert ElementTree element to Inkex element."""
        try:
            # Get the tag name without namespace
            tag = et_element.tag.split('}')[-1] if '}' in et_element.tag else et_element.tag
            
            # Map SVG elements to inkex elements
            element_map = {
                'rect': inkex.Rectangle,
                'circle': inkex.Circle,
                'ellipse': inkex.Ellipse,
                'line': inkex.Line,
                'polyline': inkex.Polyline,
                'polygon': inkex.Polygon,
                'path': inkex.PathElement,
                'text': inkex.TextElement,
                'g': inkex.Group
            }
            
            # Create appropriate inkex element
            if tag in element_map:
                elem_class = element_map[tag]
                new_elem = elem_class()
                
                # Copy all attributes
                for key, value in et_element.attrib.items():
                    new_elem.set(key, value)
                
                # Copy text content if any
                if et_element.text:
                    new_elem.text = et_element.text
                
                # Recursively add children for group elements
                if tag == 'g':
                    for child in et_element:
                        child_elem = self.import_element(child)
                        if child_elem is not None:
                            new_elem.append(child_elem)
                
                return new_elem
            else:
                # For unsupported elements, try to create generic element
                return None
        
        except Exception as e:
            inkex.errormsg(f"Warning: Could not import element {et_element.tag}: {str(e)}")
            return None


if __name__ == '__main__':
    OpenAISVGGenerator().run()



# "C:\Program Files\Inkscape\bin\python.exe" -m pip install certifi    