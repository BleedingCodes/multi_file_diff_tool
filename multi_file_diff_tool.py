"""
Multi-File Diff Tool
---------------------
Load any number of text files and compare every pair of them at once —
as a desktop GUI, or headless on the command line.

Design: the diffing logic (load / normalize / compare / report) has zero
tkinter dependency. The GUI is just one way to drive it; a CLI is another.
That split is what lets this run on a machine that doesn't even have
tkinter installed (common on minimal/headless Linux boxes) and is why
adding the CLI cost almost nothing.

Stdlib only: tkinter, difflib, pathlib, itertools, dataclasses, argparse,
webbrowser, datetime. No pip installs, ever.

Usage:
    GUI:    python3 multi_file_diff_tool.py
    CLI:    python3 multi_file_diff_tool.py file1 file2 [file3 ...] [options]
            --ignore-whitespace   collapse runs of whitespace before comparing
            --ignore-case         compare case-insensitively
            --only-differences    omit identical pairs from the output
            --html REPORT.html    write a colorized, shareable HTML report
    Merge:  python3 multi_file_diff_tool.py --merge BASE OURS THEIRS [--output MERGED_FILE]
            exit code 0 = clean merge, 1 = conflicts left (same convention as diff3/git)
"""

from __future__ import annotations

import argparse
import difflib
import itertools
import sys
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    _TKINTER_AVAILABLE = True
except ImportError:
    _TKINTER_AVAILABLE = False


# ======================================================================
# Core (no GUI dependency — usable from the GUI, the CLI, or a test file)
# ======================================================================


@dataclass
class DiffOptions:
    """Comparison settings, shared by every presentation layer."""
    ignore_whitespace: bool = False
    ignore_case: bool = False
    only_differences: bool = False  # display filter, not a comparison setting


@dataclass
class LoadedFile:
    """One file the user has added to the comparison list."""
    path: Path
    lines: list[str]  # file content, one string per element, read via pathlib


@dataclass
class PairResult:
    """The comparison outcome for exactly one pair of files."""
    name_a: str
    name_b: str
    lines_a: list[str]      # the (possibly normalized) lines that were diffed
    lines_b: list[str]
    diff_lines: list[str]   # unified_diff output, ready to render
    added_count: int
    removed_count: int

    @property
    def is_identical(self) -> bool:
        return not self.diff_lines


