"""/journal — a persistent, structured activity log for the collection system.

Every command run and update produced by the harvester is appended to a JSONL
file (survives the terminal window closing) AND forwarded to the live dashboard,
so the same stream feeds both the on-screen mini command-box and a durable record
you can replay later.

Event contract (what `Journal` forwards to the dashboard `emit`):
    {"type": "journal", "kind": <str>, "ts": <float>, ...}
  kinds:
    "cmd"   — a subprocess started:  {"argv": "git clone …", "cwd": <str|None>}
    "line"  — one line of command output: {"msg": <str>, "stream": "out"|"err"}
    "event" — a semantic milestone:  {"msg": <str>, "level": "info"|"warn"|"error", ...}

Producers (harvest/scrape/run_pipeline/env) call journal.cmd()/line()/event()
or the streaming helper journal.run(). Consumers (dashboard) render `type=="journal"`.
"""
import json
import os
import subprocess
import threading
import time
from collections import deque

DEFAULT_PATH = "dataset/journal.jsonl"


class Journal:
    def __init__(self, path=DEFAULT_PATH, emit=None, ring=400, echo=False):
        self.path = path
        self.emit = emit or (lambda e: None)
        self.echo = echo
        self.ring = deque(maxlen=ring)
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        self._fh = open(path, "a", buffering=1, encoding="utf-8")

    def _write(self, entry):
        entry.setdefault("ts", time.time())
        line = json.dumps(entry, ensure_ascii=False)
        with self._lock:
            self._fh.write(line + "\n")
            self.ring.append(entry)
        self.emit({"type": "journal", **entry})
        if self.echo:
            print(line, flush=True)

    # --- producer API ---
    def event(self, msg, level="info", **fields):
        self._write({"kind": "event", "msg": msg, "level": level, **fields})

    def cmd(self, argv, cwd=None):
        self._write({"kind": "cmd",
                     "argv": argv if isinstance(argv, str) else " ".join(map(str, argv)),
                     "cwd": cwd})

    def line(self, text, stream="out"):
        self._write({"kind": "line", "msg": text, "stream": stream})

    def run(self, argv, *, cwd=None, env=None, timeout=None):
        """Run a subprocess, streaming each output line into the journal.
        Returns (returncode, combined_output_str). stderr is merged into stdout."""
        self.cmd(argv, cwd=cwd)
        try:
            proc = subprocess.Popen(
                argv, cwd=cwd, env=env, text=True, bufsize=1,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        except FileNotFoundError as e:
            self.line(str(e), stream="err")
            return 127, str(e)
        out = []
        try:
            for ln in proc.stdout:
                ln = ln.rstrip("\n")
                out.append(ln)
                if ln:
                    self.line(ln)
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            self.line(f"[timeout after {timeout}s]", stream="err")
            return 124, "\n".join(out)
        return proc.returncode, "\n".join(out)

    def close(self):
        with self._lock:
            try:
                self._fh.close()
            except Exception:
                pass


# --- viewer:  python -m pipeline.journal [--follow] [--tail N] [--path P] ---

_C = {"cmd": "\033[36m", "line": "\033[90m", "event": "\033[37m",
      "warn": "\033[33m", "error": "\033[31m", "info": "\033[37m",
      "dim": "\033[90m", "rst": "\033[0m"}


def _fmt(entry, color=True):
    ts = time.strftime("%H:%M:%S", time.localtime(entry.get("ts", 0)))
    kind = entry.get("kind", "?")
    if kind == "cmd":
        body = "$ " + entry.get("argv", "")
        col = _C["cmd"]
    elif kind == "line":
        body = "  " + entry.get("msg", "")
        col = _C["line"]
    else:
        lvl = entry.get("level", "info")
        body = "• " + entry.get("msg", "")
        col = _C.get(lvl, _C["event"])
    if color:
        return f"{_C['dim']}{ts}{_C['rst']} {col}{body}{_C['rst']}"
    return f"{ts} {body}"


def main():
    import argparse
    ap = argparse.ArgumentParser(description="View the collection journal.")
    ap.add_argument("--path", default=DEFAULT_PATH)
    ap.add_argument("--tail", type=int, default=40, help="show the last N entries")
    ap.add_argument("--follow", "-f", action="store_true", help="follow new entries live")
    args = ap.parse_args()

    if not os.path.exists(args.path):
        print(f"no journal yet at {args.path}")
        return
    color = os.isatty(1)
    with open(args.path, encoding="utf-8") as fh:
        lines = fh.readlines()
    for ln in lines[-args.tail:]:
        try:
            print(_fmt(json.loads(ln), color))
        except json.JSONDecodeError:
            pass
    if not args.follow:
        return
    with open(args.path, encoding="utf-8") as fh:
        fh.seek(0, os.SEEK_END)
        try:
            while True:
                ln = fh.readline()
                if not ln:
                    time.sleep(0.3)
                    continue
                try:
                    print(_fmt(json.loads(ln), color))
                except json.JSONDecodeError:
                    pass
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
