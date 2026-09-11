# multi-file-diff-tool

Compare any number of text files against each other all at once — as a desktop
GUI or headless on the command line. No pip installs, ever. Standard library only.

---

## What It Does

Load two or more text files and run one **all-vs-all diff**: every unique pair
gets compared, a summary line shows how many pairs matched and how many differ,
and a shareable HTML report is one click away.

Also does **3-way merges** (base / ours / theirs) — the same conflict resolution
`git merge` does, using the same diff3-style algorithm. Useful as a standalone
merge tool or wired into a CI step via exit code.

Built for: sysadmins checking config drift across servers, QA comparing logs
across environments, developers resolving merge conflicts, anyone verifying that
several versions of a file actually match — or don't.

---

## Features

- **All-vs-all diff** — every unique pair from however many files you load
- **3-way merge** — base / ours / theirs, with `<<<<<<` / `=======` / `>>>>>>>` conflict markers
- **Desktop GUI** — tkinter, scrollable results, show/hide toggles per pair
- **CLI mode** — no tkinter required, works on headless Linux boxes
- **HTML report** — standalone, shareable, word-level highlighted, opens in browser automatically
- **Comparison options** — ignore whitespace, ignore case, show only differing pairs
- **Deterministic exit codes** — `0` clean, `1` conflicts/too few files, `2` bad args
- **Zero dependencies** — stdlib only: `tkinter`, `difflib`, `pathlib`, `itertools`, `argparse`

---

## Requirements

| Requirement | Needed for |
|---|---|
| Python 3.9+ | Everything |
| `tkinter` | GUI mode only |

CLI mode needs only Python. No `pip install`, no virtualenv, nothing.

**Install tkinter on Linux if needed:**
```bash
# Debian / Ubuntu
sudo apt install python3-tk

# Fedora
sudo dnf install python3-tkinter
```

On Windows and macOS, tkinter is bundled with the standard Python installer.

---

## Installation

```bash
git clone https://github.com/BleedingCodes/multi-file-diff-tool.git
cd multi-file-diff-tool
python3 multi_file_diff_tool.py
```

No setup script. No install step. One file.

---

## Usage

### GUI

```bash
python3 multi_file_diff_tool.py
```

1. Click **Add File(s)** — multi-select works
2. Set comparison options (ignore whitespace, ignore case, only show differences)
3. Click **All-vs-All Diff** — results open in a new window with a summary line and one section per pair
4. Click **Export HTML Report** — saves a standalone `.html` file and opens it in your browser

For 3-way merge: load at least 3 files, click **3-Way Merge...**, assign base / ours / theirs roles, click **Merge**. Save the result with **Save Merged File**.

### CLI — All-vs-all diff

```bash
python3 multi_file_diff_tool.py file1.txt file2.txt file3.txt
```

| Flag | Effect |
|---|---|
| `--ignore-whitespace` | Collapse whitespace before comparing |
| `--ignore-case` | Compare case-insensitively |
| `--only-differences` | Omit identical pairs from output |
| `--html REPORT.html` | Write a shareable HTML report |

Example — audit five server configs, output only differences, write a report:

```bash
python3 multi_file_diff_tool.py \
  server1.conf server2.conf server3.conf server4.conf server5.conf \
  --only-differences --html drift_report.html
```

### CLI — 3-way merge

```bash
python3 multi_file_diff_tool.py --merge base.txt ours.txt theirs.txt --output merged.txt
```

Order is always: base, ours, theirs. Without `--output`, merged text prints to stdout.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Diff: ran fine. Merge: clean, no conflicts |
| `1` | Diff: fewer than 2 readable files. Merge: conflicts remain |
| `2` | Bad arguments |

Exit code `1` on merge matches `git merge-file` and `diff3` convention — drops
straight into a CI step or pre-commit hook.

---

## Project Structure

```
multi-file-diff-tool/
├── multi_file_diff_tool.py    # entire program — one file
├── User_Manual.md             # detailed user manual with examples
├── LICENSE
└── README.md
```

The program is organized into four clearly marked internal sections:

| Section | Contains |
|---|---|
| **Core** | `DiffOptions`, `LoadedFile`, `PairResult`, `MergeResult`, diff logic, merge algorithm, HTML report builder |
| **CLI** | `run_cli`, `_run_merge_cli` |
| **GUI** | `MultiFileDiffApp`, `DiffResultsWindow`, `MergeRoleDialog`, `MergeResultsWindow` |
| **Entry points** | `run_gui`, `main` |

The Core section has zero tkinter dependency by design. Every function there
works from a plain Python script, the CLI, or a test file. The GUI and CLI are
just two different ways to drive the same logic.

---

## User Manual

See [`User_Manual.md`](User_Manual.md) for full documentation including:
- All GUI controls explained
- All CLI flags with examples
- How to modify the program (add options, change colors, change window sizes)
- How to test changes without a display

---

## Built by MainbyteLabs

Python tooling for electronics labs, hardware shops, and Linux-based tech teams.

[MainbyteLabs](https://github.com/MR-MainbyteLabs) ·
[LinkedIn](https://linkedin.com/in/michael-rivera-c0ding) ·
mr.mainbytelabs@gmail.com

---

## License

MIT License

Copyright (c) 2026 Michael Rivera

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
