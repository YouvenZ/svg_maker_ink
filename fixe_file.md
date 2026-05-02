```markdown
# GTK Empty Rectangle & Pango Crash Fix Plan — AI SVG Generator

## Files
- `C:\Users\youve\AppData\Roaming\inkscape\extensions\svg_maker\svg_llm_dialog.py`
- `C:\Users\youve\AppData\Roaming\inkscape\extensions\svg_maker\svg_llm.py`
- `C:\Users\youve\AppData\Roaming\inkscape\extensions\svg_maker\svg_llm.inx`

---

## Root Causes

### RC-1 — `SVGLLMDialog(Gtk.Dialog)` without a parent window
`Gtk.Dialog` without a `transient_for` parent creates a hidden internal GtkWindow on GTK3.
On Windows this renders as a visible empty rectangle behind the real dialog.

### RC-2 — `GenerationProgressDialog(Gtk.Dialog)` same issue + uses `self.response()`
Same `Gtk.Dialog` problem. Also calls `self.response(Gtk.ResponseType.OK)` from a background
thread via `GLib.idle_add`, which is valid for Dialog but not Window.

### RC-3 — `Gtk.MessageDialog(text=message)` parses Pango markup
The `text=` constructor argument is parsed as Pango XML. Any string containing `<` or `>`
(e.g. exception messages, template names) causes:
`Error: Element "X" was closed, but the currently open element is "Y"`

### RC-4 — Missing `implements-custom-gui="true"` in `svg_llm.inx`
Without this attribute Inkscape renders its own native stub/progress dialog window
alongside the custom GTK dialog, causing a second empty rectangle.

---

## Fix Plan

### Fix 1 — `svg_llm.inx`
Change:
```xml
<effect>
```
To:
```xml
<effect needs-live-preview="false" implements-custom-gui="true">
```

---

### Fix 2 — Convert `SVGLLMDialog` from `Gtk.Dialog` → `Gtk.Window`

**In svg_llm_dialog.py:**

```python
# BEFORE
class SVGLLMDialog(Gtk.Dialog):
    def __init__(self, config, history_path, templates_path="", has_selection=False, layers=None):
        super().__init__(title="AI SVG Generator", modal=True)
        ...
        self._build_ui()
        self._load_defaults_from_config()
        self.show_all()

    def _build_ui(self):
        content = self.get_content_area()
        content.set_spacing(4)
        self._notebook = Gtk.Notebook()
        content.pack_start(self._notebook, True, True, 0)
        # ... tabs ...
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        btn = self.add_button("Generate", Gtk.ResponseType.OK)
        btn.get_style_context().add_class("suggested-action")
        self.set_default_response(Gtk.ResponseType.OK)
```

```python
# AFTER
class SVGLLMDialog(Gtk.Window):
    def __init__(self, config, history_path, templates_path="", has_selection=False, layers=None):
        super().__init__(title="AI SVG Generator")
        self.set_modal(True)
        self._accepted = False
        ...
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

    def _build_ui(self):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.add(content)
        self._notebook = Gtk.Notebook()
        content.pack_start(self._notebook, True, True, 0)
        # ... tabs ...
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
```

---

### Fix 3 — Convert `GenerationProgressDialog` from `Gtk.Dialog` → `Gtk.Window`

```python
# BEFORE
class GenerationProgressDialog(Gtk.Dialog):
    def __init__(self, total_variations):
        super().__init__(title="Generating SVG…", modal=True)
        ...
        self.connect("response", self._on_response)
        self.show_all()

    def _build_ui(self):
        content = self.get_content_area()
        ...
        self._cancel_btn = self.add_button("Cancel", Gtk.ResponseType.CANCEL)

    def _finish_idle(self):
        ...
        GLib.idle_add(lambda: self.response(Gtk.ResponseType.OK) or False)
        return False

    def _on_response(self, _dialog, response_id):
        if response_id == Gtk.ResponseType.CANCEL:
            self.cancelled = True
            self._done = True
            ...
```

```python
# AFTER
class GenerationProgressDialog(Gtk.Window):
    def __init__(self, total_variations):
        super().__init__(title="Generating SVG…")
        self.set_modal(True)
        self._done_ok = False   # NEW flag replaces ResponseType.OK check
        ...
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

    def _build_ui(self):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add(content)
        ...
        self._cancel_btn = Gtk.Button(label="Cancel")
        self._cancel_btn.connect("clicked", self._on_cancel_clicked)
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        btn_box.pack_end(self._cancel_btn, False, False, 0)
        content.pack_start(btn_box, False, False, 0)

    def _finish_idle(self):
        ...
        if not self.cancelled and not self._done:
            self._done = True
            self._done_ok = True
            self._set_status("Done.")
            GLib.idle_add(lambda: self._cancel_btn.set_label("Close") or False)
            GLib.idle_add(lambda: Gtk.main_quit() or False)
        return False
    # DELETE the _on_response method entirely
```

---

### Fix 4 — Pango-safe `MessageDialog` calls

Affects: `_alert()`, `_on_clear_history()`, `_on_delete_template()`

```python
# BEFORE (all three locations)
dlg = Gtk.MessageDialog(
    transient_for=self,
    message_type=Gtk.MessageType.INFO,   # or QUESTION
    buttons=Gtk.ButtonsType.OK,          # or YES_NO
    text=message                         # ← Pango-parsed, crashes on < >
)

# AFTER
dlg = Gtk.MessageDialog(
    transient_for=self,
    message_type=Gtk.MessageType.INFO,   # or QUESTION
    buttons=Gtk.ButtonsType.OK,          # or YES_NO
)
dlg.set_markup(GLib.markup_escape_text(message))   # ← safe for any string
```

> `GLib` is already imported: `from gi.repository import Gtk, GLib`

---

### Fix 5 — Update call sites in svg_llm.py

```python
# BEFORE — SVGLLMDialog
response = dialog.run()
if response != Gtk.ResponseType.OK:
    dialog.destroy()
    return

# AFTER
dialog.show()
Gtk.main()
if not dialog._accepted:
    dialog.destroy()
    return
```

```python
# BEFORE — GenerationProgressDialog
resp = prog.run()
prog.destroy()
if resp != Gtk.ResponseType.OK or prog.cancelled:
    return

# AFTER
prog.show()
Gtk.main()
prog.destroy()
if not prog._done_ok or prog.cancelled:
    return
```

---

## Validation
```powershell
python -m py_compile svg_llm_dialog.py ; Write-Host "dialog OK"
python -m py_compile svg_llm.py        ; Write-Host "main OK"
```
Both must print `OK` with no errors.
Continued with Autopilot: Task not yet completeThe markdown fix plan covering all 5 fixes (INX attribute, SVGLLMDialog → Gtk.Window, GenerationProgressDialog → Gtk.Window, Pango-safe MessageDialog, svg_llm.py call sites) has been provided above. 



You've used 66% of your weekly rate limit. Your weekly rate limit will reset on May 4 at 4:00 AM. [Learn More](https://aka.ms/github-copilot-rate-limit-error)