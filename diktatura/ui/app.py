"""Diktatūra — pagrindinis langas: 📄 Tekstas · 🎓 Apmokymai · ⚙ Nustatymai (+ ◀ Atgal).

Vienas egzempliorius (Gtk.Application per D-Bus): antras paleidimas su `--page <skiltis>` tik perjungia skiltį jau
atidarytame lange (taip daro status bar ikonos meniu). Paleidimas — SISTEMOS python3 (gi/GTK):
    python3 -m diktatura.ui.app [--page text|training|settings] [--shot failas.png]
--shot — nufotografuoti langą ir išeiti (README screenshot'ams). Env DIKTATURA_APP_ID — kitas id (testams).
"""
import argparse
import os
import sys

from diktatura.ui.gtk import Gdk, Gio, GLib, Gtk, install_css
from diktatura.ui.settings_page import SettingsPage
from diktatura.ui.text_page import TextPage
from diktatura.ui.training_page import TrainingPage

APP_ID = "lt.diktatura.Diktatura"
PAGES = (("text", "📄 Tekstas"), ("training", "🎓 Apmokymai"), ("settings", "⚙ Nustatymai"))


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app=None, rec_dir=None, auto_refresh=True):
        super().__init__(application=app, title="Diktatūra")
        install_css()
        self.set_default_size(920, 700)
        self.set_icon_name("audio-input-microphone")
        self.history = []
        self._navigating_back = False

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.text = TextPage(self, rec_dir=rec_dir, auto_refresh=auto_refresh)
        self.training = TrainingPage(self, auto_refresh=auto_refresh)
        self.settings = SettingsPage(self)
        self.pages = {"text": self.text, "training": self.training, "settings": self.settings}
        for name, title in PAGES:
            self.stack.add_titled(self.pages[name], name, title)

        hb = Gtk.HeaderBar()
        hb.set_show_close_button(True)
        sw = Gtk.StackSwitcher()
        sw.set_stack(self.stack)
        hb.set_custom_title(sw)
        self.btn_back = Gtk.Button(label="◀ Atgal")
        self.btn_back.set_tooltip_text("Grįžti į ankstesnę skiltį")
        self.btn_back.connect("clicked", lambda _w: self.go_back())
        self.btn_back.set_sensitive(False)
        hb.pack_start(self.btn_back)
        self.set_titlebar(hb)
        self.add(self.stack)

        self.current = "text"
        self.stack.connect("notify::visible-child-name", self._on_page)
        self.connect("key-press-event", self._on_key)

    def show_page(self, name: str) -> None:
        if name in self.pages:
            self.stack.set_visible_child_name(name)

    def go_back(self) -> None:
        if self.history:
            self._navigating_back = True
            self.show_page(self.history.pop())
            self._navigating_back = False

    def _on_page(self, *_):
        name = self.stack.get_visible_child_name()
        if name == self.current:
            return
        if not self._navigating_back:
            self.history.append(self.current)
        self.current = name
        self.btn_back.set_sensitive(bool(self.history))
        page = self.pages[name]
        if hasattr(page, "on_shown"):
            page.on_shown()

    def _on_key(self, _w, ev):
        if self.current == "text":
            return self.text.on_key(ev)
        return False

    def screenshot(self, path: str, quit_after: bool = False):
        win = self.get_window()
        if win:
            pb = Gdk.pixbuf_get_from_window(win, 0, 0, win.get_width(), win.get_height())
            if pb:
                pb.savev(path, "png", [], [])
        if quit_after:
            app = self.get_application()
            app.quit() if app else Gtk.main_quit()
        return False


def parse_args(argv):
    ap = argparse.ArgumentParser(prog="diktatura.ui.app")
    ap.add_argument("--page", choices=[p for p, _ in PAGES])
    ap.add_argument("--shot", help="nufotografuoti langą į PNG ir išeiti")
    return ap.parse_args(argv)


class App(Gtk.Application):
    def __init__(self, app_id: str):
        super().__init__(application_id=app_id, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.win = None

    def do_command_line(self, cl):
        try:
            args = parse_args(cl.get_arguments()[1:])
        except SystemExit:
            return 2
        if self.win is None:
            self.win = MainWindow(self)
            self.win.show_all()
        if args.page:
            self.win.show_page(args.page)
        self.win.present_with_time(Gdk.CURRENT_TIME)
        if args.shot:
            GLib.timeout_add(1500, self.win.screenshot, os.path.abspath(args.shot), True)
        return 0


def main(argv=None) -> int:
    app = App(os.environ.get("DIKTATURA_APP_ID") or APP_ID)
    return app.run([sys.argv[0]] + list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    sys.exit(main())
