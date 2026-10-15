"""Diktatūra — status bar ikona (GNOME/Ubuntu, AyatanaAppIndicator3).

  ⚪ pilka   — budi (nerašo)
  🔴 raudona — įrašoma (yra runtime būsenos failas, kurį kuria įrašymo daemon'ai)
  🟡 geltona — apdorojama (transkripcija / mp3)
  Pulsuoja (pilna ↔ blanki tos pačios spalvos ikona, ~1 s ciklas), kol yra nežinomų balsų (Apmokymai).

Kol transkribuojama — meniu punktas „⏳ 43 % · liko ~1 val. · eilėje 4" (diktatura.progress) atidaro eigos langelį.
💊 Įrašymo indikatorius ekrano kampe (REC_PILL, ui.pill): gyva banga ir laikmatis įrašant, po to transkripcijos eiga.
Ubuntu AppIndicator paspaudus VISADA atidaro meniu (langas tiesiai neatsidaro), todėl: meniu viršuje
„⚙ Nustatymai" (ir „🎓 Apmokymai paruošti (N)", kai yra laukiančių); vidurinis klik -> iškart Nustatymai.
Langai atidaromi per `diktatura.ui.app --page …` (vienas egzempliorius).
Paleidimas: SISTEMOS python3 (turi gi):  python3 -m diktatura.ui.tray   (systemd: diktatura-tray.service)
"""
import os
import subprocess

from diktatura import paths, progress, services
from diktatura.speakers import store

LABELS = {"rec": "🔴 Įrašoma", "proc": "🟡 Apdorojama (transkripcija)", "idle": "⚪ Budi (nerašo)"}
PULSE_MS = 500             # kadras (pilna/blanki) — pilnas ciklas ~1 s
POLL_SEC = 2


