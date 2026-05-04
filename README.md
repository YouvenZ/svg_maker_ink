<div align="center">

# AI SVG Generator for Inkscape

[![Inkscape](https://img.shields.io/badge/Inkscape-1.0+-blue.svg)](https://inkscape.org/)
[![Python](https://img.shields.io/badge/Python-3.6+-green.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Generate stunning Scalable Vector Graphics using AI directly within Inkscape, powered by a modern Web GUI.**

A powerful Inkscape extension that leverages cutting-edge AI providers (OpenAI, Anthropic Claude, Google Gemini, Local Ollama, and OpenRouter/Custom Servers) to generate beautiful vector graphics from text descriptions, directly onto your canvas.

</div>

## 📺 Demo

<div align="center">

[![Watch the Demo](https://img.youtube.com/vi/z-PGFjJGexs/maxresdefault.jpg)](https://www.youtube.com/watch?v=z-PGFjJGexs)

*Click to watch the full tutorial on YouTube*

</div>


---

## ✨ Features Highlight

- **💻 Stunning Native GTK Web UI**
  - Modern, responsive **Dark Mode** interface wrapped in GTK WebKit.
  - Generates images asynchronously in the background so Inkscape never freezes.
  - Tabbed interface separating *Generation*, *Setup & Model*, *Layout & Style*, and *History*.
  - **Auto-Save:** Settings are instantly remembered and persisted across sessions as you type!

- **🤖 Universal AI Provider Support**
  - **OpenAI**: Native support for GPT-4o, o1, etc.
  - **Anthropic**: Claude 3.5 Sonnet, Haiku, Opus.
  - **Google**: Gemini 1.5 Pro, Flash.
  - **Ollama**: Connect seamlessly to your local models for zero-cost generation.
  - **OpenAI Compatible (Custom Profiles)**: Perfect for **OpenRouter**, **LM Studio**, **LocalAI**, or **vLLM**. Store unlimited isolated profiles (e.g., separate OpenRouter and LM Studio profiles within the same extension).
  - *Smart Auto-Patching:* Automatically fixes OpenRouter authentication headers and prefixes.

- **⚡ Dynamic Model Management**
  - Intelligently sync models across any API endpoint.
  - Autocomplete & search model names effortlessly via dynamic `<datalist>` filtering.
  - Alphabetically sorted model lists.

- **🕰️ Smart Prompt History**
  - Keep track of every iteration! The extension logs your session automatically to `svg_llm_history.json`.
  - Filter your history with live search.
  - One-click restore to inject past prompts, providers, and models directly back into the creation engine.

- **📐 Smart Embedding & Context**
  - Produce **1 to 4 Variations** concurrently.
  - Decide exact **Insertion Position**: Page Center, Origin (0,0), or smartly drop it **Beside your currently Selected Object**.
  - **Context-Aware Selection**: Pass the boundary Box & attributes of currently selected vector elements to guide the AI!

- **🎨 Advanced Styling Engine**
  - Aesthetic control: Choose preset color palettes (Vibrant, Pastel, Monochrome) or Stroke profiles.
  - Generate Gradients, Animations (SMIL/CSS), Accessibility tags, and mathematically optimized paths.

---

## 📦 Installation

### Step 1: Locate your Inkscape Extensions Directory

| OS | Default Path |
|----|--------------|
| **Windows** | `C:\Users\[YourName]\AppData\Roaming\inkscape\extensions\` |
| **macOS** | `~/Library/Application Support/org.inkscape.Inkscape/config/inkscape/extensions/` |
| **Linux** | `~/.config/inkscape/extensions/` |

> 💡 **Tip:** Inside Inkscape: **Edit → Preferences → System** shows the exact extensions path.

### Step 2: Install Extension Files

1. **Create the extension folder:**
   ```bash
   mkdir -p [extensions-directory]/svg_maker
   ```

2. **Copy the extracted files & folders into it:**
   ```bash
   cp svg_llm.py [extensions-directory]/svg_maker/
   cp svg_llm.inx [extensions-directory]/svg_maker/
   cp -r ui/ [extensions-directory]/svg_maker/
   ```

3. **Restart Inkscape** entirely.

---

## 🚀 Quick Start Guide

1. Open Inkscape and create a new document.
2. Go to **Extensions → Generate → AI SVG Generator**.
3. **Setup Tab**:
   - Choose your provider (e.g., Anthropic or OpenAI Compatible).
   - Enter your API Key.
   - Click **Sync** to fetch available text-to-vector models dynamically, or type it manually.
4. **Generator Tab**:
   - Write a prompt like: `A sleek, geometric sticker style of a BMW car`.
   - Hit **Generate Vector**.
5. The UI progress bar will show connection stats in real-time. Once finished, the vectors are drawn live on your Canvas!

---

## ⚙️ Configuration details

By dropping the archaic Inkscape pop-ups, the extension now purely self-manages its data using JSON structures saved transparently to its local folder.

*   `config.json` => Stores your API keys, UI settings, default dimensions, insertion positions, and dynamically handles multiple custom profile endpoints.
*   `svg_llm_history.json` => Records your timestamps, prompts, and applied generation logic.

> 🔒 *Security Note*: Your API keys are saved directly locally onto your machine's `config.json` via the web UI and never sync anywhere except the model provider endpoints.

---

## 🤝 Contributing / Upstream

This powerful AI generator represents a massive UI, UX, and Pipeline overhaul originally built upon the [inkscape extension framework](https://inkscape.gitlab.io/extensions/documentation/).

Contributions are welcome!
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/new-idea`)
3. Commit changes (`git commit -m 'Implement amazing update'`)
4. Push to branch (`git push origin feature/new-idea`)
5. Open a Pull Request!

---

## 📄 License

This software is provided under the **MIT License**.
Original Upstream Copyright (c) 2026 Rachid, Youven ZEGHLACHE.
See the `LICENSE` file for more details.