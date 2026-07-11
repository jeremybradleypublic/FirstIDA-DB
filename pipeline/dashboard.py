"""A clean live terminal dashboard (rich) for the harvest run. The harvester
calls emit(event); this module renders shared state. No business logic here.

All widths/heights are derived from the live console size on every render, so
the layout adapts when the terminal is resized. On a real TTY the dashboard
runs in the alternate screen buffer (Live(screen=True)), which repaints the
whole screen each frame — no duplicated/garbled frames on resize and no
scrollback spam; a final snapshot is printed after the run so the result
persists in normal scrollback."""
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
    # journal stream for the "activity" mini-box: (kind, text, aux)
    #   ("cmd",  argv, "")           ("line", msg, stream)         ("event", msg, level)
    cmdlog: deque = field(default_factory=lambda: deque(maxlen=200))
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
    elif t == "journal":
        kind = e.get("kind", "")
        if kind == "cmd":
            state.cmdlog.append(("cmd", e.get("argv", ""), ""))
        elif kind == "line":
            state.cmdlog.append(("line", e.get("msg", ""), e.get("stream", "out")))
        elif kind == "event":
            state.cmdlog.append(("event", e.get("msg", ""), e.get("level", "info")))


def _bar(i, n, width):
    width = max(1, width)
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


def _cmd_panel(state: DashState, lines: int):
    """The 'activity' mini-box: a scrolling view of the journal stream
    ($ command headers, dim output lines, colored milestones). Fixed height
    (lines + 2 border rows); each row truncates with an ellipsis, never wraps."""
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich import box

    grid = Table.grid(expand=True)
    grid.add_column(no_wrap=True, overflow="ellipsis")
    for kind, text, aux in list(state.cmdlog)[-lines:]:
        if kind == "cmd":
            row = Text("$ " + text, style="bold cyan", no_wrap=True, overflow="ellipsis")
        elif kind == "line":
            style = "red dim" if aux == "err" else "dim"
            row = Text("  " + text, style=style, no_wrap=True, overflow="ellipsis")
        else:  # event
            style = {"warn": "yellow", "error": "bold red"}.get(aux, "green")
            row = Text("• " + text, style=style, no_wrap=True, overflow="ellipsis")
        grid.add_row(row)
    return Panel(grid, title="[dim]activity[/]", title_align="left",
                 border_style="dim", box=box.ROUNDED, padding=(0, 1),
                 height=lines + 2)


