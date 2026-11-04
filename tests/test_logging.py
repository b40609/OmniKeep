"""App log records reach stderr (app/logging_setup.py), and radar, parsers and the cookie
bridge log through it instead of print()."""
import ast
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

EMIT = ("import logging; {setup}"
        "logging.getLogger('omnikeep.radar').info('radar cycle done'); "
        "logging.getLogger('omnikeep.cookie_bridge').warning('bridge failed')")


def _python(code):
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    return subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=60)


def _calls(path, predicate):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call) and predicate(node)]


def test_radar_parsers_and_cookie_bridge_do_not_print():
    is_print = lambda c: isinstance(c.func, ast.Name) and c.func.id == "print"  # noqa: E731
    files = sorted((REPO / "app/radar").rglob("*.py")) + sorted((REPO / "app/parsers").rglob("*.py"))
    found = [f"{f.relative_to(REPO)}:{c.lineno}" for f in files for c in _calls(f, is_print)]
    assert found == []


def test_every_app_logger_is_under_the_configured_name():
    def get_logger(c):
        return isinstance(c.func, ast.Attribute) and c.func.attr == "getLogger"
    names = {}
    for f in (REPO / "app").rglob("*.py"):
        if f.name == "logging_setup.py":
            continue  # configures the "omnikeep" logger itself
        for c in _calls(f, get_logger):
            arg = c.args[0] if c.args else None
            names[f"{f.relative_to(REPO)}:{c.lineno}"] = arg.value if isinstance(arg, ast.Constant) else ast.unparse(arg)
    # Anything outside omnikeep.* has no handler and its INFO records vanish.
    stray = {where: n for where, n in names.items() if not str(n).startswith("omnikeep")}
    assert stray == {}


def test_setup_sends_app_records_to_stderr_once_and_keeps_stdout_clean():
    # Importing the MCP server runs FastMCP's logging.basicConfig on the root logger, as
    # app.main does; the app's records must still appear once, with time and level.
    setup = ("import app.mcp_server; "
             "from app.logging_setup import configure_logging; configure_logging(); configure_logging(); ")
    res = _python(EMIT.format(setup=setup))
    assert res.returncode == 0, res.stderr
    assert res.stdout == ""  # MCP stdio: stdout carries protocol messages only
    lines = res.stderr.splitlines()
    assert [line.split(" ", 2)[2] for line in lines] == [
        "INFO    omnikeep.radar: radar cycle done",
        "WARNING omnikeep.cookie_bridge: bridge failed",
    ]


def test_entry_points_set_up_logging():
    check = "import logging; print('handlers', len(logging.getLogger('omnikeep').handlers))"
    server = _python("import runpy, uvicorn; uvicorn.run = lambda *a, **k: None; "
                     "runpy.run_path('run.py', run_name='__main__'); " + check)
    assert server.stdout.splitlines()[-1] == "handlers 1", server.stderr
    mcp = _python("import sys; sys.argv = ['mcp']; import app.mcp_server as m; "
                  "m.mcp.run = lambda **k: None; m.main(); " + check)
    assert mcp.stdout.splitlines()[-1] == "handlers 1", mcp.stderr
