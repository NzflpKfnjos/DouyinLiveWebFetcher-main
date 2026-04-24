# Performance Verification Runbook

This runbook is the verification/reporting lane for the project performance
optimization plan in `.omx/plans/prd-project-performance-optimization.md` and
uses `.omx/plans/test-spec-project-performance-optimization.md` as the source of
truth.

The goal is to prove, with reproducible evidence, that high-message CPU pressure
is reduced in the shared Python path used by both `console` and `web`, while web
UI behavior remains unchanged.

## Verification boundaries

- Do not use live-room-only measurements as the acceptance baseline; live traffic
  is too variable for before/after claims.
- Do not count browser UI changes as first-round performance wins. `webui/` files
  should remain behaviorally unchanged for this work.
- Prefer shared-path improvements in `liveMan.py` first. Web-only fan-out costs in
  `web_server.py` are tracked separately unless profiling shows they dominate.
- Use the same input fixture, command flags, Python version, host load, and run
  count for baseline and after-change measurements.

## Required proof checklist

### 1. Functional regression suite

Run this suite before and after optimization:

```bash
python3 -m unittest \
  tests.test_env_cookie \
  tests.test_fansclub_gift_events \
  tests.test_gift_banner_parsing \
  tests.test_gift_message_events
```

Passing result required: all 15 existing tests pass.

### 2. Static/runtime sanity checks

Run syntax compilation for the Python entry points touched by the performance
work and the smoke paths:

```bash
python3 -m py_compile main.py liveMan.py web_server.py tests/*.py
```

If additional Python benchmark modules are added, include them in this command.

### 3. Reproducible performance comparison

The benchmark/profile harness must support both modes with fixed input and
multiple repeated runs. The exact entry point may be supplied by the benchmark
lane, but the verification lane expects commands equivalent to:

```bash
python3 <perf-entry> --scenario high-message --mode console --runs 3 --output baseline-console.json
python3 <perf-entry> --scenario high-message --mode web --runs 3 --output baseline-web.json
python3 <perf-entry> --scenario high-message --mode console --runs 3 --output after-console.json
python3 <perf-entry> --scenario high-message --mode web --runs 3 --output after-web.json
```

Each output must include:

- scenario name and mode;
- input fixture identifier or checksum;
- run count and per-run elapsed time;
- median elapsed time;
- top three cProfile hotspots by cumulative time;
- shared-path time and web-only time when running in `web` mode;
- Git commit or diff identifier used for the run.

The primary pass condition is lower median elapsed time in the after-change runs
for the same input and command. If a mode is statistically flat because the
optimized path is a subset of the total run, the report must show that the target
hotspot's cumulative time decreased and that total median time did not regress.

### 4. Before/after report template

Use this table in the final verification report:

| Mode | Metric | Baseline median | After median | Delta | Result |
| --- | --- | ---: | ---: | ---: | --- |
| console | total elapsed | TBD | TBD | TBD | PASS/FAIL |
| console | primary hotspot cumtime | TBD | TBD | TBD | PASS/FAIL |
| web | total elapsed | TBD | TBD | TBD | PASS/FAIL |
| web | shared-path cumtime | TBD | TBD | TBD | PASS/FAIL |
| web | web-only fan-out/SSE cumtime | TBD | TBD | TBD | PASS/FAIL/Tracked |

Also record the top hotspot names before and after optimization. This prevents a
claim of improvement from hiding a new dominant hotspot.

### 5. Console smoke

A smoke run requires a real live id and valid cookie configuration when the
upstream service requires it:

```bash
python3 main.py --mode console --live-id <room_id>
```

Pass criteria:

- process starts without argument/import errors;
- fetch loop reaches message processing or a clear upstream authentication/network
  response;
- no local traceback is introduced by the optimization.

### 6. Web smoke

Use an unused local port to avoid collisions:

```bash
python3 main.py --mode web --live-id <room_id> --host 127.0.0.1 --port 8000
```

Then verify:

```bash
curl -fsS http://127.0.0.1:8000/ >/tmp/douyin-web-index.html
curl -fsS http://127.0.0.1:8000/app.js >/tmp/douyin-web-app.js
curl -fsS http://127.0.0.1:8000/api/messages
```

Pass criteria:

- the web server starts;
- static UI assets load;
- `/api/messages` returns JSON with an `items` list;
- SSE remains available at `/events` when a client connects;
- no `webui/` behavior files changed unless explicitly approved in a later plan.

## Residual-risk reporting

If any acceptance check cannot be fully executed, report it explicitly as a
residual risk instead of converting it into a pass. Common examples:

- no real live id/cookie was available for live smoke;
- benchmark harness exists but only emits total elapsed time, not hotspot splits;
- web-only SSE serialization remains a secondary hotspot after shared-path work;
- host CPU noise makes a 3-run comparison inconclusive.

## Current pre-integration baseline captured by verification lane

On the worker-3 pre-integration branch, before benchmark and runtime lanes are
merged, the existing functional regression suite passed on a fresh verification
run:

```text
Ran 15 tests in 11.653s
OK
```

Additional pre-integration sanity checks:

```text
python3 -m py_compile main.py liveMan.py web_server.py tests/*.py
# PASS: command exited 0 with no output

python3 main.py --help
# PASS: argparse help rendered for --live-id, --mode, --host, --port, --cookie

python3 main.py --mode web --live-id smoke-test --host 127.0.0.1 --port 8765
curl -fsS http://127.0.0.1:8765/
curl -fsS http://127.0.0.1:8765/app.js
curl -fsS http://127.0.0.1:8765/api/messages
# PASS: static assets loaded and /api/messages returned {"items": []}
```

This is not a performance acceptance result. It is only the current functional
and local web-route baseline that later before/after performance evidence must
preserve. Live upstream smoke with a real room id/cookie remains required after
the runtime and benchmark lanes are integrated.
