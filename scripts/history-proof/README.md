# History #10328: reproducible macOS evidence

Run in the fork's `preview/10328-history-mac` branch. The application fix remains
the two-line change in `QueryHistory.vue`; this test infrastructure is separate.

## Why this route is faster

The previous run `36418871023` spent **51m44s** building a release Tauri app even
after a Rust cache hit; its test took **18s**. Release enables LTO and a single
codegen unit. The default rust-cache configuration excludes workspace crates.

The default workflow now starts the actual Vite frontend inside a small native
macOS WKWebView host compiled by Swift. It does not compile Rust, build database
drivers, or create a DMG. Both baseline and candidate use the same host, app,
OS, locale, mocks, inputs, and measurement code. Only `QueryHistory.vue` changes.

The optional `full_tauri` workflow input retains a complete packaged-app smoke
test. It uses a debug app without release LTO or DMG packaging and enables
`cache-workspace-crates`. That smoke test alone is **not** scrollbar proof.

## Run on a Mac

```sh
pnpm install --frozen-lockfile
python3 -m venv .history-venv
.history-venv/bin/python -m pip install Pillow==11.3.0
defaults write -g AppleShowScrollBars -string Always
.history-venv/bin/python scripts/history-proof/run.py --control-only --output history-proof-results
```

Run again with `WhenScrolling`, **without `--control-only`**, and a different output directory. The workflow
runs both settings in separate macOS jobs. On a personal Mac, record and restore
your previous `AppleShowScrollBars` preference afterwards. The test needs a GUI
session and permission to take window screenshots.

From Windows, push the preview branch to the fork and open the resulting
**History macOS evidence** Actions run. Download both `History-evidence-*`
artifacts. Do not treat a skipped full Tauri job as a passed integration test.

## What is exercised

- Real production frontend and History component, English labels verified,
  dark theme to match the issue video (`--theme light` is available separately).
- Baseline component from `e9b768285`, candidate from the checked-out commit.
- Widths 288px (video condition), 240px, and 600px (no overflow).
- Three close/open cycles per width, actual application resize handle.
- Native AppKit/Quartz input; trusted horizontal wheel events and scrollLeft
  movement must be observed. The last filter must become reachable.
  Wheel coordinate conversion follows WebKit's own
  [EventSenderProxy](https://github.com/WebKit/WebKit/blob/main/Tools/WebKitTestRunner/mac/EventSenderProxy.mm).
- System window screenshots during left/right scrolling, including native
  scrollbar rendering. No CSS scrollbar substitution or JavaScript scrollLeft
  manipulation is used.
- Search hit-testing, native focus, clearance, and frame-by-frame vertical
  stability. Screenshots are retained at every sampled scroll phase.

Authentication, migration, and empty history APIs are fixtures. Other backend
calls deliberately return unavailable. This harness does not verify database
queries, real persistence, Tauri IPC, or a release binary.

## Evidence and verdict

`result.json` records OS, commit, component hashes, dimensions, trusted wheel
events, per-frame positions and screenshot names. `comparison.png` is a labeled
contact sheet; original screenshots remain unaltered. A failed setup also saves
`failure.png`, page state, and logs whenever the host is reachable.

Exit 0 requires baseline **native scrollbar overlap** with a moving visible thumb,
candidate clearance >=8px on overflow, <=1px search movement, usable search,
working scroll in both variants, and matching moving scrollbar pixels in the
candidate. The detected candidate thumb must fit below the filter buttons and
above the search box. Exit 1 means the candidate violates the layout contract. Exit 2 means
the environment or reproduction evidence is inconclusive and must not be green.

`Always` is explicitly a compatibility control: the OS already reserves scrollbar
space in the baseline. `--control-only` still requires candidate layout and native
scrollbar evidence, but reports `CONTROL PASS` without claiming reproduction.
The companion `WhenScrolling` job must pass the baseline-failure gate. Both jobs
must pass; a control pass alone never proves the repair.

The 8px clearance rule is a protective layout contract, **not a measurement of
the original video's occlusion**. Review the old/new raw images against the
video before asserting that its exact visual symptom was reproduced. Pixel
matching is conservative and may return inconclusive for another theme or
scrollbar implementation. A frontend WKWebView pass must not be described as
a full packaged Tauri verification.

Local evidence-gate tests (also work on Windows):

```sh
python scripts/history-proof/test_verdict.py
```
