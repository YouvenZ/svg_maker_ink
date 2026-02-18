Collecting workspace information# SVG LLM Generator for Inkscape

[![Inkscape](https://img.shields.io/badge/Inkscape-1.0+-blue.svg)](https://inkscape.org/)
[![Python](https://img.shields.io/badge/Python-3.6+-green.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Generate SVG graphics using AI directly within Inkscape**

A powerful Inkscape extension that leverages multiple AI providers (OpenAI, Anthropic Claude, Google Gemini, and local Ollama) to generate scalable vector graphics from text descriptions.

---

## 📋 Table of Contents

- Features
- Requirements
- Installation
- Quick Start
- Usage Guide
- Configuration
- Provider Setup
- Customization
- Troubleshooting
- Contributing
- License

---

## ✨ Features

- **🤖 Multiple AI Providers**
  - **OpenAI**: GPT-4, GPT-4 Turbo, GPT-3.5
  - **Anthropic**: Claude 3.5 Sonnet, Claude 3 Opus
  - **Google**: Gemini 1.5 Flash, Gemini 1.5 Pro
  - **Ollama**: Local models (Llama, Mistral, etc.)

- **🎨 Rich Style Options**
  - Style presets (minimal, detailed, flat, outline, geometric, etc.)
  - Color schemes (monochrome, warm, cool, pastel, vibrant, etc.)
  - Complexity levels (simple, medium, complex)
  - Stroke style control

- **📐 Flexible Sizing**
  - Preset sizes (small, medium, large, xlarge)
  - Custom dimensions
  - Aspect ratios (square, landscape, portrait, widescreen, banner)

- **🎯 Smart Positioning**
  - Center, origin, or next to selection
  - Multiple variations side-by-side
  - Automatic grouping with custom names

- **⚙️ Advanced Features**
  - Selection context awareness
  - Prompt presets (icon, logo, diagram, pattern, etc.)
  - Gradient and animation support
  - Accessibility options (title/desc)
  - Prompt history tracking
  - Retry logic for reliability

---

## 📦 Requirements

| Component | Version | Purpose |
|-----------|---------|---------|
| **Inkscape** | 1.0+ | Vector graphics editor |
| **Python** | 3.6+ | Extension runtime |
| **Internet** | - | API access (except Ollama) |

### Optional for Local Generation

| Component | Purpose |
|-----------|---------|
| **Ollama** | Run AI models locally without API costs |

---

## 🚀 Installation

### Step 1: Locate Extensions Directory

| OS | Path |
|----|------|
| **Windows** | `C:\Users\[YourName]\AppData\Roaming\inkscape\extensions\` |
| **macOS** | `~/Library/Application Support/org.inkscape.Inkscape/config/inkscape/extensions/` |
| **Linux** | `~/.config/inkscape/extensions/` |

> 💡 **Tip:** In Inkscape: **Edit → Preferences → System** shows extensions path

### Step 2: Install Extension Files

1. **Create extension folder:**
   ```bash
   mkdir -p [extensions-directory]/svg_maker
   ```

2. **Copy files:**
   ```bash
   cp svg_llm.py [extensions-directory]/svg_maker/
   cp svg_llm.inx [extensions-directory]/svg_maker/
   ```

3. **Restart Inkscape**

### Step 3: Verify Installation

1. Open Inkscape
2. Go to **Extensions → Generate → SVG LLM Generator**
3. The extension dialog should appear

---

## 🎯 Quick Start

### Basic Example

1. Open Inkscape
2. Go to **Extensions → Generate → SVG LLM Generator**
3. Select a provider (e.g., OpenAI)
4. Enter your API key
5. Type a prompt: `A simple house icon with a chimney`
6. Click **Apply**

**Result:** An AI-generated SVG house icon appears on your canvas!

---

## 📖 Usage Guide

### Tab Overview

| Tab | Purpose |
|-----|---------|
| **Provider** | Select AI provider and enter API key |
| **Prompt** | Enter description and select presets |
| **Style** | Configure visual style and colors |
| **Size** | Set dimensions and aspect ratio |
| **Output** | Grouping, positioning, variations |
| **Advanced** | Temperature, tokens, retries, seed |
| **Help** | Quick reference and tips |

### Prompt Tab Options

| Option | Description |
|--------|-------------|
| **Prompt** | Text description of desired SVG |
| **Preset** | Quick templates (icon, logo, diagram, etc.) |
| **Use Selection Context** | Match style of selected elements |

### Style Tab Options

| Option | Values | Description |
|--------|--------|-------------|
| **Style Hint** | minimal, detailed, flat, outline, geometric, organic, hand_drawn, isometric, cartoon | Visual style |
| **Color Scheme** | any, monochrome, warm, cool, pastel, vibrant, grayscale, earth, neon | Color palette |
| **Complexity** | simple, medium, complex | Detail level |
| **Stroke Style** | any, thin, medium, thick, none | Line thickness |

### Size Tab Options

| Option | Values |
|--------|--------|
| **Size** | small (200px), medium (400px), large (600px), xlarge (800px), custom |
| **Aspect Ratio** | square, landscape (4:3), portrait (3:4), widescreen (16:9), banner (3:1) |
| **Custom Width/Height** | Any pixel value |

### Output Tab Options

| Option | Description |
|--------|-------------|
| **Add Group** | Wrap generated SVG in a group |
| **Group Name** | Custom identifier for the group |
| **Position** | center, origin (0,0), selection (next to selected) |
| **Variations** | Generate 1-4 different interpretations |
| **Include Gradients** | Allow gradient fills |
| **Include Animations** | Add CSS/SMIL animations |
| **Add Accessibility** | Include title/desc elements |

---

## ⚙️ Configuration

### API Key Management

Three ways to provide API keys (in priority order):

#### 1. Direct Input (Temporary)
Enter key directly in the Provider tab each time.

#### 2. Save for Future Use (Recommended)
1. Enter API key in Provider tab
2. Check **"Save API key"**
3. Key is stored in `.config.json`

#### 3. Config File (Manual)

Edit `.config.json` in the extension directory:

```json
{
    "api_keys": {
        "openai": "sk-your-openai-key",
        "anthropic": "sk-ant-your-anthropic-key",
        "google": "your-google-api-key"
    },
    "last_provider": "openai"
}
```

### Prompt History

The extension automatically saves your prompts to `.svg_llm_history.json`:

```json
[
    {
        "prompt": "A simple house icon",
        "timestamp": "2024-01-15T10:30:00",
        "width": 400,
        "height": 400,
        "provider": "openai",
        "model": "gpt-4-turbo",
        "style": "minimal",
        "color_scheme": "any"
    }
]
```

---

## 🔌 Provider Setup

### OpenAI

1. Get API key from [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. Select provider: **openai**
3. Recommended models: `gpt-4-turbo`, `gpt-4o`, `gpt-3.5-turbo`

### Anthropic Claude

1. Get API key from [console.anthropic.com](https://console.anthropic.com/)
2. Select provider: **anthropic**
3. Recommended models: `claude-3-5-sonnet-20241022`, `claude-3-opus-20240229`

### Google Gemini

1. Get API key from [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Select provider: **google**
3. Recommended models: `gemini-1.5-flash`, `gemini-1.5-pro`

### Ollama (Local)

1. Install Ollama from [ollama.com](https://ollama.com/)
2. Pull a model:
   ```bash
   ollama pull llama3.1
   ```
3. Start Ollama:
   ```bash
   ollama serve
   ```
4. Select provider: **ollama**
5. No API key needed!

---

## 🔧 Customization

### Changing Default Settings

Edit the class constants in svg_llm.py:

```python
class SVGLLMGenerator(inkex.EffectExtension):
    CONFIG_FILENAME = '.config.json'      # Config file name
    HISTORY_FILENAME = '.svg_llm_history.json'  # History file name
    MAX_HISTORY = 50                       # Max history entries
```

### Adding Custom Presets

Add new presets in the `build_prompt` method:

```python
preset_prompts = {
    'icon': "Create a simple, recognizable icon...",
    'illustration': "Create an artistic illustration...",
    # Add your custom preset:
    'scientific': "Create a scientific diagram with labels and annotations...",
}
```

### Custom Style Descriptions

Modify style descriptions in `build_prompt`:

```python
style_descriptions = {
    'minimal': 'Use a minimal, clean design...',
    # Add custom style:
    'blueprint': 'Use technical blueprint style with white lines on blue background...',
}
```

### Custom Color Schemes

Add color schemes in `build_prompt`:

```python
color_descriptions = {
    'monochrome': 'Use only one color...',
    # Add custom scheme:
    'synthwave': 'Use synthwave/retrowave colors (pink, cyan, purple on dark)...',
}
```

### Modifying the System Prompt

Edit the system message in API call methods:

```python
def call_openai_api(self, prompt, api_key):
    # ...
    data = {
        'messages': [
            {
                'role': 'system',
                'content': 'Your custom system prompt here...'
            },
            # ...
        ]
    }
```

---

## 🐛 Troubleshooting

### Common Issues

<details>
<summary><b>Extension not appearing in menu</b></summary>

**Solutions:**
1. Verify files are correctly placed:
   ```bash
   ls [extensions-directory]/svg_maker/
   # Should show: svg_llm.py, svg_llm.inx
   ```
2. Check file permissions (Linux/macOS):
   ```bash
   chmod +x svg_llm.py
   ```
3. Restart Inkscape completely
4. Check Inkscape error log: **Edit → Preferences → System → Open Error Log**

</details>

<details>
<summary><b>API Key Error</b></summary>

**Error:** `Please provide a valid API key for [provider]`

**Solutions:**
1. Verify API key is correct (no extra spaces)
2. Check API key has proper permissions
3. Ensure API key is not expired
4. For Ollama: No key needed, ensure server is running

</details>

<details>
<summary><b>Network/Connection Error</b></summary>

**Error:** `Network Error: ...`

**Solutions:**
1. Check internet connection
2. Verify firewall isn't blocking requests
3. For Ollama: Ensure `ollama serve` is running
4. Try increasing timeout in Advanced tab

</details>

<details>
<summary><b>Invalid SVG Generated</b></summary>

**Error:** `Failed to parse SVG code: ...`

**Solutions:**
1. Try a different model (GPT-4 tends to be more reliable)
2. Simplify your prompt
3. Reduce complexity setting
4. Enable "Optimize paths" option
5. Try with a different provider

</details>

<details>
<summary><b>Ollama Connection Failed</b></summary>

**Error:** `Cannot connect to Ollama`

**Solutions:**
1. Start Ollama server:
   ```bash
   ollama serve
   ```
2. Verify Ollama is running:
   ```bash
   curl http://localhost:11434/api/tags
   ```
3. Check custom endpoint URL if not using default
4. Pull a model if none installed:
   ```bash
   ollama pull llama3.1
   ```

</details>

### Debug Tips

1. **Check error log:** **Edit → Preferences → System → Open Error Log**
2. **Test API independently:** Use curl or Postman to verify API access
3. **Start simple:** Test with basic prompts before complex ones
4. **Check history:** Review `.svg_llm_history.json` for past successful prompts

---

## 📁 File Structure

```
svg_maker/
├── svg_llm.py              # Main extension code
├── svg_llm.inx             # Inkscape extension definition
├── README.md               # This file
├── LICENSE                 # MIT License
├── .config.json            # Saved API keys (auto-created)
└── .svg_llm_history.json   # Prompt history (auto-created)
```

---

## 💡 Tips & Best Practices

### Prompt Writing Tips

1. **Be specific:** "A red apple with a leaf" > "an apple"
2. **Mention style:** "flat design icon of..." or "detailed illustration of..."
3. **Specify colors:** "using blue and orange colors"
4. **Define complexity:** "simple/minimal" or "detailed/intricate"

### Performance Tips

1. **Use presets:** They include optimized instructions
2. **Start with medium complexity:** Adjust based on results
3. **Lower temperature for consistency:** 0.3-0.5 for predictable results
4. **Higher temperature for creativity:** 0.8-1.0 for variety

### Quality Tips

1. **GPT-4 models produce best SVG:** More reliable than GPT-3.5
2. **Claude excels at complex diagrams:** Good for flowcharts
3. **Gemini is fast and affordable:** Good for simple icons
4. **Local Ollama varies by model:** llama3.1 recommended

---

## 🤝 Contributing

Contributions are welcome!

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/new-provider`)
3. Commit changes (`git commit -m 'Add new AI provider'`)
4. Push to branch (`git push origin feature/new-provider`)
5. Open a Pull Request

**Development Setup:**
```bash
git clone https://github.com/YouvenZ/svg_maker_ink.git
cd svg_maker_ink
# Symlink for testing
ln -s $(pwd) ~/.config/inkscape/extensions/svg_maker
```

---

## 📄 License

This project is licensed under the MIT License - see LICENSE file for details.

---

## 📧 Support

- **Issues**: [GitHub Issues](https://github.com/YouvenZ/svg_maker_ink/issues)
- **Discussions**: [GitHub Discussions](https://github.com/YouvenZ/svg_maker_ink/discussions)
- **Email**: youvenz.pro@gmail.com

---

## 🙏 Acknowledgments

- Built on [Inkscape Extension API](https://inkscape.gitlab.io/extensions/documentation/)
- Powered by [OpenAI](https://openai.com/), [Anthropic](https://anthropic.com/), [Google](https://ai.google.dev/), and [Ollama](https://ollama.com/)
- Inspired by the need for AI-assisted vector graphics creation

---

## 🔄 Changelog

### v1.0.0 (2024)
- ✨ Initial release
- ✅ OpenAI, Anthropic, Google, Ollama support
- ✅ Multiple style and color options
- ✅ Flexible sizing with aspect ratios
- ✅ Selection context awareness
- ✅ Multiple variations generation
- ✅ Prompt history tracking
- ✅ API key persistence
- ✅ Retry logic for reliability