def load_file(path: Path) -> LoadedFile:
    """Read one file into a LoadedFile. Raises OSError if it can't be read."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    return LoadedFile(path=path, lines=lines)


def normalize_lines(lines: list[str], options: DiffOptions) -> list[str]:
    """Apply ignore-whitespace / ignore-case before comparing.

    Note: this tool compares (and displays) the *normalized* text, rather
    than matching on normalized text while still displaying the raw
    original — that trickier approach is what tools like `git diff -w`
    do internally. Showing exactly what was compared keeps this tool
    simple and honest about what you're looking at.
    """
    normalized = lines
    if options.ignore_whitespace:
        normalized = [" ".join(line.split()) for line in normalized]
    if options.ignore_case:
        normalized = [line.lower() for line in normalized]
    return normalized


def compute_all_pairs(
    loaded_files: list[LoadedFile], options: DiffOptions
) -> list[PairResult]:
    """Diff every unique pair of loaded files (all-vs-all)."""
    results: list[PairResult] = []

    for file_a, file_b in itertools.combinations(loaded_files, 2):
        lines_a = normalize_lines(file_a.lines, options)
        lines_b = normalize_lines(file_b.lines, options)

        diff_lines = list(
            difflib.unified_diff(
                lines_a, lines_b,
                fromfile=file_a.path.name, tofile=file_b.path.name,
                lineterm="",
            )
        )

        added_count = sum(
            1 for line in diff_lines if line.startswith("+") and not line.startswith("+++")
        )
        removed_count = sum(
            1 for line in diff_lines if line.startswith("-") and not line.startswith("---")
        )

        results.append(PairResult(
            name_a=file_a.path.name, name_b=file_b.path.name,
            lines_a=lines_a, lines_b=lines_b,
            diff_lines=diff_lines,
            added_count=added_count, removed_count=removed_count,
        ))

    return results


def format_summary_line(loaded_files: list[LoadedFile], pair_results: list[PairResult]) -> str:
    identical_pairs = sum(1 for pair in pair_results if pair.is_identical)
    differing_pairs = len(pair_results) - identical_pairs
    total_added = sum(pair.added_count for pair in pair_results)
    total_removed = sum(pair.removed_count for pair in pair_results)

    return (
        f"{len(loaded_files)} files loaded, {len(pair_results)} pairs compared — "
        f"{identical_pairs} identical, {differing_pairs} differ "
        f"(totals: +{total_added} / -{total_removed} lines)"
    )


@dataclass
class MergeResult:
    """The outcome of a 3-way merge of one base/ours/theirs triple."""
    base_name: str
    ours_name: str
    theirs_name: str
    merged_lines: list[str]
    conflict_count: int

    @property
    def has_conflicts(self) -> bool:
        return self.conflict_count > 0


def _changed_ranges(ops, side):
    """Every non-equal (tag, i1, i2) region from one side's diff-against-base
    opcodes, tagged with which side it came from."""
    return [(i1, i2, side) for tag, i1, i2, j1, j2 in ops if tag != "equal"]


def _find_clusters(ops_ours, ops_theirs):
    """Merge every changed region from both sides into maximal clusters of
    overlapping/touching base-index ranges (the standard "merge intervals"
    sweep). Each cluster is (lo, hi, {which side(s) touched it})."""
    changes = _changed_ranges(ops_ours, "ours") + _changed_ranges(ops_theirs, "theirs")
    changes.sort(key=lambda c: (c[0], c[1]))

    clusters = []
    for i1, i2, side in changes:
        if clusters and i1 <= clusters[-1][1]:
            lo, hi, sides = clusters[-1]
            clusters[-1] = (lo, max(hi, i2), sides | {side})
        else:
            clusters.append((i1, i2, {side}))
    return clusters


def _render_side(ops, side_lines, base, lo, hi):
    """Reconstruct what one side's content looks like for base range
    [lo, hi). Safe because "equal" ops (base == that side, content-wise)
    can be sliced at any sub-range, and every non-equal op that touches
    [lo, hi) is guaranteed fully contained in it by how clusters are built
    above — a cluster's bounds always expand to cover a whole op, never
    cut through the middle of one."""
    pieces = []
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            if i2 <= lo or i1 >= hi:
                continue
            start, end = max(i1, lo), min(i2, hi)
            pieces.extend(base[start:end])
        else:
            if i1 >= lo and i2 <= hi:
                pieces.extend(side_lines[j1:j2])
    return pieces


def three_way_merge(
    base_lines: list[str],
    ours_lines: list[str],
    theirs_lines: list[str],
    ours_label: str = "OURS",
    theirs_label: str = "THEIRS",
) -> tuple[list[str], int]:
    """3-way merge of ours/theirs against a common base, built entirely on
    two difflib comparisons (base-vs-ours and base-vs-theirs) — no external
    `diff3` or `git` binary involved.

    The idea: take every changed region from both sides' opcodes and sweep
    them into maximal clusters of overlapping/touching base ranges (a
    standard "merge intervals" pass). For each cluster:
      - if only one side touched it, take that side's version
      - if both sides made the *same* change, take it (no conflict)
      - if both sides changed it *differently*, that's a real conflict

    This is opcode-cluster based rather than anchor-based, which is the
    same algorithm used by this project's sibling tool,
    file_diff_viewer_threeway_merge.py — both tools now agree on every
    edge case, including two edits on directly adjacent lines with no
    unchanged line between them (those still conflict: there's no safe
    sync point proving the edits are independent, which matches how GNU
    diff3 and `git merge-file` behave too).
    """
    ops_ours = difflib.SequenceMatcher(None, base_lines, ours_lines, autojunk=False).get_opcodes()
    ops_theirs = difflib.SequenceMatcher(None, base_lines, theirs_lines, autojunk=False).get_opcodes()
    clusters = _find_clusters(ops_ours, ops_theirs)

    merged_lines: list[str] = []
    conflict_count = 0
    pos = 0
    for lo, hi, sides in clusters:
        merged_lines.extend(base_lines[pos:lo])  # unchanged gap before this cluster

        if sides == {"ours"}:
            merged_lines.extend(_render_side(ops_ours, ours_lines, base_lines, lo, hi))
        elif sides == {"theirs"}:
            merged_lines.extend(_render_side(ops_theirs, theirs_lines, base_lines, lo, hi))
        else:
            ours_piece = _render_side(ops_ours, ours_lines, base_lines, lo, hi)
            theirs_piece = _render_side(ops_theirs, theirs_lines, base_lines, lo, hi)
            if ours_piece == theirs_piece:
                merged_lines.extend(ours_piece)  # both sides made the same change
            else:
                conflict_count += 1
                merged_lines.append(f"<<<<<<< {ours_label}\n")
                merged_lines.extend(ours_piece)
                merged_lines.append("=======\n")
                merged_lines.extend(theirs_piece)
                merged_lines.append(f">>>>>>> {theirs_label}\n")
        pos = hi

    merged_lines.extend(base_lines[pos:])  # trailing unchanged tail
    return merged_lines, conflict_count


def build_html_report(
    loaded_files: list[LoadedFile], pair_results: list[PairResult], options: DiffOptions
) -> str:
    """Build one shareable HTML page: a summary plus a side-by-side,
    word-level-highlighted diff table for every differing pair.

    Uses difflib.HtmlDiff — a stdlib class most people never reach for —
    so this "premium" feature costs zero extra dependencies.
    """
    differ = difflib.HtmlDiff(wrapcolumn=100)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    page = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'><title>Multi-File Diff Report</title>",
        f"<style>{differ._styles}\n"
        "body{font-family:Arial,Helvetica,sans-serif;margin:2em;background:#fafafa;color:#222;}"
        "h1{font-size:1.4em;}"
        "h2{font-size:1.05em;margin-top:2em;border-bottom:1px solid #ccc;padding-bottom:4px;}"
        ".identical{color:#0a7d00;} .meta{color:#666;font-size:0.9em;}"
        "</style></head><body>",
        "<h1>Multi-File Diff Report</h1>",
        f"<p class='meta'>Generated {generated_at} &middot; "
        f"ignore whitespace: {options.ignore_whitespace} &middot; "
        f"ignore case: {options.ignore_case}</p>",
        f"<p><strong>{format_summary_line(loaded_files, pair_results)}</strong></p>",
        differ._legend,
    ]

    for pair in pair_results:
        if pair.is_identical:
            page.append(
                f"<h2>{pair.name_a} vs {pair.name_b}</h2>"
                "<p class='identical'>Identical — no differences.</p>"
            )
        else:
            page.append(
                f"<h2>{pair.name_a} vs {pair.name_b} "
                f"&mdash; +{pair.added_count} / -{pair.removed_count} lines</h2>"
            )
            page.append(differ.make_table(
                pair.lines_a, pair.lines_b,
                fromdesc=pair.name_a, todesc=pair.name_b,
                context=True, numlines=3,
            ))

    page.append("</body></html>")
    return "\n".join(page)


# ======================================================================
# CLI — no tkinter import required to reach this code path
# ======================================================================


def run_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="multi_file_diff_tool.py",
        description="Compare every pair among the given files (all-vs-all).",
    )
    parser.add_argument("files", nargs="+", help="two or more files (or exactly 3 with --merge)")
    parser.add_argument("--ignore-whitespace", action="store_true",
                         help="collapse runs of whitespace before comparing")
    parser.add_argument("--ignore-case", action="store_true",
                         help="compare case-insensitively")
    parser.add_argument("--only-differences", action="store_true",
                         help="omit identical pairs from the printed output")
    parser.add_argument("--html", metavar="REPORT.html",
                         help="write a colorized, shareable HTML report to this path")
    parser.add_argument("--merge", action="store_true",
                         help="3-way merge mode: treat the 3 files as BASE OURS THEIRS")
    parser.add_argument("--output", metavar="MERGED_FILE",
                         help="write the merged result here (--merge only); default is stdout")
    args = parser.parse_args(argv)

    if args.merge:
        return _run_merge_cli(args, parser)

    if len(args.files) < 2:
        parser.error("provide at least 2 files to compare")

    options = DiffOptions(
        ignore_whitespace=args.ignore_whitespace,
        ignore_case=args.ignore_case,
        only_differences=args.only_differences,
    )

    loaded_files: list[LoadedFile] = []
    for raw_path in args.files:
        path = Path(raw_path)
        try:
            loaded_files.append(load_file(path))
        except OSError as error:
            print(f"Skipping {path}: {error}", file=sys.stderr)

    if len(loaded_files) < 2:
        print("Need at least 2 readable files to compare.", file=sys.stderr)
        return 1

    pair_results = compute_all_pairs(loaded_files, options)

    print(format_summary_line(loaded_files, pair_results))
    print()
    for pair in pair_results:
        if pair.is_identical:
            if not options.only_differences:
                print(f"{pair.name_a} vs {pair.name_b}: identical")
            continue
        print(f"{pair.name_a} vs {pair.name_b}: +{pair.added_count} / -{pair.removed_count}")
        for line in pair.diff_lines:
            # Content lines keep the original file's "\n"; header/hunk
            # lines don't (lineterm=""). Strip it so print() doesn't
            # double up blank lines either way.
            print(line.rstrip("\n"))
        print()

    if args.html:
        html = build_html_report(loaded_files, pair_results, options)
        Path(args.html).write_text(html, encoding="utf-8")
        print(f"HTML report written to {args.html}")

    return 0


def _run_merge_cli(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if len(args.files) != 3:
        parser.error("--merge requires exactly 3 files, in order: BASE OURS THEIRS")

    base_path, ours_path, theirs_path = (Path(p) for p in args.files)
    try:
        base_file = load_file(base_path)
        ours_file = load_file(ours_path)
        theirs_file = load_file(theirs_path)
    except OSError as error:
        print(f"Could not read a file: {error}", file=sys.stderr)
        return 1

    merged_lines, conflict_count = three_way_merge(
        base_file.lines, ours_file.lines, theirs_file.lines,
        ours_label=ours_path.name, theirs_label=theirs_path.name,
    )
    merged_text = "".join(merged_lines)

    if args.output:
        Path(args.output).write_text(merged_text, encoding="utf-8")
        print(f"Merged output written to {args.output}", file=sys.stderr)
    else:
        print(merged_text, end="")

    # Exit codes follow the diff3/git merge-file convention: 0 = clean
    # merge, 1 = conflicts left in the output, so this is CI/script-friendly.
    if conflict_count:
        print(f"{conflict_count} conflict(s) found.", file=sys.stderr)
        return 1
    print("Clean merge, no conflicts.", file=sys.stderr)
    return 0


# ======================================================================
# GUI
# ======================================================================


class MultiFileDiffApp:
    """The main window: a file list, comparison options, and action buttons."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Multi-File Diff Tool")
        self.root.geometry("500x430")

        self.loaded_files: list[LoadedFile] = []
        self.ignore_whitespace_var = tk.BooleanVar(value=False)
        self.ignore_case_var = tk.BooleanVar(value=False)
        self.only_differences_var = tk.BooleanVar(value=False)

        self._build_widgets()

    def _build_widgets(self) -> None:
        list_frame = ttk.Frame(self.root, padding=10)
        list_frame.pack(fill="both", expand=True)

        ttk.Label(list_frame, text="Loaded files:").pack(anchor="w")

        listbox_frame = ttk.Frame(list_frame)
        listbox_frame.pack(fill="both", expand=True, pady=(5, 0))

        self.file_listbox = tk.Listbox(listbox_frame, selectmode="extended")
        self.file_listbox.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(
            listbox_frame, orient="vertical", command=self.file_listbox.yview
        )
        scrollbar.pack(side="right", fill="y")
        self.file_listbox.config(yscrollcommand=scrollbar.set)

        options_frame = ttk.Frame(self.root, padding=(10, 0))
        options_frame.pack(fill="x")
        ttk.Checkbutton(
            options_frame, text="Ignore whitespace", variable=self.ignore_whitespace_var
        ).pack(side="left")
        ttk.Checkbutton(
            options_frame, text="Ignore case", variable=self.ignore_case_var
        ).pack(side="left", padx=10)
        ttk.Checkbutton(
            options_frame, text="Only show differing pairs", variable=self.only_differences_var
        ).pack(side="left")

        button_frame = ttk.Frame(self.root, padding=10)
        button_frame.pack(fill="x")

        ttk.Button(button_frame, text="Add File(s)", command=self.add_files).pack(
            side="left", padx=(0, 5)
        )
        ttk.Button(
            button_frame, text="Remove Selected", command=self.remove_selected_files
        ).pack(side="left", padx=5)
        ttk.Button(
            button_frame, text="All-vs-All Diff", command=self.show_all_vs_all_diff
        ).pack(side="right")
        ttk.Button(
            button_frame, text="3-Way Merge...", command=self.show_merge_dialog
        ).pack(side="right", padx=(0, 5))

    # ---------- file management ----------

    def add_files(self) -> None:
        file_paths = filedialog.askopenfilenames(title="Select file(s) to add")
        if not file_paths:
            return  # user cancelled the dialog

        for raw_path in file_paths:
            path = Path(raw_path)
            try:
                loaded_file = load_file(path)
            except OSError as error:
                messagebox.showerror(
                    "Could not read file", f"Skipping {path.name}:\n{error}"
                )
                continue

            self.loaded_files.append(loaded_file)
            self.file_listbox.insert("end", path.name)

    def remove_selected_files(self) -> None:
        selected_indexes = self.file_listbox.curselection()
        if not selected_indexes:
            messagebox.showinfo(
                "Nothing selected", "Select one or more files to remove first."
            )
            return

        # Remove from the highest index down so deleting one entry doesn't
        # shift the position of the ones still waiting to be removed.
        for index in sorted(selected_indexes, reverse=True):
            del self.loaded_files[index]
            self.file_listbox.delete(index)

    # ---------- diffing ----------

    def show_all_vs_all_diff(self) -> None:
        if len(self.loaded_files) < 2:
            messagebox.showwarning(
                "Not enough files",
                "Load at least 2 files before running an all-vs-all diff.",
            )
            return

        options = DiffOptions(
            ignore_whitespace=self.ignore_whitespace_var.get(),
            ignore_case=self.ignore_case_var.get(),
            only_differences=self.only_differences_var.get(),
        )
        pair_results = compute_all_pairs(self.loaded_files, options)

        results_window = DiffResultsWindow(self.root, self.loaded_files, pair_results, options)
        results_window.build()

    # ---------- 3-way merge ----------

    def show_merge_dialog(self) -> None:
        if len(self.loaded_files) < 3:
            messagebox.showwarning(
                "Not enough files",
                "Load at least 3 files first: a common base, your version (ours), "
                "and the other version (theirs).",
            )
            return

        MergeRoleDialog(self.root, self.loaded_files, on_confirm=self._run_merge)

    def _run_merge(self, base_file: LoadedFile, ours_file: LoadedFile, theirs_file: LoadedFile) -> None:
        merged_lines, conflict_count = three_way_merge(
            base_file.lines, ours_file.lines, theirs_file.lines,
            ours_label=ours_file.path.name, theirs_label=theirs_file.path.name,
        )
        result = MergeResult(
            base_name=base_file.path.name,
            ours_name=ours_file.path.name,
            theirs_name=theirs_file.path.name,
            merged_lines=merged_lines,
            conflict_count=conflict_count,
        )
        results_window = MergeResultsWindow(self.root, result)
        results_window.build()


