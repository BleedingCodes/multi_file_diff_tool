# Multi\-File Diff Tool

User manual · covers install, use, and modification

## Purpose

This is a single\-file Python program for comparing text files — configs, logs, exported reports, code snippets — against each other, all at once. Instead of opening a pairwise diff tool once per pair of files, you load any number of files and run one **all\-vs\-all** comparison: every pair gets diffed, a summary line tells you how many pairs matched and how many differ, and a shareable HTML report is one click away. It also does **3\-way merges** (base / ours / theirs), the kind of conflict resolution `git merge` does, using the same diffing engine.

It's built for anyone who needs to verify that several versions of a file actually match, or don't: sysadmins checking config drift across servers, QA comparing logs across environments, or a freelancer confirming a deliverable didn't drift between drafts.

It runs as a desktop GUI or headless on the command line, and needs nothing beyond the Python standard library — no `pip install`, ever.

## Installation

### Requirements

| Requirement | Needed for | Notes |
| --- | --- | --- |
| Python 3.9 or newer | Everything | Check with `python3 --version` |
| `tkinter` | GUI mode only | Bundled with Python on Windows and macOS. On Linux it's often a separate package. |

The command\-line mode needs **only** Python itself — no `tkinter`, no external packages, nothing to install.

### Step by step

1. Save `multi_file_diff_tool.py` anywhere on your computer — there's no installer and no setup script to run.

2. Confirm Python is available:
   
   ```bash
   python3 --version
   ```
   
   Anything 3.9 or later works.

3. Confirm `tkinter` is available (only needed if you plan to use the GUI):
   
   ```bash
   python3 -c "import tkinter"
   ```
   
   No output means it's fine. If you see `ModuleNotFoundError: No module named 'tkinter'`, install it for your platform:
   
   - **Debian/Ubuntu:** `sudo apt install python3-tk`
   - **Fedora:** `sudo dnf install python3-tkinter`
   - **macOS (python.org installer) / Windows:** already included

4. Run it:
   
   ```bash
   python3 multi_file_diff_tool.py
   ```
   
   That's the whole install. There's nothing to uninstall beyond deleting the file.

No `tkinter`? The command\-line mode still works completely — it's a separate code path that never imports `tkinter` at all. See **Using the Command Line** below.

## Using the GUI

Launch with no arguments:

```bash
python3 multi_file_diff_tool.py
```

### 1\. Load files

Click **Add File(s)** and select one or more files (multi\-select works in the file dialog). Each one appears in the list by filename. Click **Remove Selected** to drop files you no longer need — select one or more rows first.

### 2\. Set comparison options (optional)

Three checkboxes above the button row:

| Option | Effect |
| --- | --- |
| Ignore whitespace | Collapses runs of spaces/tabs before comparing, so `root /var/www;` and `root  /var/www;` count as the same line |
| Ignore case | Compares case\-insensitively |
| Only show differing pairs | Hides identical pairs from the results window so it stays short with many files loaded |

These are read fresh each time you click a diff or merge button — change them and re\-run to see the effect.

### 3\. Run All\-vs\-All Diff

With at least 2 files loaded, click **All\-vs\-All Diff**. A new window opens with:

- A **summary line** at the top — files loaded, pairs compared, how many are identical vs. differ, and total added/removed line counts.
- One **section per pair**. Identical pairs collapse to a single line. Differing pairs show a colorized diff (green \= added, red \= removed, blue \= file/hunk headers) with a **Show/Hide** toggle so the window stays scannable past 4–5 files.
- An **Export HTML Report** button, top right — saves a standalone `.html` file with a side\-by\-side, word\-level\-highlighted diff for every pair, and opens it in your browser automatically. This file needs nothing else to view or share; send it to anyone.

### 4\. Run a 3\-Way Merge

Needs at least 3 files loaded. Click **3\-Way Merge...** A small dialog asks you to assign three of your loaded files to roles:

- **Base** — the common ancestor both versions started from
- **Ours** — your version
- **Theirs** — the other version

Pick three different files and click **Merge**. The results window shows the merged text: unchanged lines plain, your side of any conflict in green, their side in red, and `<<<<<<<` / `=======` / `>>>>>>>` conflict markers in blue. The header line tells you the conflict count, or that it merged cleanly. Click **Save Merged File** to write it to disk — if conflicts remain, you'll still need to open the file and resolve the marked sections by hand (that part isn't automatic in any merge tool, this one included).

## Using the Command Line

The CLI covers the same two operations — all\-vs\-all diff and 3\-way merge — and needs no `tkinter` at all.

### All\-vs\-all diff

