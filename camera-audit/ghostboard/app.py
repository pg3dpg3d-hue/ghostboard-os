"""
app.py — TUI GHOSTBOARD « RECON › Camera Audit » (Textual).

Pensée pour la dalle 4 pouces (~53 colonnes) et pilotable ENTIÈREMENT au
clavier physique BlackBerry Q20 — aucune action ne dépend de la souris.

Quatre écrans :
  Welcome  bannière GHOSTBOARD + rappel du périmètre autorisé
  Targets  édition rapide des cibles, validées contre le périmètre AVANT run
  Run      avancement live des 6 modules
  Findings constats triés par sévérité, détail au focus, rapport HTML servi

La logique de scan n'est PAS ici : elle vient de `bridge.get_backend()`, qui
relie auditkit. Cet écran affiche, trie, sert.
"""
from __future__ import annotations

import queue
from pathlib import Path

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (DataTable, Footer, Input, Label, RichLog, Static,
                             TextArea)

from . import bridge, scope, theme
from .report_server import ReportServer

REPORT_DIR = Path.home() / ".cache" / "ghostboard" / "recon"
REPORT_FILE = "camera-audit.html"


def _topbar(demo: bool) -> Static:
    bar = Static(id="topbar")
    parts = [("GHOSTBOARD", "bold"), " · ", theme.MODULE_NAME]
    if demo:
        parts += ["  ", ("[DEMO]", "")]  # étiquette courte : tient sur 53 colonnes
    bar.update(Text.assemble(*parts))
    return bar