class MergeRoleDialog:
    """A small dialog to assign 3 loaded files to base / ours / theirs."""

    def __init__(
        self,
        parent: tk.Tk,
        loaded_files: list[LoadedFile],
        on_confirm,  # callback: (base, ours, theirs) -> None
    ) -> None:
        self.loaded_files = loaded_files
        self.on_confirm = on_confirm

        # Unique display strings even if two loaded files share a filename.
        self.choices = [f"{index + 1}. {file.path.name}" for index, file in enumerate(loaded_files)]

        self.window = tk.Toplevel(parent)
        self.window.title("Choose files to merge")
        self.window.resizable(False, False)

        self.base_var = tk.StringVar()
        self.ours_var = tk.StringVar()
        self.theirs_var = tk.StringVar()

        self._build_widgets()

    def _build_widgets(self) -> None:
        form = ttk.Frame(self.window, padding=15)
        form.pack(fill="both", expand=True)

        self._add_row(form, "Base (common ancestor):", self.base_var, default_index=0)
        self._add_row(form, "Ours:", self.ours_var, default_index=1)
        self._add_row(form, "Theirs:", self.theirs_var, default_index=2 if len(self.choices) > 2 else 0)

        button_row = ttk.Frame(form)
        button_row.pack(fill="x", pady=(10, 0))
        ttk.Button(button_row, text="Cancel", command=self.window.destroy).pack(side="right")
        ttk.Button(button_row, text="Merge", command=self._confirm).pack(side="right", padx=(0, 5))

    def _add_row(self, parent: ttk.Frame, label_text: str, variable: tk.StringVar, default_index: int) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text=label_text, width=20).pack(side="left")
        variable.set(self.choices[default_index])
        combobox = ttk.Combobox(row, textvariable=variable, values=self.choices, state="readonly", width=30)
        combobox.pack(side="left", fill="x", expand=True)

    def _confirm(self) -> None:
        selections = [self.base_var.get(), self.ours_var.get(), self.theirs_var.get()]
        if len(set(selections)) < 3:
            messagebox.showwarning(
                "Pick 3 different files", "Base, Ours, and Theirs must be 3 different files."
            )
            return

        indexes = [self.choices.index(choice) for choice in selections]
        base_file, ours_file, theirs_file = (self.loaded_files[i] for i in indexes)

        self.window.destroy()
        self.on_confirm(base_file, ours_file, theirs_file)


