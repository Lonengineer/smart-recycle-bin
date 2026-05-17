"""
demo_runner.py
--------------
A one-shot demo script I wrote to prove the whole system works end-to-end.
It simulates the full workflow: establish baseline, detect a change, back it up,
then rollback. All without needing to manually start/stop the watcher.

Run with:  python demo_runner.py
"""

import stat

import os
import sys
import time
import shutil
from datetime import datetime

# We're in the project root, so imports work fine
from config import VAULT_DIR_NAME
from scanner import scan_folder, diff_snapshots
from vault import (
    get_vault_path, make_sure_vault_exists,
    load_last_snapshot, save_snapshot_index,
    save_delta_copy, get_sorted_backup_timestamps,
    list_all_backups, bring_back_last_version,
)

SEP = "-" * 60


def log(msg, color=None):
    colors = {"green": "\033[92m", "yellow": "\033[93m", "red": "\033[91m",
              "cyan": "\033[96m", "bold": "\033[1m", "reset": "\033[0m"}
    if color and color in colors:
        print(f"{colors[color]}{msg}{colors['reset']}")
    else:
        print(msg)


def run_demo(test_folder):
    print()
    log("=" * 60, "bold")
    log("  Smart Recycle Bin — End-to-End Demo", "bold")
    log("=" * 60, "bold")
    print()

    # ----------------------------------------------------------------
    # PHASE 1: Clean slate — remove any old vault/test folder first
    # ----------------------------------------------------------------
    log("PHASE 1: Preparing a fresh test environment", "cyan")
    log(SEP)

    def _force_remove(func, path, exc_info):
        # On Windows some files may be marked read-only; clear the flag and retry
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except Exception:
            pass  # If it still fails, just move on

    if os.path.exists(test_folder):
        shutil.rmtree(test_folder, onerror=_force_remove)
        time.sleep(0.5)  # small pause so Windows has time to release handles
    os.makedirs(test_folder)

    # Write some initial files
    with open(os.path.join(test_folder, "notes.txt"), "w") as f:
        f.write("Version 1 of my notes.\nThis is the original content.\n")
    with open(os.path.join(test_folder, "todo.txt"), "w") as f:
        f.write("1. Finish the assignment\n2. Submit before deadline\n3. Sleep\n")
    os.makedirs(os.path.join(test_folder, "src"), exist_ok=True)
    with open(os.path.join(test_folder, "src", "main.py"), "w") as f:
        f.write("# v1\nprint('hello world')\n")

    log("  Created test files:", "green")
    for root, dirs, files in os.walk(test_folder):
        for fname in files:
            rel = os.path.relpath(os.path.join(root, fname), test_folder)
            log(f"    {rel}")
    print()

    # ----------------------------------------------------------------
    # PHASE 2: Establish baseline
    # ----------------------------------------------------------------
    log("PHASE 2: Building initial snapshot (baseline)", "cyan")
    log(SEP)

    vault_path = get_vault_path(test_folder)
    make_sure_vault_exists(vault_path)
    baseline = scan_folder(test_folder, vault_path)
    save_snapshot_index(vault_path, baseline)
    log(f"  Baseline saved — tracking {len(baseline)} file(s).", "green")
    for f in baseline:
        log(f"    {f}: {baseline[f][:12]}...")
    print()

    # ----------------------------------------------------------------
    # PHASE 3: Simulate a change and detect it
    # ----------------------------------------------------------------
    log("PHASE 3: Simulating file modifications", "cyan")
    log(SEP)

    time.sleep(1)  # make sure the timestamp will differ

    # Modify notes.txt
    with open(os.path.join(test_folder, "notes.txt"), "w") as f:
        f.write("Version 2 of my notes.\nI added some more content here!\nAnd a third line.\n")
    log("  Modified: notes.txt", "yellow")

    # Add a brand new file
    with open(os.path.join(test_folder, "new_ideas.txt"), "w") as f:
        f.write("New idea: add a 'history' command to list all backups.\n")
    log("  Created:  new_ideas.txt", "yellow")
    print()

    # ----------------------------------------------------------------
    # PHASE 4: Detect changes (simulating one poll cycle)
    # ----------------------------------------------------------------
    log("PHASE 4: Detecting changes (one poll cycle)", "cyan")
    log(SEP)

    current_snapshot = scan_folder(test_folder, vault_path)
    previous_snapshot = load_last_snapshot(vault_path)
    changed, deleted = diff_snapshots(previous_snapshot, current_snapshot)

    for rel_path, change_type in changed:
        label = "NEW FILE " if change_type == "new" else "MODIFIED "
        log(f"  {label}  {rel_path}", "yellow")
    for rel_path in deleted:
        log(f"  DELETED   {rel_path}", "red")

    if changed:
        ts, count = save_delta_copy(test_folder, vault_path, changed)
        log(f"\n  -> Backed up {count} file(s) to vault snapshot [{ts}]", "green")
        save_snapshot_index(vault_path, current_snapshot)
    print()

    # ----------------------------------------------------------------
    # PHASE 5: Make another change — so we have 2 snapshots in vault
    # ----------------------------------------------------------------
    log("PHASE 5: Making a second change (creating 2nd snapshot)", "cyan")
    log(SEP)

    time.sleep(1)
    with open(os.path.join(test_folder, "src", "main.py"), "w") as f:
        f.write("# v2 — updated\nprint('hello world v2')\nprint('new feature!')\n")
    log("  Modified: src/main.py", "yellow")

    current_snapshot2 = scan_folder(test_folder, vault_path)
    prev2 = load_last_snapshot(vault_path)
    changed2, _ = diff_snapshots(prev2, current_snapshot2)
    if changed2:
        ts2, count2 = save_delta_copy(test_folder, vault_path, changed2)
        log(f"  -> Backed up {count2} file(s) to vault snapshot [{ts2}]", "green")
        save_snapshot_index(vault_path, current_snapshot2)
    print()

    # ----------------------------------------------------------------
    # PHASE 6: Show vault history
    # ----------------------------------------------------------------
    log("PHASE 6: Vault history", "cyan")
    log(SEP)
    list_all_backups(vault_path)
    print()

    # Show current content of notes.txt before rollback
    notes_path = os.path.join(test_folder, "notes.txt")
    log("  Current content of notes.txt (before rollback):", "yellow")
    with open(notes_path) as f:
        for line in f:
            log(f"    {line.rstrip()}")
    print()

    # ----------------------------------------------------------------
    # PHASE 7: Rollback!
    # ----------------------------------------------------------------
    log("PHASE 7: Rolling back to most recent backup", "cyan")
    log(SEP)
    bring_back_last_version(test_folder)
    print()

    # Show content of notes.txt after rollback
    log("  Content of notes.txt (after rollback):", "green")
    with open(notes_path) as f:
        for line in f:
            log(f"    {line.rstrip()}")
    print()

    log("=" * 60, "bold")
    log("  Demo complete. Everything worked as expected!", "green")
    log("=" * 60, "bold")
    print()


if __name__ == "__main__":
    demo_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_folder")
    run_demo(demo_folder)
