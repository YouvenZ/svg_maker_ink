#!/usr/bin/env python3
"""
Review-first result gallery for the AI SVG Generator extension.

After generation, ResultReviewDialog shows every variation rendered as a
thumbnail. Nothing touches the Inkscape document until the user clicks
"Insert Selected". From here the user can also:

  - Refine a variation      — send a follow-up instruction; the existing SVG
                              is embedded in the prompt and replaced in place
  - Regenerate a variation  — re-run the original prompt for one slot
  - Preview / Copy / Save   — per-variation utilities
  - Discard All             — close without touching the document

The dialog is API-agnostic: the caller supplies callables
  refine_fn(existing_svg, instruction) -> svg_str
  regenerate_fn(variation_index)       -> svg_str
which are executed on a background thread.
"""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib

import threading

from svg_llm_common import sanitize_svg

# Optional librsvg for thumbnail rendering
_HAS_RSVG = False
_Rsvg = None
try:
    gi.require_version('Rsvg', '2.0')
    from gi.repository import Rsvg as _Rsvg  # type: ignore
    _HAS_RSVG = True
except Exception:
    pass

# Fallback: GdkPixbuf's SVG loader (present in Inkscape's Windows build,
# where the Rsvg introspection typelib is NOT shipped)
_HAS_PIXBUF_SVG = False
try:
    from gi.repository import GdkPixbuf as _GdkPixbuf  # type: ignore
    _probe = _GdkPixbuf.PixbufLoader()
    _probe.write(b'<svg xmlns="http://www.w3.org/2000/svg" '
                 b'width="1" height="1"/>')
    _probe.close()
    _HAS_PIXBUF_SVG = _probe.get_pixbuf() is not None
    del _probe
except Exception:
    _GdkPixbuf = None

_THUMB_SIZE = 240


def render_svg_pixbuf(svg_code, max_px):
    """
    Render SVG source to a GdkPixbuf scaled to fit max_px (aspect kept).
    Returns None when the pixbuf SVG loader is unavailable or parsing fails.
    """
    if not _HAS_PIXBUF_SVG:
        return None
    try:
        loader = _GdkPixbuf.PixbufLoader()

        def _on_size(ldr, w, h):
            if w > 0 and h > 0:
                scale = min(max_px / w, max_px / h)
                ldr.set_size(max(1, int(w * scale)), max(1, int(h * scale)))

        loader.connect('size-prepared', _on_size)
        loader.write(svg_code.encode('utf-8'))
        loader.close()
        return loader.get_pixbuf()
    except Exception:
        return None