class MergeResultsWindow:
    """Shows the merged output, colorized, with a Save button."""

    TAG_COLORS = {
        "header": "#0033cc",   # blue  — conflict marker lines
        "ours": "#0a7d00",     # green — our side of a conflict
        "theirs": "#b30000",   # red   — their side of a conflict
    }

    def __init__(self, parent: tk.Tk, result: MergeResult) -> None:
        self.parent = parent
        self.result = result

        self.window = tk.Toplevel(parent)
        self.window.title("3-Way Merge Result")
        self.window.geometry("750x600")

    def build(self) -> None:
        top_bar = ttk.Frame(self.window, padding=10)
        top_bar.pack(fill="x")

        if self.result.has_conflicts:
            summary_text = (
                f"{self.result.ours_name} + {self.result.theirs_name} "
                f"(base: {self.result.base_name}) — {self.result.conflict_count} conflict(s)"
            )
        else:
            summary_text = (
                f"{self.result.ours_name} + {self.result.theirs_name} "
                f"(base: {self.result.base_name}) — clean merge, no conflicts"
            )
        ttk.Label(top_bar, text=summary_text, font=("TkDefaultFont", 10, "bold")).pack(side="left")
        ttk.Button(top_bar, text="Save Merged File", command=self.save_merged_file).pack(side="right")

        text_frame = ttk.Frame(self.window, padding=(10, 0, 10, 10))
        text_frame.pack(fill="both", expand=True)

        text_widget = tk.Text(text_frame, wrap="none")
        text_widget.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=text_widget.yview)
        scrollbar.pack(side="right", fill="y")
        text_widget.config(yscrollcommand=scrollbar.set)

        self._insert_colored_merge(text_widget, self.result.merged_lines)
        text_widget.config(state="disabled")

    def _insert_colored_merge(self, text_widget: tk.Text, merged_lines: list[str]) -> None:
        for tag, color in self.TAG_COLORS.items():
            text_widget.tag_configure(tag, foreground=color)

        # Track which side of a conflict block we're currently inside so
        # each line gets colored consistently with the diff view's
        # green=ours / red=theirs / blue=marker convention.
        side = "context"
        for line in merged_lines:
            if line.startswith("<<<<<<<"):
                side = "ours"
                text_widget.insert("end", line, "header")
            elif line == "=======\n":
                side = "theirs"
                text_widget.insert("end", line, "header")
            elif line.startswith(">>>>>>>"):
                side = "context"
                text_widget.insert("end", line, "header")
            elif side == "ours":
                text_widget.insert("end", line, "ours")
            elif side == "theirs":
                text_widget.insert("end", line, "theirs")
            else:
                text_widget.insert("end", line)

    def save_merged_file(self) -> None:
        save_path = filedialog.asksaveasfilename(
            title="Save merged file",
            initialfile=f"merged_{self.result.ours_name}",
        )
        if not save_path:
            return  # user cancelled

        try:
            Path(save_path).write_text("".join(self.result.merged_lines), encoding="utf-8")
        except OSError as error:
            messagebox.showerror("Could not save file", str(error))
            return

        if self.result.has_conflicts:
            messagebox.showinfo(
                "Saved with conflicts",
                f"Saved to:\n{save_path}\n\n"
                f"{self.result.conflict_count} conflict(s) still need manual resolution "
                "(look for <<<<<<< markers).",
            )
        else:
            messagebox.showinfo("Saved", f"Saved to:\n{save_path}")