class WelcomeScreen(Screen):
    BINDINGS = [
        Binding("enter", "go_targets", "Targets"),
        Binding("q", "app.quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        be = self.app.backend  # type: ignore[attr-defined]
        yield _topbar(be.is_demo)
        yield Static(theme.BANNER, id="banner")
        yield Static(theme.TAGLINE, id="tagline")

        entries = be.scope()
        scope_children = [Static("PERIMETER — AUTHORIZED SCOPE", classes="card-title")]
        if entries:
            scope_children += [Static(f"  ▸ {e}", classes="scope-line") for e in entries]
        else:
            scope_children.append(
                Static("  no scope declared — runs will be refused", classes="warn"))
        scope_children.append(Static(
            "Only hosts inside this perimeter can be scanned. Out-of-scope "
            "targets are refused before any packet is sent.", classes="dim"))
        yield Vertical(*scope_children, id="scope-box", classes="card")
        yield Footer()

    def action_go_targets(self) -> None:
        self.app.push_screen(TargetsScreen())


class TargetsScreen(Screen):
    BINDINGS = [
        Binding("f5", "run", "Run scan"),
        Binding("ctrl+r", "run", "Run scan"),
        Binding("escape", "app.pop_screen", "Back"),
        Binding("q", "app.quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        be = self.app.backend  # type: ignore[attr-defined]
        yield _topbar(be.is_demo)
        yield Label("TARGETS — one per line (IP, IP:port, CIDR, host)")
        ta = TextArea(id="targets-input", show_line_numbers=False)
        ta.text = "\n".join(be.scope())  # pré-rempli au périmètre : toujours in-scope
        yield ta
        yield Static("", id="target-help")
        yield Footer()

    def on_mount(self) -> None:
        self._revalidate()
        self.query_one("#targets-input", TextArea).focus()

    def on_text_area_changed(self, _event) -> None:
        self._revalidate()

    def _targets(self) -> list[str]:
        raw = self.query_one("#targets-input", TextArea).text
        return [ln.strip() for ln in raw.splitlines() if ln.strip()]

    def _revalidate(self) -> None:
        be = self.app.backend  # type: ignore[attr-defined]
        allowed, checks = scope.filter_targets(self._targets(), be.scope())
        help_w = self.query_one("#target-help", Static)
        if not checks:
            help_w.update(Text("Enter at least one target.", style="italic"))
            return
        lines = []
        for c in checks:
            mark = "✓" if c.ok else "✗"
            style = self.app.hx("ok") if c.ok else self.app.hx("sev_critical")
            lines.append(Text.assemble((f"  {mark} {c.target}", style),
                                       (f"  — {c.reason}", self.app.hx("text_dim"))))
        summary = Text.assemble(
            (f"{len(allowed)} in scope", self.app.hx("ok")), " · ",
            (f"{len(checks) - len(allowed)} refused", self.app.hx("sev_critical")),
            (f"   [F5] run", self.app.hx("accent")))
        body = Text("\n").join(lines + [Text(""), summary])
        help_w.update(body)

    def action_run(self) -> None:
        be = self.app.backend  # type: ignore[attr-defined]
        allowed, checks = scope.filter_targets(self._targets(), be.scope())
        if not allowed:
            self.app.bell()
            self.query_one("#target-help", Static).update(
                Text("No in-scope target — nothing to run.",
                     style=self.app.hx("sev_critical")))
            return
        self.app.push_screen(RunScreen(allowed))


class RunScreen(Screen):
    BINDINGS = [
        Binding("enter", "findings", "Findings"),
        Binding("escape", "app.pop_screen", "Back"),
        Binding("q", "app.quit", "Quit"),
    ]

    def __init__(self, targets: list[str]):
        super().__init__()
        self.targets = targets
        self._q: queue.Queue = queue.Queue()
        self._count = 0
        self._done = False

    def compose(self) -> ComposeResult:
        be = self.app.backend  # type: ignore[attr-defined]
        yield _topbar(be.is_demo)
        yield Label(f"RUNNING · {len(self.targets)} target(s)")
        rail = Vertical(id="modrail")
        yield rail
        yield Static("", id="run-count")
        yield RichLog(id="run-log", highlight=False, markup=False, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        rail = self.query_one("#modrail", Vertical)
        for key, label in bridge.MODULES:
            rail.mount(Static(f"  ○ {label}", id=f"mod-{key}", classes="mod mod-pending"))
        self._update_count()
        self._scan()

    @work(thread=True, exclusive=True)
    def _scan(self) -> None:
        # Worker en thread : la logique de scan d'auditkit peut bloquer. On
        # marshalle chaque événement vers le thread UI via call_from_thread.
        be = self.app.backend  # type: ignore[attr-defined]

        def emit(ev: bridge.Event):
            self.app.call_from_thread(self._on_event, ev)

        try:
            be.run(self.targets, emit)
        except Exception as exc:  # un scan qui plante ne doit pas figer la TUI
            self.app.call_from_thread(
                self._on_event, bridge.Event("error", message=f"scan error: {exc}"))
            self.app.call_from_thread(self._on_event, bridge.Event("done"))

    def _on_event(self, ev: bridge.Event) -> None:
        log = self.query_one("#run-log", RichLog)
        if ev.kind == "module_start":
            w = self.query_one(f"#mod-{ev.module}", Static)
            w.remove_class("mod-pending"); w.add_class("mod-active")
            w.update(f"  ▶ {bridge.MODULE_LABEL.get(ev.module, ev.module)}")
            log.write(f"[{bridge.MODULE_LABEL.get(ev.module, ev.module)}] start")
        elif ev.kind == "module_done":
            w = self.query_one(f"#mod-{ev.module}", Static)
            w.remove_class("mod-active"); w.add_class("mod-done")
            w.update(f"  ● {bridge.MODULE_LABEL.get(ev.module, ev.module)}")
        elif ev.kind == "finding" and ev.finding:
            self._count += 1
            self.app.findings.append(ev.finding)  # type: ignore[attr-defined]
            self._update_count()
            sev = ev.finding.severity.label
            log.write(f"  + [{sev}] {ev.finding.title}")
        elif ev.kind in ("log", "error"):
            log.write(("! " if ev.kind == "error" else "  ") + ev.message)
        elif ev.kind == "done":
            self._done = True
            if ev.message:
                log.write(ev.message)
            log.write("— scan complete — [Enter] findings —")
            self.refresh_bindings()  # révèle l'action « findings » dans le footer

    def _update_count(self) -> None:
        self.query_one("#run-count", Static).update(
            Text(f"  {self._count} finding(s)", style=self.app.hx("text")))

    def check_action(self, action: str, parameters):
        # L'accès aux constats n'est proposé qu'une fois le scan terminé.
        if action == "findings" and not self._done:
            return None  # masqué du footer tant que le scan tourne
        return True

    def action_findings(self) -> None:
        if self._done:
            self.app.push_screen(FindingsScreen())


class FindingsScreen(Screen):
    BINDINGS = [
        Binding("r", "report", "Report+serve"),
        Binding("s", "toggle_server", "Serve on/off"),
        Binding("escape", "home", "Home"),
        Binding("q", "app.quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        be = self.app.backend  # type: ignore[attr-defined]
        yield _topbar(be.is_demo)
        table = DataTable(id="findings", cursor_type="row", zebra_stripes=False)
        yield table
        yield Static("", id="detail")
        yield Static("", id="summary")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#findings", DataTable)
        table.add_column("SEV", width=9)
        table.add_column("TARGET", width=16)
        table.add_column("FINDING")
        # Tri par sévérité décroissante : les critiques en tête.
        self._rows = sorted(self.app.findings,  # type: ignore[attr-defined]
                            key=lambda f: -int(f.severity))
        for f in self._rows:
            table.add_row(
                Text(f.severity.label, style=self._sev_style(f.severity)),
                Text(f.target or "—", style=self.app.hx("text_dim")),
                Text(f.title, style=self._sev_style(f.severity)
                     if f.severity >= bridge.Severity.HIGH else self.app.hx("text")))
        self._update_summary()
        if self._rows:
            table.focus()
            self._show_detail(0)
        else:
            self.query_one("#detail", Static).update(
                Text("No findings.", style=self.app.hx("text_dim")))

    def _sev_style(self, sev: bridge.Severity) -> str:
        return {
            bridge.Severity.CRITICAL: self.app.hx("sev_critical"),
            bridge.Severity.HIGH: self.app.hx("sev_high"),
            bridge.Severity.MEDIUM: self.app.hx("sev_medium"),
            bridge.Severity.INFO: self.app.hx("text_dim"),
        }[sev]

    def on_data_table_row_highlighted(self, event) -> None:
        self._show_detail(event.cursor_row)

    def _show_detail(self, idx: int) -> None:
        if not (0 <= idx < len(self._rows)):
            return
        f = self._rows[idx]
        parts = [
            Text.assemble((f.severity.label, self._sev_style(f.severity)),
                          "  ", (f.title, self.app.hx("text") + " bold")),
            Text.assemble((f"{f.target or '—'}", self.app.hx("text_dim")),
                          "  ·  ", (f.module_label, self.app.hx("text_dim"))),
        ]
        if f.cve:
            parts.append(Text(f.cve + "  (informational)", style=self.app.hx("sev_high")))
        if f.detail:
            parts.append(Text(f.detail, style=self.app.hx("text")))
        if f.evidence:
            parts.append(Text("› " + f.evidence, style=self.app.hx("text_dim")))
        self.query_one("#detail", Static).update(Text("\n").join(parts))

    def _update_summary(self) -> None:
        from collections import Counter
        c = Counter(f.severity for f in self._rows)
        srv = ""
        if self.app.server and self.app.server_note:  # type: ignore[attr-defined]
            srv = "   ● " + self.app.server.url(REPORT_FILE)  # type: ignore[attr-defined]
        txt = Text.assemble(
            (f"{c[bridge.Severity.CRITICAL]} crit", self.app.hx("sev_critical")), " · ",
            (f"{c[bridge.Severity.HIGH]} high", self.app.hx("sev_high")), " · ",
            (f"{c[bridge.Severity.MEDIUM]} med", self.app.hx("sev_medium")), " · ",
            (f"{c[bridge.Severity.INFO]} info", self.app.hx("text_dim")),
            (srv, self.app.hx("ok")))
        self.query_one("#summary", Static).update(txt)

    def action_report(self) -> None:
        be = self.app.backend  # type: ignore[attr-defined]
        out = REPORT_DIR / REPORT_FILE
        be.make_report(self._rows, out)
        if not self.app.server:  # type: ignore[attr-defined]
            self._start_server()
        self._update_summary()
        note = self.app.server_note or ""  # type: ignore[attr-defined]
        self.query_one("#detail", Static).update(
            Text.assemble(("Report regenerated.\n", self.app.hx("ok")),
                          (note + "\n", self.app.hx("text")),
                          (self.app.server.url(REPORT_FILE),  # type: ignore[attr-defined]
                           self.app.hx("accent"))))

    def action_toggle_server(self) -> None:
        if self.app.server:  # type: ignore[attr-defined]
            self.app.server.stop()  # type: ignore[attr-defined]
            self.app.server = None  # type: ignore[attr-defined]
            self.app.server_note = ""  # type: ignore[attr-defined]
        else:
            (REPORT_DIR / REPORT_FILE).parent.mkdir(parents=True, exist_ok=True)
            if not (REPORT_DIR / REPORT_FILE).exists():
                self.app.backend.make_report(self._rows, REPORT_DIR / REPORT_FILE)  # type: ignore[attr-defined]
            self._start_server()
        self._update_summary()

    def _start_server(self) -> None:
        srv = ReportServer(REPORT_DIR)
        note = srv.start()
        self.app.server = srv  # type: ignore[attr-defined]
        self.app.server_note = note  # type: ignore[attr-defined]

    def action_home(self) -> None:
        self.app.pop_screen()


class ReconApp(App):
    CSS_PATH = "recon.tcss"
    TITLE = "GHOSTBOARD RECON"

    def __init__(self, backend=None):
        super().__init__()
        self.backend = backend or bridge.get_backend()
        self.findings: list[bridge.GhostFinding] = []
        self.server = None
        self.server_note = ""
        self._palette = theme.load_palette()

    def get_css_variables(self) -> dict[str, str]:
        # Injecte les $gb-* issus de la palette du système. C'est ce qui rend
        # recon.tcss piloté par brand/palette.toml.
        base = super().get_css_variables()
        base.update(theme.css_variables())
        return base

    def hx(self, key: str) -> str:
        """Hex d'une couleur de la palette, pour styliser du Rich Text."""
        return self._palette.get(key, "#D6D2E0")

    def on_mount(self) -> None:
        self.push_screen(WelcomeScreen())

    def action_quit(self) -> None:  # nettoie le serveur avant de sortir
        if self.server:
            self.server.stop()
        self.exit()


def main() -> int:
    ReconApp().run()
    return 0