```bash
python3 multi_file_diff_tool.py file1.txt file2.txt file3.txt
```

| Flag | Effect |
| --- | --- |
| `--ignore-whitespace` | Collapse whitespace before comparing |
| `--ignore-case` | Compare case\-insensitively |
| `--only-differences` | Omit identical pairs from the printed output |
| `--html REPORT.html` | Write the same shareable HTML report the GUI produces |

Example — audit five server configs and keep only the differences, plus a report to attach to a ticket:

```bash
python3 multi_file_diff_tool.py server1.conf server2.conf server3.conf \
  server4.conf server5.conf --only-differences --html drift_report.html
```

### 3\-way merge

```bash
python3 multi_file_diff_tool.py --merge base.txt ours.txt theirs.txt --output merged.txt
```

Files must be given **in that order** — base, then ours, then theirs. Without `--output`, the merged text prints to standard output instead of writing a file, which is useful for piping into something else.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Diff mode: ran fine. Merge mode: clean merge, no conflicts. |
| `1` | Diff mode: fewer than 2 readable files. Merge mode: conflicts remain in the output. |
| `2` | Bad arguments (missing files, wrong count for `--merge`, etc.) |

The `0`/`1` split in merge mode matches `git merge-file` and `diff3`'s own convention, so `--merge` drops straight into a CI step or pre\-commit hook: a nonzero exit means "something needs a human."

## Modifying the Program

Everything lives in one file, organized into four clearly marked sections — search for these banner comments to jump around:

| Section | Contains | You'd touch it to... |
| --- | --- | --- |
| **Core** | `DiffOptions`, `LoadedFile`, `PairResult`, `MergeResult`, `load_file`, `normalize_lines`, `compute_all_pairs`, `three_way_merge`, `build_html_report` | Change comparison logic, add a new option, change the merge algorithm, change the HTML report |
| **CLI** | `run_cli`, `_run_merge_cli` | Add a new command\-line flag |
| **GUI** | `MultiFileDiffApp`, `DiffResultsWindow`, `MergeRoleDialog`, `MergeResultsWindow` | Change buttons, layout, colors, window behavior |
| **Entry points** | `run_gui`, `main` | Change how the program decides GUI vs. CLI mode |

The **Core** section has zero `tkinter` dependency by design — every function there works from a plain Python script, a test file, or the CLI. That's deliberate: it's what let the CLI mode exist almost for free once the Core section was written, and it's the pattern worth copying whenever you add a new feature — write the logic first as a plain function, then wire a button or a flag to it, never the other way around.

### Common changes

**Change a diff color.** Both `DiffResultsWindow` and `MergeResultsWindow` (GUI section) have a `TAG_COLORS` dictionary near the top of the class — a hex color per tag name. Edit the hex value and re\-run; no other code needs to change.

**Add a new comparison option.** Three steps, all in the Core section first:

1. Add a field to `DiffOptions` (e.g. `ignore_blank_lines: bool = False`).
2. Use it inside `normalize_lines`.
3. Then wire it up: a `ttk.Checkbutton` \+ `tk.BooleanVar` in `MultiFileDiffApp._build_widgets` for the GUI, and an `argparse.add_argument(...)` in `run_cli` for the CLI. Both already follow this exact pattern for `ignore_whitespace` — copy it.

**Change default window sizes.** Each GUI window class sets `self.window.geometry("WIDTHxHEIGHT")` (or `self.root.geometry(...)` for the main window) in its `__init__`.

**Change the HTML report's look.** `build_html_report` in the Core section builds the page as a list of HTML strings joined at the end — the inline `<style>` block partway down controls fonts, spacing, and colors outside what `difflib.HtmlDiff` already styles.

### Testing a change

There's no test suite, but the CLI path makes manual testing fast because it needs no display:

```bash
# 1. Check for syntax errors
python3 -m py_compile multi_file_diff_tool.py

# 2. Make a couple of throwaway test files
printf 'a\nb\nc\n' > t1.txt
printf 'a\nB\nc\n' > t2.txt

# 3. Run the CLI path and read the output
python3 multi_file_diff_tool.py t1.txt t2.txt
```

If you're touching `three_way_merge` specifically, sanity\-check it against the real thing before trusting it — `git merge-file --stdout` (part of any Git install) implements the same diff3\-style algorithm, so running the same three files through both and comparing output is a fast way to catch a mistake:

```bash
git merge-file --stdout ours.txt base.txt theirs.txt
python3 multi_file_diff_tool.py --merge base.txt ours.txt theirs.txt
```

Clean merges should match exactly; conflicting ones should agree on *which* pairs conflict even if the marker text differs slightly.