def _render(state: DashState, width: int, height: int):
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.table import Table
    from rich.text import Text
    from rich import box

    width = max(24, width)
    height = max(8, height)
    inner = width - 4  # outer panel borders + padding

    c = state.counts
    head = Table.grid(expand=True)
    head.add_column(justify="left", no_wrap=True, overflow="ellipsis")
    head.add_column(justify="right", no_wrap=True, overflow="ellipsis")
    limit = "∞" if state.limit is None else str(state.limit)
    head.add_row(
        Text.assemble(("queued ", "dim"), (f"{c['queued']}  ", "cyan"),
                      ("running ", "dim"), (f"{c['running']}  ", "yellow"),
                      ("done ", "dim"), (f"{c['done']}  ", "green"),
                      ("failed ", "dim"), (f"{c['failed']}", "red"),
                      no_wrap=True, overflow="ellipsis"),
        Text(f"{state.processed}/{limit} this run", style="dim",
             no_wrap=True, overflow="ellipsis"))

    cur = Table.grid(expand=True)
    cur.add_column(justify="left", no_wrap=True, overflow="ellipsis")
    icon = {"cloning": "⬇", "compiling": "⚙", "discovering": "🔎"}.get(state.stage, "•")
    cur.add_row(Text.assemble(("▶ ", "bold green"), (state.repo, "bold"),
                              ("   ", ""), (f"{icon} {state.stage}", "yellow"),
                              no_wrap=True, overflow="ellipsis"))
    if state.cur_n:
        pct = int(100 * state.cur_i / state.cur_n)
        counts_s = f"{state.cur_i}/{state.cur_n} "
        # bar scales with the terminal; the file path gets whatever is left
        bar_w = max(8, min(inner // 2, inner - len(counts_s) - 24))
        file_room = max(6, inner - bar_w - 8 - len(counts_s))
        f = state.cur_file
        if len(f) > file_room:
            f = "…" + f[-(file_room - 1):]
        cur.add_row(Text.assemble((_bar(state.cur_i, state.cur_n, bar_w), "green"),
                                  (f"  {pct:3d}%  ", "bold"),
                                  (counts_s, "dim"),
                                  (f, "dim"),
                                  no_wrap=True, overflow="ellipsis"))

    rpm, ppm = _rates(state)
    tot = Table.grid(expand=True)
    tot.add_column(justify="left", no_wrap=True, overflow="ellipsis")
    tot.add_column(justify="right", no_wrap=True, overflow="ellipsis")
    tot.add_row(
        Text.assemble(("pairs ", "dim"), (f"{state.pairs_total:,}", "bold green"),
                      (f"  (+{state.repo_pairs} this repo)   ", "dim"),
                      ("skips ", "dim"), (f"{state.skips_total:,}", "red"),
                      no_wrap=True, overflow="ellipsis"),
        Text(f"{rpm:.1f} repos/min · {ppm:.0f} pairs/min", style="dim",
             no_wrap=True, overflow="ellipsis"))

    # --- height budget (everything below derives from the console height) ---
    fixed = 1 + 1 + (2 if state.cur_n else 1) + 1 + 1     # head, rule, cur, rule, tot
    avail = max(0, height - 2 - fixed)                    # rows left inside the outer panel
    min_cmd = 3 + 2                                       # smallest useful activity box
    show_recent = bool(state.recent or state.log) and avail >= min_cmd + 4
    recent = None
    recent_h = 0
    if show_recent:
        rows = []
        for status, repo, note in state.recent:
            mark, style = ("✓", "green") if status == "done" else ("✗", "red")
            rows.append((Text(mark, style=style), Text(repo, style="dim"), Text(note, style=style)))
        for level, msg in list(state.log)[:2]:
            style = {"warn": "yellow", "info": "dim"}.get(level, "dim")
            rows.append((Text("·", style=style), Text(msg, style=style), Text("", "")))
        max_rows = min(len(rows), 4, max(1, avail - min_cmd - 2))
        rows = rows[:max_rows]
        recent = Table(box=box.SIMPLE, expand=True, show_header=True, header_style="dim",
                       pad_edge=False)
        recent.add_column("", width=2)
        recent.add_column("repo", ratio=2, no_wrap=True, overflow="ellipsis")
        recent.add_column("result", ratio=1, no_wrap=True, overflow="ellipsis")
        for r in rows:
            recent.add_row(*r)
        recent_h = len(rows) + 2                          # header + separator + rows
    cmd_lines = max(1, avail - recent_h - 2)              # activity box content rows

    body = Table.grid(expand=True)
    body.add_column()
    body.add_row(head)
    body.add_row(Rule(style="dim"))
    body.add_row(cur)
    body.add_row(Rule(style="dim"))
    body.add_row(tot)
    if recent is not None:
        body.add_row(recent)
    body.add_row(_cmd_panel(state, cmd_lines))

    title = "harvesting complete" if state.done else "disasm harvest"
    return Panel(body, title=f"[bold]{title}[/]  ·  {_elapsed(state)} elapsed",
                 subtitle="[dim]Ctrl-C once: finish repo · twice: abort[/]",
                 border_style="green" if state.done else "cyan", box=box.ROUNDED,
                 height=height)


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
        def __rich_console__(self, console, options):
            with lock:
                h = options.height or console.size.height
                yield _render(state, options.max_width, h)

    console = Console()
    result = None
    # Alt-screen mode repaints the full screen every frame, so resizing the
    # terminal (larger or smaller) never leaves duplicated frames or fills the
    # scrollback; vertical_overflow="crop" guards the resize race where the
    # frame is momentarily taller than the shrunken terminal. On non-TTY
    # output (pipes/CI) fall back to plain incremental rendering.
    use_screen = console.is_terminal
    with Live(_Renderable(), console=console, refresh_per_second=4,
              screen=use_screen, vertical_overflow="crop"):
        try:
            result = work(emit)
        finally:
            with lock:
                state.done = True
            time.sleep(0.4)  # let the final frame paint
    if use_screen:
        # leaving the alt screen erased the dashboard; print one snapshot so
        # the final state survives in normal scrollback
        with lock:
            console.print(_render(state, console.size.width,
                                  min(console.size.height, 24)))
    console.print(f"[green]done[/] · processed {state.processed} repos · "
                  f"{state.pairs_total:,} pairs · {state.skips_total:,} skips")
    return result