class DiffResultsWindow:
    """A Toplevel window showing a colorized diff for every pair of files."""

    TAG_COLORS = {
        "header": "#0033cc",   # blue  — file/hunk header lines
        "added": "#0a7d00",    # green — lines only in the second file
        "removed": "#b30000",  # red   — lines only in the first file
    }

    def __init__(
        self,
        parent: tk.Tk,
        loaded_files: list[LoadedFile],
        pair_results: list[PairResult],
        options: DiffOptions,
    ) -> None:
        self.parent = parent
        self.loaded_files = loaded_files
        self.pair_results = pair_results
        self.options = options

        self.window = tk.Toplevel(parent)
        self.window.title("All-vs-All Diff Results")
        self.window.geometry("850x650")

    def build(self) -> None:
        top_bar = ttk.Frame(self.window, padding=10)
        top_bar.pack(fill="x")

        summary_text = format_summary_line(self.loaded_files, self.pair_results)
        ttk.Label(top_bar, text=summary_text, font=("TkDefaultFont", 10, "bold")).pack(
            side="left"
        )
        ttk.Button(top_bar, text="Export HTML Report", command=self.export_html_report).pack(
            side="right"
        )

        # Scrollable area: a Canvas holding an inner Frame, driven by a
        # Scrollbar. This is the standard tkinter pattern for "a list of
        # widgets that might not fit on screen."
        canvas = tk.Canvas(self.window, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.window, orient="vertical", command=canvas.yview)
        self.sections_frame = ttk.Frame(canvas)

        self.sections_frame.bind(
            "<Configure>",
            lambda event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self.sections_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=(0, 10))
        scrollbar.pack(side="right", fill="y", pady=(0, 10))

        self._populate_sections()

    def _populate_sections(self) -> None:
        hidden_identical_count = 0

        for pair in self.pair_results:
            if pair.is_identical and self.options.only_differences:
                hidden_identical_count += 1
                continue
            self._add_pair_section(pair)

        if hidden_identical_count:
            ttk.Label(
                self.sections_frame,
                text=f"({hidden_identical_count} identical pair(s) hidden — "
                     "uncheck 'Only show differing pairs' to see them)",
                foreground="#666",
            ).pack(anchor="w", padx=10, pady=5)

    def _add_pair_section(self, pair: PairResult) -> None:
        section = ttk.Frame(self.sections_frame, relief="groove", borderwidth=1)
        section.pack(fill="x", padx=5, pady=5)

        header_frame = ttk.Frame(section)
        header_frame.pack(fill="x")

        status_text = "identical" if pair.is_identical else f"+{pair.added_count} / -{pair.removed_count}"
        title = f"{pair.name_a}  vs  {pair.name_b}   —   {status_text}"

        if pair.is_identical:
            ttk.Label(header_frame, text=title).pack(side="left", padx=5, pady=5)
            return  # nothing else to show for an identical pair

        # Differing pairs get a Show/Hide toggle so the window stays
        # scannable once several file pairs are listed.
        text_widget = tk.Text(
            section, height=min(15, len(pair.diff_lines) + 1), wrap="none"
        )
        self._insert_colored_diff(text_widget, pair.diff_lines)
        text_widget.config(state="disabled")
        text_widget.pack(fill="both", expand=True, padx=5, pady=(0, 5))

        is_expanded = tk.BooleanVar(value=True)

        def toggle() -> None:
            if is_expanded.get():
                text_widget.pack_forget()
                toggle_button.config(text="Show")
            else:
                text_widget.pack(fill="both", expand=True, padx=5, pady=(0, 5))
                toggle_button.config(text="Hide")
            is_expanded.set(not is_expanded.get())

        toggle_button = ttk.Button(header_frame, text="Hide", width=6, command=toggle)
        toggle_button.pack(side="right", padx=5)
        ttk.Label(header_frame, text=title).pack(side="left", padx=5, pady=5)

    def _insert_colored_diff(self, text_widget: tk.Text, diff_lines: list[str]) -> None:
        for tag, color in self.TAG_COLORS.items():
            text_widget.tag_configure(tag, foreground=color)

        for line in diff_lines:
            display_line = line if line.endswith("\n") else line + "\n"

            if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
                text_widget.insert("end", display_line, "header")
            elif line.startswith("+"):
                text_widget.insert("end", display_line, "added")
            elif line.startswith("-"):
                text_widget.insert("end", display_line, "removed")
            else:
                text_widget.insert("end", display_line)

    def export_html_report(self) -> None:
        save_path = filedialog.asksaveasfilename(
            title="Save HTML report",
            defaultextension=".html",
            filetypes=[("HTML file", "*.html")],
            initialfile="diff_report.html",
        )
        if not save_path:
            return  # user cancelled

        html = build_html_report(self.loaded_files, self.pair_results, self.options)
        try:
            Path(save_path).write_text(html, encoding="utf-8")
        except OSError as error:
            messagebox.showerror("Could not save report", str(error))
            return

        messagebox.showinfo("Report saved", f"Saved to:\n{save_path}")
        try:
            webbrowser.open(Path(save_path).resolve().as_uri())
        except Exception:
            pass  # opening a browser is a nice-to-have, not essential


def run_gui() -> None:
    if not _TKINTER_AVAILABLE:
        script_name = Path(__file__).name
        print("tkinter isn't installed, so the GUI can't start.")
        print("Install it (e.g. 'sudo apt install python3-tk') or use CLI mode instead:")
        print(f"  python3 {script_name} file1.txt file2.txt [file3.txt ...] --html report.html")
        sys.exit(1)

    root = tk.Tk()
    MultiFileDiffApp(root)
    root.mainloop()


def main() -> None:
    if len(sys.argv) > 1:
        sys.exit(run_cli(sys.argv[1:]))
    run_gui()


if __name__ == "__main__":
    main()
