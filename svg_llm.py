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
import http.server
import socketserver
import webbrowser
import threading
import socket
import gi
try:
    gi.require_version('Gtk', '3.0')
    gi.require_version('WebKit2', '4.1')
    from gi.repository import Gtk, WebKit2, GLib
    GTK_UI_AVAILABLE = True
except (ImportError, ValueError):
    try:
        gi.require_version('WebKit2', '4.0')
        from gi.repository import Gtk, WebKit2, GLib
        GTK_UI_AVAILABLE = True
    except:
        GTK_UI_AVAILABLE = False

try:
    import webview
    WEBVIEW_AVAILABLE = True
except (ImportError, ValueError):
    WEBVIEW_AVAILABLE = False

import sys
# Redirect all stderr to a log file to suppress Inkscape's annoying log dialog and GTK warnings
log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'svg_maker.log')
log_file = open(log_path, 'w')
os.dup2(log_file.fileno(), sys.stderr.fileno())

class SVGLLMGenerator(inkex.EffectExtension):
    """Extension to generate SVG using various LLM providers."""
    
    CONFIG_FILENAME = 'config.json'
    HISTORY_FILENAME = 'svg_llm_history.json'
    MAX_HISTORY = 50
    
    PROVIDERS = {
        'openai': {
            'name': 'OpenAI DALL-E',
            'env_key': 'OPENAI_API_KEY',
            'config_key': 'openai_api_key',
            'models': ['gpt-4o', 'gpt-4-turbo', 'gpt-4', 'gpt-3.5-turbo'],
        },
        'anthropic': {
            'name': 'Anthropic Claude',
            'env_key': 'ANTHROPIC_API_KEY',
            'config_key': 'anthropic_api_key',
            'models': ['claude-3-5-sonnet-20241022', 'claude-3-opus-20240229', 'claude-3-sonnet-20240229', 'claude-3-haiku-20240307'],
        },
        'google': {
            'name': 'Google Gemini',
            'env_key': 'GEMINI_API_KEY',
            'config_key': 'google_api_key',
            'models': ['gemini-1.5-pro', 'gemini-1.5-flash', 'gemini-1.0-pro'],
        },
        'ollama': {
            'name': 'Ollama (Local)',
            'env_key': '',
            'config_key': '',
            'models': ['llama3.1', 'llama3', 'mistral', 'codellama'],
        },
        'openai_compatible': {
            'name': 'OpenAI Compatible',
            'env_key': '',
            'config_key': '',
            'models': ['custom'],
        }
    }

    class WebUIHandler(http.server.SimpleHTTPRequestHandler):
        """Handler for the Web UI."""
        
        def __init__(self, *args, extension_instance=None, **kwargs):
            self.extension_instance = extension_instance
            super().__init__(*args, **kwargs)

        def log_message(self, format, *args):
            # Silence logging
            pass

        def do_GET(self):
            if self.path == '/get-settings':
                # ... existing logic ...
                config = self.extension_instance.config
                provider = config.get('last_provider', self.extension_instance.options.provider or "openai")
                
                
                settings = {
                    'provider': provider,
                    'provider_settings': config.get('provider_settings', {}),
                    'custom_profiles': config.get('custom_profiles', []),
                    'prompt': self.extension_instance.options.prompt or "",
                    'variations': self.extension_instance.options.variations or 1,
                    'size': config.get('layout_settings', {}).get('size', self.extension_instance.options.size or "512x512"),
                    'aspect_ratio': config.get('layout_settings', {}).get('aspect_ratio', self.extension_instance.options.aspect_ratio or "1:1"),
                    'retry_count': config.get('layout_settings', {}).get('retry_count', self.extension_instance.options.retry_count or 2),
                    'temperature': config.get('layout_settings', {}).get('temperature', self.extension_instance.options.temperature or 0.7),
                    'position': config.get('layout_settings', {}).get('position', self.extension_instance.options.position or "center"),
                    'use_selection_context': config.get('layout_settings', {}).get('use_selection_context', self.extension_instance.options.use_selection_context or False),
                    'available_models': {k: v['models'] for k, v in self.extension_instance.PROVIDERS.items()}
                }
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(settings).encode('utf-8'))
            elif self.path == '/status':
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(self.extension_instance.status_data).encode('utf-8'))
            elif self.path == '/heartbeat':
                import time
                self.extension_instance.last_heartbeat = time.time()
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'alive'}).encode('utf-8'))
            elif self.path == '/get-history':
                history = self.extension_instance.load_history()
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(history).encode('utf-8'))
                
            else:
                super().do_GET()

        def do_POST(self):
            if self.path == '/submit':
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                # Extract data for debugging
                with open(os.path.join(os.path.dirname(__file__), "debug_submit.log"), "w") as f:
                    json.dump(data, f, indent=2)

                # Start generation in a background thread
                threading.Thread(target=self.extension_instance.perform_generation, args=(data,)).start()
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'started'}).encode('utf-8'))
                
            elif self.path == '/save-settings':
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                
                # Update config without closing UI
                self.extension_instance.update_config_from_ui(data)
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'saved'}).encode('utf-8'))
                
            elif self.path == '/clear-history':
                self.extension_instance.clear_history()
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'cleared'}).encode('utf-8'))
                
            elif self.path == '/close':
                # Shut down safely
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'closing'}).encode('utf-8'))
                
                bg = getattr(self.extension_instance, 'active_backend', None)
                if bg == 'gtk':
                    from gi.repository import GLib, Gtk
                    GLib.idle_add(Gtk.main_quit)
                elif bg == 'webview':
                    try: self.extension_instance.webview_window.destroy()
                    except: pass
                
            elif self.path == '/sync-models':
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                params = json.loads(post_data.decode('utf-8'))
                
                try:
                    # Temporary hijack the instance options to run sync
                    orig_options = self.extension_instance.options
                    
                    # Create a temporary object that mimics the options needed for sync
                    class TempOptions:
                        def __init__(self, p, e, k):
                            self.provider = p
                            self.api_endpoint = e
                            self.api_key = k
                            self.save_api_key = False
                    
                    self.extension_instance.options = TempOptions(params.get('provider'), params.get('api_endpoint'), params.get('api_key'))
                    
                    # We need to fetch models without updating the .inx file
                    # Let's extract the fetching logic or use a modified sync method
                    # For now, I'll just return some defaults as proof of concept if I don't want to refactor yet,
                    # but I should try to make it work.
                    
                    # Implementation of fetching logic (simplified from sync_models_from_provider)
                    models = []
                    provider = params.get('provider')
                    api_key = params.get('api_key') or self.extension_instance.get_api_key()
                    
                    provider_type = 'openai_compatible' if provider and provider.startswith('custom_') else provider
                    
                    ssl_context = ssl._create_unverified_context()
                    
                    if provider_type == 'openai' or provider_type == 'openai_compatible':
                        url = "https://api.openai.com/v1/models"
                        if provider_type == 'openai_compatible':
                            endpoint = params.get('api_endpoint') or "http://localhost:1234/v1"
                            url = endpoint.rstrip('/') + "/models"
                        
                        headers = {'Authorization': f'Bearer {api_key}'}
                        req = urllib.request.Request(url, headers=headers, method='GET')
                        with urllib.request.urlopen(req, timeout=10, context=ssl_context) as response:
                            result = json.loads(response.read().decode('utf-8'))
                            models = [m['id'] for m in result.get('data', []) if 'gpt' in m['id'] or 'o1-' in m['id'] or 'o3-' in m['id'] or provider_type == 'openai_compatible']
                    
                    elif provider_type == 'ollama':
                        endpoint = params.get('api_endpoint') or "http://localhost:11434"
                        url = f"{endpoint}/api/tags"
                        with urllib.request.urlopen(url, timeout=10, context=ssl_context) as response:
                            result = json.loads(response.read().decode('utf-8'))
                            models = [m['name'] for m in result.get('models', [])]
                            
                    elif provider_type == 'google':
                        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
                        with urllib.request.urlopen(url, timeout=10, context=ssl_context) as response:
                            result = json.loads(response.read().decode('utf-8'))
                            # Filter for gemini models that end with 'models/gemini-*' and extract base name
                            models = [m['name'].split('/')[-1] for m in result.get('models', []) if 'gemini' in m['name']]
                            
                    elif provider_type == 'anthropic':
                        # Anthropic doesn't have a public /models endpoint yet, return hardcoded current models
                        models = self.extension_instance.PROVIDERS['anthropic']['models']
                    
                    self.extension_instance.options = orig_options # Restore
                    
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'models': models}).encode('utf-8'))
                    
                except Exception as e:
                    self.send_response(500)
                    self.send_header('Content-type', 'text/plain')
                    self.end_headers()
                    self.wfile.write(str(e).encode('utf-8'))



    def __init__(self):
        super().__init__()
        self.config_path = os.path.join(os.path.dirname(__file__), self.CONFIG_FILENAME)
        self.history_path = os.path.join(os.path.dirname(__file__), self.HISTORY_FILENAME)
        self.web_ui_data = None
        self.config = self.load_config()
        
        # Apply saved configuration to options
        if self.config.get('last_provider'):
            self.options.provider = self.config['last_provider']
            
            # Load endpoint and manual model for the last provider from new structure
            provider_data = self.config.get('provider_settings', {}).get(self.options.provider, {})
            if 'api_endpoint' in provider_data:
                self.options.api_endpoint = provider_data['api_endpoint']
            if 'manual_model_name' in provider_data:
                self.options.manual_model_name = provider_data['manual_model_name']
            if 'model' in provider_data:
                self.options.model = provider_data['model']
            
        layout = self.config.get('layout_settings', {})
        if layout.get('size'):
            self.options.size = layout['size']
        if layout.get('aspect_ratio'):
            self.options.aspect_ratio = layout['aspect_ratio']
        
        # Initialize status for async feedback
        self.status_data = {"status": "idle", "progress": 0, "message": ""}
        self.is_processing = False

    def run_web_ui(self):
        """Start a local server and open the Web UI in a native GTK window."""
        # Find a free port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            port = s.getsockname()[1]
        
        ui_dir = os.path.join(os.path.dirname(__file__), 'ui')
        
        # Create the server
        handler_class = lambda *args, **kwargs: self.WebUIHandler(
            *args, extension_instance=self, directory=ui_dir, **kwargs
        )
        
        server = socketserver.TCPServer(("", port), handler_class)
        # Start server in a thread so GTK can run its main loop
        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.daemon = True
        server_thread.start()
        
        url = f"http://localhost:{port}/index.html"
        
        ui_pref = self.config.get('ui_backend', 'auto')
        
        use_gtk = False
        use_webview = False
        
        if ui_pref == 'gtk' and GTK_UI_AVAILABLE:
            use_gtk = True
        elif ui_pref == 'webview' and WEBVIEW_AVAILABLE:
            use_webview = True
        elif ui_pref == 'browser':
            pass
        elif ui_pref == 'auto':
            if GTK_UI_AVAILABLE:
                use_gtk = True
            elif WEBVIEW_AVAILABLE:
                use_webview = True

        if use_gtk:
            self.active_backend = 'gtk'
            from gi.repository import GLib, Gtk
            # Add a heartbeat to keep the GTK main loop "alive" during background tasks
            # This prevents the OS from marking the window as "Not Responding"
            heartbeat_id = GLib.timeout_add(100, lambda: True)
            
            # Run GTK native window
            GLib.idle_add(self._launch_gtk_window, url, server)
            Gtk.main()
            
            # Cleanup heartbeat
            GLib.source_remove(heartbeat_id)
        elif use_webview:
            self.active_backend = 'webview'
            self.webview_window = webview.create_window('AI SVG Generator', url, width=650, height=800, resizable=True)
            webview.start()
            self.status_data['status'] = 'closed'
        else:
            import time
            import subprocess
            self.last_heartbeat = time.time()
            start_time = time.time()
            
            app_launched = False
            self.app_process = None
            browser_paths = [
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
            ]
            
            if os.name == 'nt':
                for b_path in browser_paths:
                    if os.path.exists(b_path):
                        try:
                            self.app_process = subprocess.Popen([b_path, f"--app={url}", "--window-size=650,800"])
                            app_launched = True
                            self.active_backend = 'app'
                            break
                        except Exception as e:
                            with open(log_path, 'a') as f:
                                f.write(f"Failed to launch browser app: {e}\n")
                            pass
            
            if not app_launched:
                self.active_backend = 'browser'
                webbrowser.open(url)
                
            while self.is_processing or self.status_data.get('status') == 'idle':
                time.sleep(0.5)
                # Auto kill server if UI hangs
                if time.time() - self.last_heartbeat > 3.0 and time.time() - start_time > 15.0:
                    self.status_data['status'] = 'closed'
                    break

            if app_launched and self.app_process:
                try: self.app_process.terminate()
                except: pass
        
        server.server_close()
        return self.web_ui_data

    def _launch_gtk_window(self, url, server):
        window = Gtk.Window(title="AI SVG Generator")
        window.set_default_size(650, 800)
        window.set_position(Gtk.WindowPosition.CENTER)
        
        webview = WebKit2.WebView()
        window.add(webview)
        webview.load_uri(url)
        
        def on_destroy(widget):
            server.shutdown()
            Gtk.main_quit()
            
        window.connect("destroy", on_destroy)
        window.show_all()

    def get_config_value(self, key, default=None):
        """Helper to get value from config with fallback."""
        if hasattr(self, 'config') and self.config:
            return self.config.get(key, default)
        return default

    def update_config_from_ui(self, data):
        """Update extension options and persistent config from UI data."""
        # Update current options
        for key, value in data.items():
            if hasattr(self.options, key):
                orig_val = getattr(self.options, key)
                try:
                    if isinstance(orig_val, bool):
                        setattr(self.options, key, str(value).lower() == 'true')
                    elif isinstance(orig_val, int):
                        setattr(self.options, key, int(value))
                    elif isinstance(orig_val, float):
                        setattr(self.options, key, float(value))
                    else:
                        setattr(self.options, key, value)
                except:
                    setattr(self.options, key, value)
        
        # Update persistent config
        config = self.load_config()
        
        # Save Provider specifics
        provider = data.get('provider')
        if provider:
            config['last_provider'] = provider
            if 'provider_settings' not in config: config['provider_settings'] = {}
            if provider not in config['provider_settings']: config['provider_settings'][provider] = {}
            
            p_data = config['provider_settings'][provider]
            if 'api_key' in data: p_data['api_key'] = data.get('api_key')
            if 'model' in data: p_data['model'] = data.get('model')
            if 'api_endpoint' in data: p_data['api_endpoint'] = data.get('api_endpoint')
            if 'manual_model_name' in data: p_data['manual_model_name'] = data.get('manual_model_name')
            
            # Handle custom profiles from UI
            if 'custom_profiles' in data:
                config['custom_profiles'] = data['custom_profiles']
            
            # Save any other profiles sent (UI handles syncing them)
            if 'provider_settings' in data:
                config['provider_settings'] = data['provider_settings']
        
        # Save Layout Styles
        if 'layout_settings' not in config: config['layout_settings'] = {}
        layout = config['layout_settings']
        if data.get('size'): layout['size'] = data.get('size')
        if data.get('aspect_ratio'): layout['aspect_ratio'] = data.get('aspect_ratio')
        if data.get('retry_count'): layout['retry_count'] = int(data.get('retry_count'))
        if data.get('temperature'): layout['temperature'] = float(data.get('temperature'))
        if data.get('position'): layout['position'] = data.get('position')
        if 'use_selection_context' in data: layout['use_selection_context'] = data.get('use_selection_context')
        
        if 'ui_backend' in data: config['ui_backend'] = data['ui_backend']
        
        self.save_config(config)
        self.config = config # Refresh local cache
        # Remove inkex.errormsg logs to avoid Inkscape dialog popup
    
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
        pars.add_argument("--manual_model_name", type=str, default="", help="Manual model name")
        pars.add_argument("--sync_models", type=inkex.Boolean, default=False, help="Sync models from provider")
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
        
        # We don't call perform_generation here anymore, it's triggered from /submit
        pass

    def perform_generation(self, data):
        """Asynchronous generation process called in a background thread."""
        try:
            self.is_processing = True
            self.status_data = {"status": "processing", "progress": 5, "message": "Initializing..."}
            
            # Apply data from Web UI
            for key, value in data.items():
                if hasattr(self.options, key):
                    orig_val = getattr(self.options, key)
                    try:
                        if isinstance(orig_val, bool):
                            setattr(self.options, key, str(value).lower() == 'true')
                        elif isinstance(orig_val, int):
                            setattr(self.options, key, int(value))
                        elif isinstance(orig_val, float):
                            setattr(self.options, key, float(value))
                        else:
                            setattr(self.options, key, value)
                    except:
                        setattr(self.options, key, value)
                else:
                    setattr(self.options, key, value)
                    
            # Unpack provider-specific settings (like api_endpoint, model) since UI sends them nested
            provider = data.get('provider')
            if provider and 'provider_settings' in data:
                p_settings = data['provider_settings'].get(provider, {})
                for k in ['api_endpoint', 'model', 'api_key', 'manual_model_name']:
                    if k in p_settings:
                        setattr(self.options, k, p_settings[k])

            self.status_data.update({"progress": 10, "message": "Loading configuration..."})
            api_key = self.get_api_key()
            
            # Save API key if requested
            if self.options.save_api_key and api_key:
                self.save_api_key(api_key)

            # Validate prompt
            if not self.options.prompt or len(self.options.prompt.strip()) < 3:
                self.status_data = {"status": "error", "progress": 0, "message": "Prompt too short."}
                self.is_processing = False
                return

            # Get size
            width, height = self.get_size()
            
            # Get selection context
            selection_context = ""
            if self.options.use_selection_context and self.svg.selection:
                self.status_data.update({"progress": 15, "message": "Analyzing selection..."})
                selection_context = self.get_selection_context()
            
            # Build prompt
            self.status_data.update({"progress": 20, "message": "Preparing AI context..."})
            enhanced_prompt = self.build_prompt(width, height, selection_context)
            
            # Variations count
            variations = min(max(1, int(self.options.variations or 1)), 4)
            success_count = 0
            last_error = None
            
            for i in range(variations):
                idx_msg = f" (Variation {i+1}/{variations})" if variations > 1 else ""
                self.status_data.update({
                    "progress": 20 + int((i / variations) * 60), 
                    "message": f"Calling API...{idx_msg}"
                })
                
                try:
                    svg_code = self.call_api_with_retry(enhanced_prompt, api_key, i)
                    if not svg_code:
                        continue
                    
                    self.status_data.update({"message": f"Parsing response...{idx_msg}"})
                    svg_code = self.validate_and_fix_svg(svg_code, width, height)
                    
                    self.status_data.update({"message": f"Adding to Inkscape...{idx_msg}"})
                    offset_x = i * (width + 20) if variations > 1 else 0
                    
                    # Add to document
                    self.add_svg_to_document(svg_code, width, height, offset_x, variation_num=i+1)
                    success_count += 1
                    
                except Exception as e:
                    last_error = str(e)
                    inkex.errormsg(f"Variation {i+1} failed: {e}")
            
            if success_count > 0:
                # Save history
                if self.options.save_to_history:
                    self.save_to_history(self.options.prompt, width, height)

                self.status_data = {"status": "completed", "progress": 100, "message": f"Successfully generated {success_count} variations!"}
                
                # QUIT gracefully
                import time
                time.sleep(1.5)
                bg = getattr(self, 'active_backend', None)
                if bg == 'gtk':
                    from gi.repository import GLib, Gtk
                    GLib.idle_add(Gtk.main_quit)
                elif bg == 'webview':
                    try: self.webview_window.destroy()
                    except: pass
            else:
                self.status_data = {"status": "error", "progress": 0, "message": f"Error: {last_error or 'Unknown generation failure'}"}
                
        except Exception as e:
            self.status_data = {"status": "error", "progress": 0, "message": f"Error: {str(e)}"}
        finally:
            self.is_processing = False

    def effect(self):
        """Main effect function."""
        # Run Web UI immediately
        self.run_web_ui()
        # The background thread updates the document and then quits GTK.
        # Once Gtk.main() returns, Inkscape will save the modified SVG.
    
    # ==================== Configuration Management ====================
    
    def get_api_key(self, provider=None):
        """
        Get API key with priority:
        1. Direct input (if provided and not placeholder)
        2. Environment variable (if use_env_key is True)
        3. Config file (if use_config_key is True)
        """
        if not provider:
            provider = getattr(self.options, 'provider', None) or self.config.get('last_provider', 'openai')

        # Skip API key for local provider
        if provider == 'local':
            return ''

        # 1. Check direct input first
        if self.options.api_key and self.options.api_key not in ['', 'sk-...', 'sk-your-key-here']:
            # Save to config if requested
            if self.options.save_api_key:
                config_key = self.PROVIDERS.get(provider, {}).get('config_key', '')
                if config_key:
                    self.set_config_value(config_key, self.options.api_key)
            return self.options.api_key
        
        # 2. Check config file directly from nested provider_settings
        p_data = self.config.get('provider_settings', {}).get(provider, {})
        if 'api_key' in p_data and p_data['api_key']:
            return p_data['api_key']
        
        return ''

    def load_config(self):
        """Load saved configuration and auto-migrate to new V2 schema if necessary."""
        config = {'provider_settings': {}, 'custom_profiles': [], 'layout_settings': {}, 'last_provider': 'openai'}
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    
                    # Merge new schema
                    if 'provider_settings' in loaded:
                        config.update(loaded)
                    else:
                        # Auto-migrate v1 -> v2 schema
                        config['last_provider'] = loaded.get('last_provider', 'openai')
                        
                        layout_keys = ['last_size', 'last_aspect_ratio', 'last_retry_count', 'last_temperature', 'last_position', 'last_use_selection_context']
                        for k in layout_keys:
                            if k in loaded:
                                config['layout_settings'][k.replace('last_', '')] = loaded.get(k)
                        
                        api_keys = loaded.get('api_keys', {})
                        endpoints = loaded.get('endpoints', {})
                        manual_models = loaded.get('manual_models', {})
                        
                        for provider in set(list(api_keys.keys()) + list(endpoints.keys()) + list(manual_models.keys()) + [config['last_provider']]):
                            if provider not in config['provider_settings']:
                                config['provider_settings'][provider] = {}
                            if provider in api_keys: config['provider_settings'][provider]['api_key'] = api_keys[provider]
                            if provider in endpoints: config['provider_settings'][provider]['api_endpoint'] = endpoints[provider]
                            if provider in manual_models: config['provider_settings'][provider]['manual_model_name'] = manual_models[provider]
                            if provider == config['last_provider'] and 'last_model' in loaded:
                                config['provider_settings'][provider]['model'] = loaded['last_model']
                                
                    return config
            except Exception as e:
                inkex.errormsg(f"Migration error: {e}")
        return config
    
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
        provider = self.options.provider
        if 'provider_settings' not in config: config['provider_settings'] = {}
        if provider not in config['provider_settings']: config['provider_settings'][provider] = {}
        
        config['provider_settings'][provider]['api_key'] = api_key
        config['last_provider'] = provider
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

    def clear_history(self):
        """Clear all prompt history."""
        if os.path.exists(self.history_path):
            try:
                os.remove(self.history_path)
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
            f"8. Valid elements: svg, g, path, rect, circle, ellipse, line, polyline, polygon, text, tspan, defs, use, clipPath, mask, linearGradient, radialGradient, stop",
            f"\nCRITICAL: DO NOT WRITE PROSE. DO NOT EXPLAIN. NO CHINESE/ENGLISH TEXT OUTSIDE SVG. ONLY <svg>...</svg>",
            f"请勿提供任何说明文字。只输出SVG代码。不要包含Markdown代码块符号。"
        ])
        
        if self.options.optimize_paths:
            prompt_parts.append("\n9. Optimize paths - use shorthand commands")
        
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
        provider = (getattr(self.options, 'provider', None) or self.config.get('last_provider', 'openai')).lower().strip()
        provider_type = 'openai_compatible' if provider.startswith('custom_') else provider
        
        if provider_type == "openai":
            return self.call_openai_api(prompt, api_key)
        elif provider_type == "anthropic":
            return self.call_anthropic_api(prompt, api_key)
        elif provider_type == "google":
            return self.call_google_api(prompt, api_key)
        elif provider_type == "ollama":
            return self.call_ollama_api(prompt)
        elif provider_type == "openai_compatible":
            return self.call_openai_api(prompt, api_key, is_compatible=True)
        else:
            raise Exception(f"Unknown provider: {provider}")
    
    def call_openai_api(self, prompt, api_key, is_compatible=False):
        """Call OpenAI API (or compatible) to generate SVG code."""
        if is_compatible:
            endpoint = self.options.api_endpoint or "http://localhost:1234/v1"
            # Ensure endpoint has /chat/completions if not present
            if not endpoint.endswith('/chat/completions'):
                if not endpoint.endswith('/'):
                    endpoint += '/'
                endpoint += 'chat/completions'
            url = endpoint
        else:
            url = "https://api.openai.com/v1/chat/completions"
        
        # Logs removed to prevent Inkscape popup
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}'
        }
        
        if is_compatible and 'openrouter.ai' in url.lower():
            headers['HTTP-Referer'] = 'https://github.com/bezineb5/svg_maker'
            headers['X-OpenRouter-Title'] = 'Inkscape AI SVG Generator'
            if not api_key.startswith('sk-or-v1-'):
                headers['Authorization'] = f'Bearer sk-or-v1-{api_key}'
        
        # Determine model name
        model = self.options.model
        if model == 'custom' or is_compatible:
            model = self.options.manual_model_name or model
        
        data = {
            'model': model,
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
            'temperature': self.options.temperature
        }
        
        # Native OpenAI strongly prefers max_completion_tokens now, especially for o1/o3
        if not is_compatible or ('o1-' in model or 'o3-' in model):
            data['max_completion_tokens'] = self.options.max_tokens
            if 'o1-' in model or 'o3-' in model:
                # o1/o3 strictly reject non-default temperature. Best to omit it entirely.
                if 'temperature' in data:
                    del data['temperature']
        else:
            data['max_tokens'] = self.options.max_tokens
        
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
        """Make HTTP request to API. Debugging active."""
        with open(os.path.join(os.path.dirname(__file__), "debug_outgoing.log"), "w") as f:
            f.write(f"URL: {url}\nHeaders: {headers}\nParser: {response_parser}\nAPI Key Length: {len(headers.get('Authorization', ''))}")
            
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
    
    def extract_svg_code(self, text):
        """Extract and sanitize SVG code from a potentially chatty AI response."""
        if not text:
            return ""
            
        # 1. Strip markdown code blocks if present
        text = re.sub(r'```svg\s*', '', text)
        text = re.sub(r'```\s*', '', text)
        
        # 2. Try to find <svg> ... </svg> blocks
        matches = re.findall(r'<svg[^>]*>.*?</svg>', text, re.DOTALL | re.IGNORECASE)
        
        if matches:
            matches.sort(key=len, reverse=True)
            svg_candidate = matches[0]
            
            # 3. Sanitize: Remove plain text explaining code BETWEEN tagging pairs
            # This is risky but often necessary for chatty local models.
            # We keep everything inside <...> and remove things outside unless they are in <text>
            # For simplicity, let's just remove obvious prose (lines starting with Chinese or bullet points)
            # but a better way is to keep only valid tags and their content.
            
            # Simplified approach: If it fails to parse, we'll try a regex-based tag recovery in add_svg_to_document
            return svg_candidate
            
        # 3. Fallback: if <svg> exists but </svg> is missing
        if '<svg' in text.lower():
            start_idx = text.lower().find('<svg')
            return text[start_idx:] + '</svg>'
            
        return text

    def validate_and_fix_svg(self, svg_code, width, height):
        """Validate and attempt to fix common SVG issues."""
        # Clean response first
        svg_code = self.extract_svg_code(svg_code)
        
        # Ensure it starts with <svg
        if not svg_code.strip().startswith('<svg'):
             # Wrap content in SVG tags if we couldn't find a proper block
             svg_code = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">{svg_code}</svg>'
        
        # Ensure xmlns is present
        if 'xmlns=' not in svg_code:
            svg_code = svg_code.replace('<svg', '<svg xmlns="http://www.w3.org/2000/svg"', 1)
        
        # Ensure viewBox is present
        if 'viewBox=' not in svg_code:
            svg_code = svg_code.replace('<svg', f'<svg viewBox="0 0 {width} {height}"', 1)
        
        return svg_code
    
    def add_svg_to_document(self, svg_code, target_width, target_height, offset_x=0, variation_num=1):
        """Parse SVG code and add it to the document. Includes recovery for chatty models."""
        try:
            # First attempt: standard parse
            try:
                svg_root = ET.fromstring(svg_code)
            except ET.ParseError as e:
                # Recovery: AI might have put prose INSIDE the <svg> tag.
                # We'll try to extract all valid-looking tags and re-wrap them.
                inkex.errormsg(f"Parsing failed ({e}), attempting tag recovery...")
                
                # Extract all tags like <path.../> or <circle...></circle>
                # Use a regex that looks for standard SVG elements
                element_pattern = r'<(path|circle|rect|ellipse|line|polyline|polygon|text|g|defs|linearGradient|radialGradient|use|mask|clipPath|stop)[^>]*?>.*?</\1>|<(path|circle|rect|ellipse|line|polyline|polygon|text|g|defs|linearGradient|radialGradient|use|mask|clipPath|stop)[^>]*?/>'
                elements = re.findall(element_pattern, svg_code, re.DOTALL | re.IGNORECASE)
                
                # elements is a list of tuples (tagname1, tagname2) due to the OR in the regex
                # We want the actual full match for each.
                full_elements = []
                for match in re.finditer(element_pattern, svg_code, re.DOTALL | re.IGNORECASE):
                    full_elements.append(match.group(0))
                
                if full_elements:
                    # Wrap the recovered elements in a clean SVG tag
                    recovered_svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {target_width} {target_height}">'
                    recovered_svg += "\n".join(full_elements)
                    recovered_svg += '</svg>'
                    svg_root = ET.fromstring(recovered_svg)
                    inkex.errormsg("Tag recovery successful.")
                else:
                    raise e
            
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
    try:
        SVGLLMGenerator().run()
    finally:
        log_file.close()
