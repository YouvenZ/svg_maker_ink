#!/usr/bin/env python3
"""
Prompt loader for the AI SVG Generator extension.

Reads prompt text from Markdown files in {extension_dir}/prompts/.
Falls back to hardcoded defaults when a file is missing so the extension
always works — even if the prompts/ directory is absent.

File layout
-----------
prompts/
  system_prompt.md          ← default LLM system prompt
  presets/icon.md           ← one file per preset name
  presets/illustration.md
  …
  styles/minimal.md         ← one file per style name
  …
  colors/monochrome.md      ← one file per colour-scheme name
  …
  complexity/simple.md      ← one file per complexity level
  …
  strokes/thin.md           ← one file per stroke-style name
  …

Format
------
Each file may optionally begin with a YAML front-matter block (--- … ---).
The front-matter is stripped; only the text that follows is sent to the model.
"""

import os
import re


class PromptLoader:
    """Load prompt fragments from markdown files; fall back to built-in defaults."""

    # ── Hard-coded defaults ────────────────────────────────────────────────
    DEFAULTS: dict = {
        'system_prompt': (
            "You are an expert SVG code generator. "
            "You only respond with valid, clean SVG code "
            "without any explanation or markdown formatting. "
            "Never include ```svg or ``` markers. "
            "Always produce well-formed, valid SVG that follows the W3C SVG specification."
        ),
        'presets': {
            'icon': (
                "Create a simple, recognizable icon suitable for UI/UX design. "
                "Use clear, bold shapes with minimal detail. "
                "The icon should be immediately understandable at small sizes."
            ),
            'illustration': (
                "Create an artistic illustration with visual appeal and appropriate detail. "
                "Use a balanced composition with clear focal points and a pleasing color harmony."
            ),
            'diagram': (
                "Create a clear, informative diagram with proper labels and logical connections. "
                "Use consistent visual language for nodes, edges, and annotations."
            ),
            'pattern': (
                "Create a seamless repeating pattern that tiles correctly in all four directions. "
                "Ensure the edges match perfectly so there are no visible seams when tiled."
            ),
            'logo': (
                "Create a professional, scalable logo design that is memorable and versatile. "
                "Keep it clean and bold so it reads clearly at any size."
            ),
            'flowchart': (
                "Create a flowchart with clearly labeled rectangles for processes, "
                "diamonds for decisions, rounded rectangles for start/end, "
                "and arrows showing the flow direction."
            ),
            'infographic': (
                "Create an informative graphic with data-visualization elements, "
                "icons, and callouts. Balance text and visuals for maximum clarity."
            ),
        },
        'styles': {
            'minimal': (
                "Use a minimal, clean design with simple shapes and generous whitespace. "
                "Remove anything that is not essential."
            ),
            'detailed': (
                "Include rich, detailed elements with textures and visual complexity. "
                "Layer shapes to create depth and interest."
            ),
            'flat': (
                "Use flat design principles: solid colors, no shadows, no gradients, "
                "simple geometric shapes, and clean typography if text is used."
            ),
            'outline': (
                "Use only outlines and strokes — no fills. Pure line art style. "
                "Vary stroke width to suggest depth."
            ),
            'filled': (
                "Use filled shapes with no or minimal strokes. "
                "Let color and shape define all forms."
            ),
            'geometric': (
                "Use only geometric shapes (circles, rectangles, triangles, polygons). "
                "All forms should be precise and angular."
            ),
            'organic': (
                "Use organic, natural flowing curves and irregular shapes. "
                "Avoid anything perfectly geometric or mechanical."
            ),
            'hand_drawn': (
                "Give it a hand-drawn, sketchy appearance. "
                "Use slightly imperfect lines, visible stroke variation, "
                "and a loose, gestural quality."
            ),
            'isometric': (
                "Use isometric 3D perspective. "
                "All receding edges follow 30-degree angles from horizontal. "
                "Top, left, and right faces use distinct shading."
            ),
            'cartoon': (
                "Use a cartoon/comic style with bold outlines, flat colors, "
                "and expressive, slightly exaggerated forms."
            ),
        },
        'colors': {
            'monochrome': (
                "Use only one hue in a range of shades, tints, and tones. "
                "Vary lightness to create contrast and hierarchy."
            ),
            'warm': (
                "Use warm colors exclusively: reds, oranges, yellows, "
                "and warm browns or beiges. No cool hues."
            ),
            'cool': (
                "Use cool colors exclusively: blues, greens, purples, "
                "and teals. No warm hues."
            ),
            'pastel': (
                "Use soft pastel colors with low saturation and high lightness. "
                "Delicate, airy, and gentle."
            ),
            'vibrant': (
                "Use bright, fully saturated, vibrant colors. "
                "High contrast between elements."
            ),
            'grayscale': (
                "Use only black, white, and shades of gray. "
                "No hue whatsoever."
            ),
            'earth': (
                "Use earthy, natural tones: warm browns, olive greens, "
                "sandy beiges, terracotta, and muted ochres."
            ),
            'neon': (
                "Use bright neon/fluorescent colors (electric blues, hot pinks, "
                "lime greens, vivid oranges) against a dark background."
            ),
            'complementary': (
                "Use two complementary colors (opposite on the color wheel) "
                "and their tints/shades for all elements."
            ),
        },
        'complexity': {
            'simple': (
                "Use minimal elements and basic shapes only. "
                "Maximum 10–15 SVG elements in total."
            ),
            'medium': (
                "Use moderate complexity with some detail. "
                "Target around 20–40 SVG elements."
            ),
            'complex': (
                "Include rich detail, many elements, layering, "
                "and intricate design work."
            ),
        },
        'strokes': {
            'thin': "Use thin strokes throughout (stroke-width 1–2 px).",
            'medium': "Use medium strokes throughout (stroke-width 2–4 px).",
            'thick': "Use thick, bold strokes throughout (stroke-width 4–8 px).",
            'none': "Do NOT use any strokes. Filled shapes only, no outlines.",
            'variable': (
                "Use variable stroke widths — thicker for emphasis and outer edges, "
                "thinner for inner details."
            ),
        },
    }

    # ── Constructor ────────────────────────────────────────────────────────

    def __init__(self, extension_dir: str):
        self._base = os.path.join(extension_dir, 'prompts')
        self._cache: dict[str, str] = {}

    # ── Private helpers ────────────────────────────────────────────────────

    def _read(self, *path_parts: str) -> str | None:
        """
        Read a file at prompts/{path_parts}.md, strip YAML front-matter,
        return the body text. Returns None if the file is missing or empty.
        Results are cached after the first read.
        """
        key = '/'.join(path_parts)
        if key in self._cache:
            return self._cache[key] or None

        # Build path (append .md if not already present)
        filepath = os.path.join(self._base, *path_parts)
        if not filepath.endswith('.md'):
            filepath += '.md'

        try:
            with open(filepath, 'r', encoding='utf-8') as fh:
                raw = fh.read()
        except (FileNotFoundError, OSError):
            self._cache[key] = ''
            return None

        # Strip YAML front-matter (--- … ---)
        stripped = raw.strip()
        if stripped.startswith('---'):
            end_idx = stripped.find('\n---', 3)
            if end_idx != -1:
                stripped = stripped[end_idx + 4:].strip()

        self._cache[key] = stripped
        return stripped or None

    # ── Public API ─────────────────────────────────────────────────────────

    def get_system_prompt(self) -> str:
        return self._read('system_prompt') or self.DEFAULTS['system_prompt']

    def get_preset(self, name: str) -> str:
        return self._read('presets', name) or self.DEFAULTS['presets'].get(name, '')

    def get_style(self, name: str) -> str:
        return self._read('styles', name) or self.DEFAULTS['styles'].get(name, '')

    def get_color(self, name: str) -> str:
        return self._read('colors', name) or self.DEFAULTS['colors'].get(name, '')

    def get_complexity(self, name: str) -> str:
        return self._read('complexity', name) or self.DEFAULTS['complexity'].get(name, '')

    def get_stroke(self, name: str) -> str:
        return self._read('strokes', name) or self.DEFAULTS['strokes'].get(name, '')