class _VariationCard(Gtk.Frame):
    """One gallery card: thumbnail + insert checkbox + utility buttons."""

    def __init__(self, index, svg_code, error, parent_dialog):
        super().__init__()
        self.index = index
        self.svg_code = svg_code      # sanitized SVG source, or None
        self.error = error
        self._handle = None
        self._parent_dialog = parent_dialog
        self.set_shadow_type(Gtk.ShadowType.ETCHED_IN)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        vbox.set_border_width(6)
        self.add(vbox)

        title = Gtk.Label(xalign=0)
        title.set_markup(f"<b>Variation {index + 1}</b>")
        vbox.pack_start(title, False, False, 0)

        # ── Thumbnail area ───────────────────────────────────
        self._thumb_container = Gtk.Box()
        self._thumb_container.set_size_request(_THUMB_SIZE, _THUMB_SIZE)
        vbox.pack_start(self._thumb_container, False, False, 0)

        # ── Status line (size / error) ───────────────────────
        self._status_lbl = Gtk.Label(xalign=0)
        self._status_lbl.set_line_wrap(True)
        self._status_lbl.set_max_width_chars(34)
        self._status_lbl.get_style_context().add_class('dim-label')
        vbox.pack_start(self._status_lbl, False, False, 0)

        # ── Insert checkbox ──────────────────────────────────
        self.insert_check = Gtk.CheckButton(label="Insert into document")
        vbox.pack_start(self.insert_check, False, False, 0)

        # ── Utility buttons ──────────────────────────────────
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._preview_btn = Gtk.Button(label="Preview")
        self._preview_btn.connect('clicked', self._on_preview)
        self._copy_btn = Gtk.Button(label="Copy")
        self._copy_btn.set_tooltip_text("Copy SVG source to clipboard")
        self._copy_btn.connect('clicked', self._on_copy)
        self._save_btn = Gtk.Button(label="Save…")
        self._save_btn.set_tooltip_text("Save this variation to an .svg file")
        self._save_btn.connect('clicked', self._on_save)
        for b in (self._preview_btn, self._copy_btn, self._save_btn):
            btn_box.pack_start(b, True, True, 0)
        vbox.pack_start(btn_box, False, False, 0)

        self.set_content(svg_code, error)

    # ── Content management ───────────────────────────────────

    def set_content(self, svg_code, error):
        """Set / replace the card's SVG (after refine / regenerate)."""
        self.svg_code = svg_code
        self.error = error
        ok = bool(svg_code) and not error

        for child in self._thumb_container.get_children():
            self._thumb_container.remove(child)

        self._handle = None
        if ok and _HAS_RSVG:
            try:
                self._handle = _Rsvg.Handle.new_from_data(
                    svg_code.encode('utf-8'))
            except Exception:
                self._handle = None

        pixbuf = None
        if ok and self._handle is None:
            pixbuf = render_svg_pixbuf(svg_code, _THUMB_SIZE)

        if self._handle is not None:
            area = Gtk.DrawingArea()
            area.set_size_request(_THUMB_SIZE, _THUMB_SIZE)
            area.connect('draw', self._on_draw)
            self._thumb_container.pack_start(area, True, True, 0)
        elif pixbuf is not None:
            img = Gtk.Image.new_from_pixbuf(pixbuf)
            self._thumb_container.pack_start(img, True, True, 0)
        elif ok:
            # No librsvg — show a source snippet instead
            buf = Gtk.TextBuffer()
            snippet = svg_code[:600] + ('…' if len(svg_code) > 600 else '')
            buf.set_text(snippet)
            view = Gtk.TextView(buffer=buf)
            view.set_editable(False)
            view.set_monospace(True)
            view.set_wrap_mode(Gtk.WrapMode.CHAR)
            sw = Gtk.ScrolledWindow()
            sw.set_size_request(_THUMB_SIZE, _THUMB_SIZE)
            sw.add(view)
            self._thumb_container.pack_start(sw, True, True, 0)
        else:
            lbl = Gtk.Label(label="✗ generation failed", xalign=0.5)
            lbl.get_style_context().add_class('dim-label')
            self._thumb_container.pack_start(lbl, True, True, 0)

        if ok:
            size_b = len(svg_code.encode('utf-8'))
            self._status_lbl.set_text(f"{size_b:,} bytes")
            self.insert_check.set_sensitive(True)
            self.insert_check.set_active(True)
        else:
            self._status_lbl.set_text(str(error or 'No SVG produced.')[:200])
            self.insert_check.set_active(False)
            self.insert_check.set_sensitive(False)

        for b in (self._preview_btn, self._copy_btn, self._save_btn):
            b.set_sensitive(ok)

        self._thumb_container.show_all()

    def _on_draw(self, widget, cr):
        if self._handle is None:
            return
        alloc = widget.get_allocation()
        w, h = alloc.width, alloc.height
        try:
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
        scale = min(w / iw, h / ih)
        ox = (w - iw * scale) / 2
        oy = (h - ih * scale) / 2
        cr.translate(ox, oy)
        cr.scale(scale, scale)
        try:
            vp = _Rsvg.Rectangle()
            vp.x, vp.y, vp.width, vp.height = 0, 0, iw, ih
            self._handle.render_document(cr, vp)
        except Exception:
            try:
                self._handle.render_cairo(cr)
            except Exception:
                pass

    # ── Button handlers ──────────────────────────────────────

    def _on_preview(self, _btn):
        if not self.svg_code:
            return
        try:
            from svg_llm_dialog import SVGPreviewWindow
            SVGPreviewWindow(self.svg_code)
        except Exception:
            pass

    def _on_copy(self, _btn):
        if not self.svg_code:
            return
        try:
            from gi.repository import Gdk
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            clipboard.set_text(self.svg_code, -1)
            clipboard.store()
        except Exception:
            pass

    def _on_save(self, _btn):
        if not self.svg_code:
            return
        dlg = Gtk.FileChooserDialog(
            title="Save SVG variation",
            transient_for=self._parent_dialog,
            action=Gtk.FileChooserAction.SAVE,
        )
        dlg.add_buttons("_Cancel", Gtk.ResponseType.CANCEL,
                        "_Save", Gtk.ResponseType.ACCEPT)
        dlg.set_do_overwrite_confirmation(True)
        dlg.set_current_name(f"ai_svg_variation_{self.index + 1}.svg")
        if dlg.run() == Gtk.ResponseType.ACCEPT:
            path = dlg.get_filename()
            try:
                with open(path, 'w', encoding='utf-8') as fh:
                    fh.write(self.svg_code)
            except Exception as exc:
                self._parent_dialog.show_message(f"Could not save file: {exc}")
        dlg.destroy()


