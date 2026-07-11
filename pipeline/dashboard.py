"""A clean live terminal dashboard (rich) for the harvest run. The harvester
calls emit(event); this module renders shared state. No business logic here."""
import threading
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class DashState:
    limit: int | None = None
    start: float = field(default_factory=time.time)
    counts: dict = field(default_factory=lambda: {"queued": 0, "running": 0, "done": 0, "failed": 0})
    processed: int = 0
    pairs_total: int = 0
    skips_total: int = 0
    repo: str = "—"
    stage: str = "starting"
    cur_file: str = ""
    cur_i: int = 0
    cur_n: int = 0
    repo_pairs: int = 0
    recent: deque = field(default_factory=lambda: deque(maxlen=6))
    log: deque = field(default_factory=lambda: deque(maxlen=7))
    _samples: deque = field(default_factory=lambda: deque(maxlen=30))
    done: bool = False


def apply(state: DashState, e: dict) -> None:
    t = e.get("type")
    if t == "stage":
        state.repo = e.get("repo") or state.repo
        state.stage = e["stage"]
        state.cur_file, state.cur_i, state.cur_n = "", 0, 0
        if e["stage"] == "cloning":
            state.repo_pairs = 0
    elif t == "file":
        state.cur_file, state.cur_i, state.cur_n = e.get("file", ""), e.get("i", 0), e.get("n", 0)
    elif t == "repo_done":
        status = e.get("status")
        if status == "done":
            state.pairs_total += e.get("pairs", 0)
            state.skips_total += e.get("skipped", 0)
            state.repo_pairs = e.get("pairs", 0)
            state.recent.appendleft(("done", e.get("repo", ""), f"{e.get('pairs', 0)} pairs"))
        else:
            state.recent.appendleft(("failed", e.get("repo", ""), e.get("reason", "failed")))
        state._samples.append((time.time(), state.pairs_total, state.processed))
    elif t == "progress":
        state.processed = e.get("processed", state.processed)
        for k in ("queued", "running", "done", "failed"):
            if k in e:
                state.counts[k] = e[k]
    elif t == "discover":
        state.stage = "discovering"
        state.repo = e.get("slice", "")
    elif t == "log":
        state.log.appendleft((e.get("level", "info"), e.get("msg", "")))


def _bar(i, n, width=34):
    if not n:
        return "░" * width
    filled = int(width * i / n)
    return "█" * filled + "░" * (width - filled)


def _elapsed(state):
    s = int(time.time() - state.start)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _rates(state):
    mins = max((time.time() - state.start) / 60, 1e-6)
    return state.processed / mins, state.pairs_total / mins


def _render(state: DashState):
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich import box

    c = state.counts
    head = Table.grid(expand=True)
    head.add_column(justify="left")
    head.add_column(justify="right")
    limit = "∞" if state.limit is None else str(state.limit)
    head.add_row(
        Text.assemble(("queued ", "dim"), (f"{c['queued']}  ", "cyan"),
                      ("running ", "dim"), (f"{c['running']}  ", "yellow"),
                      ("done ", "dim"), (f"{c['done']}  ", "green"),
                      ("failed ", "dim"), (f"{c['failed']}", "red")),
        Text(f"{state.processed}/{limit} this run", style="dim"))

    cur = Table.grid(expand=True)
    cur.add_column(justify="left")
    icon = {"cloning": "⬇", "compiling": "⚙", "discovering": "🔎"}.get(state.stage, "•")
    cur.add_row(Text.assemble(("▶ ", "bold green"), (state.repo, "bold"),
                              ("   ", ""), (f"{icon} {state.stage}", "yellow")))
    if state.cur_n:
        pct = int(100 * state.cur_i / state.cur_n)
        cur.add_row(Text.assemble((_bar(state.cur_i, state.cur_n), "green"),
                                  (f"  {pct:3d}%  ", "bold"),
                                  (f"{state.cur_i}/{state.cur_n} ", "dim"),
                                  (state.cur_file[-42:], "dim")))

    rpm, ppm = _rates(state)
    tot = Table.grid(expand=True)
    tot.add_column(justify="left")
    tot.add_column(justify="right")
    tot.add_row(
        Text.assemble(("pairs ", "dim"), (f"{state.pairs_total:,}", "bold green"),
                      (f"  (+{state.repo_pairs} this repo)   ", "dim"),
                      ("skips ", "dim"), (f"{state.skips_total:,}", "red")),
        Text(f"{rpm:.1f} repos/min · {ppm:.0f} pairs/min", style="dim"))

    recent = Table(box=box.SIMPLE, expand=True, show_header=True, header_style="dim",
                   pad_edge=False)
    recent.add_column("", width=2)
    recent.add_column("repo", ratio=2, no_wrap=True)
    recent.add_column("result", ratio=1, no_wrap=True)
    for status, repo, note in state.recent:
        mark, style = ("✓", "green") if status == "done" else ("✗", "red")
        recent.add_row(Text(mark, style=style), Text(repo, style="dim"), Text(note, style=style))
    for level, msg in list(state.log)[:3]:
        style = {"warn": "yellow", "info": "dim"}.get(level, "dim")
        recent.add_row(Text("·", style=style), Text(msg[:60], style=style), Text("", ""))

    body = Table.grid(expand=True)
    body.add_column()
    body.add_row(head)
    body.add_row(Text("─" * 3, style="dim"))
    body.add_row(cur)
    body.add_row(Text("─" * 3, style="dim"))
    body.add_row(tot)
    body.add_row(recent)

    title = "harvesting complete" if state.done else "disasm harvest"
    return Panel(body, title=f"[bold]{title}[/]  ·  {_elapsed(state)} elapsed",
                 subtitle="[dim]Ctrl-C once: finish repo · twice: abort[/]",
                 border_style="green" if state.done else "cyan", box=box.ROUNDED)


def run_with_dashboard(work, limit=None):
    """Run work(emit) with a live rich view. Returns work's result."""
    from rich.live import Live
    from rich.console import Console

    state = DashState(limit=limit)
    lock = threading.Lock()

    def emit(e):
        with lock:
            apply(state, e)

    class _Renderable:
        def __rich__(self):
            with lock:
                return _render(state)

    console = Console()
    result = None
    with Live(_Renderable(), console=console, refresh_per_second=4, screen=False):
        try:
            result = work(emit)
        finally:
            with lock:
                state.done = True
            time.sleep(0.4)  # let the final frame paint
    console.print(f"[green]done[/] · processed {state.processed} repos · "
                  f"{state.pairs_total:,} pairs · {state.skips_total:,} skips")
    return result