def running(pattern: str) -> bool:
    return subprocess.run(["pgrep", "-f", pattern],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def compute_state(recording: bool, processing: bool) -> str:
    """Gryna būsenos logika: įrašymas svarbiau už apdorojimą."""
    if recording:
        return "rec"
    if processing:
        return "proc"
    return "idle"


def icon_name(state: str, pending: int, phase: int) -> str:
    """Kuris ikonos kadras rodomas: kol yra laukiančių balsų — kas antras kadras blankus."""
    return f"diktatura-{state}-dim" if pending and phase % 2 else f"diktatura-{state}"


def training_label(pending: int) -> str:
    return f"🎓 Apmokymai paruošti ({pending})"


def current_state() -> str:
    return compute_state(
        paths.STATE_RECORDING.exists(),
        running(r"diktatura\.asr\.transcribe") or running(r"ffmpeg.*libmp3lame"),
    )


def open_app(page: str) -> None:
    """Atidaryti/perjungti pagrindinį langą (jei jau atidarytas — tik perjungia skiltį); "progress" — Tekstas +
    ⏳ eigos langelis."""
    env = {**os.environ, "PYTHONPATH": str(paths.REPO)}
    args = ["--page", "text", "--progress"] if page == "progress" else ["--page", page]
    subprocess.Popen(["/usr/bin/python3", "-m", "diktatura.ui.app", *args], cwd=str(paths.REPO), env=env)


def progress_label(snap) -> str:
    """Meniu punktas: „⏳ 43 % · liko ~1 val. 20 min · eilėje 4" ("" — nieko nevyksta)."""
    s = progress.summary(snap)
    return f"⏳ {s}" if s else ""


class Tray:
    def __init__(self, indicator=None, opener=open_app, state_fn=current_state, mode_fn=services.recorder_mode,
                 pending_fn=store.pending_count, timers=True, progress_fn=progress.snapshot, pill=None):
        from diktatura.ui.gtk import GLib, Gtk
        self.Gtk = Gtk
        self.opener, self.state_fn, self.mode_fn, self.pending_fn = opener, state_fn, mode_fn, pending_fn
        self.progress_fn = progress_fn
        self.ind = indicator or self._make_indicator()
        self.menu = Gtk.Menu()
        self.it_settings = self._item("⚙ Nustatymai", lambda: self.opener("settings"))
        self.it_training = self._item(training_label(0), lambda: self.opener("training"))
        self._item("📄 Rodyti nuskaitytą tekstą", lambda: self.opener("text"))
        self.it_progress = self._item("⏳", lambda: self.opener("progress"))
        self.menu.append(Gtk.SeparatorMenuItem())
        self.it_status = self._item("Diktatūra", None)
        self.it_mode = self._item("Režimas: …", None)
        self.menu.append(Gtk.SeparatorMenuItem())
        self._item("Atidaryti įrašų aplanką", lambda: subprocess.Popen(["xdg-open", str(paths.RECORDINGS)]))
        self._item("Išeiti", Gtk.main_quit)          # tik ikona; įrašymas (VOX / Slack servisas) veikia toliau
        self.menu.show_all()
        self.ind.set_menu(self.menu)
        self.ind.set_secondary_activate_target(self.it_settings)      # vidurinis klik -> Nustatymai
        self.state, self.pending, self.phase, self.shown_icon = None, 0, 0, None
        self.update()
        self.pill = pill
        if timers:
            GLib.timeout_add_seconds(POLL_SEC, self.update)
            GLib.timeout_add(PULSE_MS, self.pulse)
            if self.pill is None:
                from diktatura.ui import pill as pill_mod
                view = pill_mod.PillView(on_click=self.on_pill_click, on_close=lambda: self.pill.dismiss())
                self.pill = pill_mod.PillController(view, snap_fn=self.progress_fn)
            GLib.timeout_add(100, self._pill_tick)

    def _pill_tick(self):
        try:
            self.pill.tick()
        except Exception:                        # indikatorius — tik informacija; ikona nelūžta
            pass
        return True

    def on_pill_click(self) -> None:
        """Spragtelėtas indikatorius: transkribuojant — ⏳ langelis, kitaip — Tekstas."""
        self.opener("progress" if self.pill is not None and self.pill.state == "after"
                    and self.pill.view.mode == "after" and self.pill.view.bar.get_visible() else "text")

    @staticmethod
    def _make_indicator():
        import gi
        gi.require_version("AyatanaAppIndicator3", "0.1")
        from gi.repository import AyatanaAppIndicator3 as AppIndicator
        ind = AppIndicator.Indicator.new_with_path(
            "diktatura", "diktatura-idle", AppIndicator.IndicatorCategory.APPLICATION_STATUS, str(paths.ICONS))
        ind.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        return ind

    def _item(self, text, cb):
        it = self.Gtk.MenuItem(label=text)
        if cb:
            it.connect("activate", lambda _w: cb())
        else:
            it.set_sensitive(False)
        self.menu.append(it)
        return it

    def _set_icon(self):
        name = icon_name(self.state, self.pending, self.phase)
        if name != self.shown_icon:
            self.ind.set_icon_full(name, LABELS[self.state])
            self.shown_icon = name

    def update(self):
        self.state = self.state_fn()
        self.pending = self.pending_fn()
        if not self.pending:
            self.phase = 0
        self._set_icon()
        self.ind.set_title(f"Diktatūra — {LABELS[self.state]}")
        self.it_status.set_label(f"Diktatūra — {LABELS[self.state]}")
        self.it_mode.set_label(f"Režimas: {services.MODE_LABELS[self.mode_fn()].split(' — ')[0]}")
        self.it_training.set_label(training_label(self.pending))
        self.it_training.set_visible(bool(self.pending))
        try:
            prog = progress_label(self.progress_fn())
        except Exception:                        # eiga — tik informacija; ikona nelūžta
            prog = ""
        self.it_progress.set_label(prog or "⏳")
        self.it_progress.set_visible(bool(prog))
        return True

    def pulse(self):
        if self.pending:
            self.phase += 1
            self._set_icon()
        return True


def main():
    from diktatura.ui.gtk import Gtk
    Tray()
    Gtk.main()


if __name__ == "__main__":
    main()