class ResultReviewDialog(Gtk.Window):
    """
    Modal gallery shown after generation. Blocks in Gtk.main() until the
    user accepts or discards.

    After the dialog closes, read:
      .accepted           — True if "Insert Selected" was clicked
      .accepted_results   — list of (variation_index, svg_code) to insert
    """

    def __init__(self, results, refine_fn=None, regenerate_fn=None):
        """
        results:       list of (svg_code | None, error | None) per variation
        refine_fn:     callable(existing_svg, instruction) -> svg_code
        regenerate_fn: callable(variation_index) -> svg_code
        Both callables may raise; they run on a background thread.
        """
        super().__init__(title="Review Generated SVG")
        self.set_modal(True)
        self.set_keep_above(True)
        self.set_border_width(10)
        self.accepted = False
        self.accepted_results = []
        self._refine_fn = refine_fn
        self._regenerate_fn = regenerate_fn
        self._busy = False
        self._cards = []

        n = max(1, len(results))
        width = min(300 * n + 60, 1000)
        self.set_default_size(width, 560)

        self._build_ui(results)
        self.connect('delete-event', self._on_discard)
        self.show_all()

    # ── UI ───────────────────────────────────────────────────

    def _build_ui(self, results):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add(outer)

        hint = Gtk.Label(xalign=0)
        hint.set_markup(
            "Nothing has been added to your document yet. "
            "<b>Check the variations you want</b>, refine or regenerate as "
            "needed, then click <b>Insert Selected</b>."
        )
        hint.set_line_wrap(True)
        outer.pack_start(hint, False, False, 0)

        # ── Gallery ──────────────────────────────────────────
        gallery = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for i, (svg_code, error) in enumerate(results):
            safe_svg = sanitize_svg(svg_code) if svg_code else None
            card = _VariationCard(i, safe_svg, error, self)
            self._cards.append(card)
            gallery.pack_start(card, False, False, 0)

        gallery_sw = Gtk.ScrolledWindow()
        gallery_sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        gallery_sw.add(gallery)
        outer.pack_start(gallery_sw, True, True, 0)

        # ── Refine / regenerate row ──────────────────────────
        if self._refine_fn or self._regenerate_fn:
            outer.pack_start(Gtk.Separator(), False, False, 0)
            refine_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

            refine_box.pack_start(Gtk.Label(label="Variation:"), False, False, 0)
            self._target_combo = Gtk.ComboBoxText()
            for i in range(len(self._cards)):
                self._target_combo.append(str(i), str(i + 1))
            self._target_combo.set_active(0)
            refine_box.pack_start(self._target_combo, False, False, 0)

            self._refine_entry = Gtk.Entry()
            self._refine_entry.set_placeholder_text(
                "Refine instruction — e.g. \"make the roof red, remove the text\""
            )
            self._refine_entry.connect('activate', self._on_refine)
            refine_box.pack_start(self._refine_entry, True, True, 0)

            if self._refine_fn:
                self._refine_btn = Gtk.Button(label="Refine")
                self._refine_btn.set_tooltip_text(
                    "Send the instruction plus the current SVG back to the "
                    "model and replace this variation with the result"
                )
                self._refine_btn.connect('clicked', self._on_refine)
                refine_box.pack_start(self._refine_btn, False, False, 0)
            else:
                self._refine_btn = None

            if self._regenerate_fn:
                self._regen_btn = Gtk.Button(label="Regenerate")
                self._regen_btn.set_tooltip_text(
                    "Re-run the original prompt for this variation"
                )
                self._regen_btn.connect('clicked', self._on_regenerate)
                refine_box.pack_start(self._regen_btn, False, False, 0)
            else:
                self._regen_btn = None

            outer.pack_start(refine_box, False, False, 0)

            self._busy_lbl = Gtk.Label(xalign=0)
            self._busy_lbl.get_style_context().add_class('dim-label')
            outer.pack_start(self._busy_lbl, False, False, 0)

        # ── Bottom bar ───────────────────────────────────────
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        discard_btn = Gtk.Button(label="Discard All")
        discard_btn.connect('clicked', self._on_discard)
        btn_box.pack_start(discard_btn, False, False, 0)

        self._insert_btn = Gtk.Button(label="Insert Selected")
        self._insert_btn.get_style_context().add_class('suggested-action')
        self._insert_btn.connect('clicked', self._on_insert)
        btn_box.pack_end(self._insert_btn, False, False, 0)
        outer.pack_start(btn_box, False, False, 0)

    # ── Helpers ──────────────────────────────────────────────

    def show_message(self, message):
        dlg = Gtk.MessageDialog(
            transient_for=self,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
        )
        dlg.set_markup(GLib.markup_escape_text(message))
        dlg.run()
        dlg.destroy()

    def _set_busy(self, busy, text=""):
        self._busy = busy
        if hasattr(self, '_busy_lbl'):
            self._busy_lbl.set_text(text)
        for btn in (getattr(self, '_refine_btn', None),
                    getattr(self, '_regen_btn', None),
                    self._insert_btn):
            if btn is not None:
                btn.set_sensitive(not busy)

    def _target_index(self):
        try:
            return int(self._target_combo.get_active_id() or '0')
        except Exception:
            return 0

    # ── Refine / regenerate ──────────────────────────────────

    def _on_refine(self, _widget):
        if self._busy or not self._refine_fn:
            return
        instruction = self._refine_entry.get_text().strip()
        if not instruction:
            self.show_message("Type a refine instruction first.")
            return
        idx = self._target_index()
        card = self._cards[idx]
        if not card.svg_code:
            self.show_message(
                f"Variation {idx + 1} has no SVG to refine — "
                "use Regenerate instead."
            )
            return
        self._run_async(
            f"Refining variation {idx + 1}…",
            lambda: self._refine_fn(card.svg_code, instruction),
            card,
        )
        self._refine_entry.set_text("")

    def _on_regenerate(self, _widget):
        if self._busy or not self._regenerate_fn:
            return
        idx = self._target_index()
        card = self._cards[idx]
        self._run_async(
            f"Regenerating variation {idx + 1}…",
            lambda: self._regenerate_fn(idx),
            card,
        )

    def _run_async(self, busy_text, fn, card):
        """Run fn() on a worker thread, update the card on the GTK thread."""
        self._set_busy(True, busy_text)

        def _worker():
            try:
                svg = fn()
                GLib.idle_add(self._apply_result, card, sanitize_svg(svg), None)
            except Exception as exc:
                GLib.idle_add(self._apply_result, card, None, str(exc))

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_result(self, card, svg, error):
        if error:
            self._set_busy(False, f"✗ {error[:160]}")
            # keep the card's previous content on failure
            if card.svg_code is None:
                card.set_content(None, error)
        else:
            card.set_content(svg, None)
            self._set_busy(False, f"✓ Variation {card.index + 1} updated")
        return False

    # ── Accept / discard ─────────────────────────────────────

    def _on_insert(self, _widget):
        if self._busy:
            return
        selected = [
            (card.index, card.svg_code)
            for card in self._cards
            if card.insert_check.get_active() and card.svg_code
        ]
        if not selected:
            self.show_message(
                "No variation is checked for insertion. Check at least one, "
                "or use Discard All to close without inserting."
            )
            return
        self.accepted = True
        self.accepted_results = selected
        Gtk.main_quit()

    def _on_discard(self, *_args):
        self.accepted = False
        self.accepted_results = []
        Gtk.main_quit()
        return False
