import pipeline.dashboard as dashboard


def test_run_split_dashboard_runs_all_sides_and_returns_results():
    seen = {"a": 0, "b": 0}

    def mk(key, pairs):
        def work(emit):
            emit({"type": "stage", "repo": key, "stage": "generating"})
            emit({"type": "journal", "kind": "event", "msg": f"{key} fn", "level": "info"})
            emit({"type": "repo_done", "repo": key, "status": "done",
                  "pairs": pairs, "skipped": 0})
            seen[key] += 1
            return {"pairs": pairs}
        return work

    res = dashboard.run_split_dashboard(
        [("scraper", "cyan", mk("a", 3)), ("generator", "magenta", mk("b", 5))])
    assert res == [{"pairs": 3}, {"pairs": 5}]
    assert seen == {"a": 1, "b": 1}


def test_side_panel_renders_without_error():
    from rich.console import Console
    st = dashboard.DashState()
    dashboard.apply(st, {"type": "repo_done", "repo": "x", "status": "done",
                         "pairs": 9, "skipped": 1})
    panel = dashboard._side_panel(st, "generator", "magenta", width=40, height=16)
    # exercising the renderer end-to-end must not raise
    Console(file=open("/dev/null", "w"), width=40).print(panel)
