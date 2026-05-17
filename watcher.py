# watcher.py
# ----------
# The polling loop that keeps an eye on the target folder.
# This runs indefinitely (until Ctrl+C) and relies on the scanner module to
# detect changes, and the vault module to actually save the backups.

import os
import sys
import time

from config import POLL_INTERVAL
from scanner import scan_folder, diff_snapshots
from vault import (
    get_vault_path,
    make_sure_vault_exists,
    load_last_snapshot,
    save_snapshot_index,
    save_delta_copy,
)


def watch_folder(target_folder):
    """
    Starts the monitoring loop on target_folder.

    Flow:
    1. Make sure the vault exists.
    2. Load the last known snapshot (or build a fresh baseline if first run).
    3. Poll every POLL_INTERVAL seconds: scan, diff, and back up if anything changed.
    4. Keep going until the user hits Ctrl+C.
    """
    if not os.path.isdir(target_folder):
        print(f"[error] '{target_folder}' is not a valid folder. Double check the path.")
        sys.exit(1)

    vault_path = get_vault_path(target_folder)
    make_sure_vault_exists(vault_path)

    abs_path = os.path.abspath(target_folder)
    print(f"\n[watch] Monitoring: {abs_path}")
    print(f"[watch] Poll interval: {POLL_INTERVAL}s   |   Vault: {vault_path}")
    print(f"[watch] Press Ctrl+C to stop.\n")

    previous_snapshot = load_last_snapshot(vault_path)

    if not previous_snapshot:
        print("[watch] No previous baseline found — scanning folder to establish one...")
        previous_snapshot = scan_folder(target_folder, vault_path)
        save_snapshot_index(vault_path, previous_snapshot)
        file_count = len(previous_snapshot)
        print(f"[watch] Baseline set. Tracking {file_count} file(s). Now watching for changes...\n")
    else:
        file_count = len(previous_snapshot)
        print(f"[watch] Loaded existing baseline ({file_count} file(s) tracked). Watching...\n")

    try:
        while True:
            time.sleep(POLL_INTERVAL)
            current_snapshot = scan_folder(target_folder, vault_path)
            changed, deleted = diff_snapshots(previous_snapshot, current_snapshot)

            if changed or deleted:
                print("[watch] Change detected!")

                for rel_path, change_type in changed:
                    label = "NEW FILE " if change_type == "new" else "MODIFIED "
                    print(f"  {label}  {rel_path}")

                for rel_path in deleted:
                    print(f"  DELETED   {rel_path}")

                # Only back up files that are still there (can't back up deleted ones)
                if changed:
                    ts, count = save_delta_copy(target_folder, vault_path, changed)
                    print(f"  -> {count} file(s) saved to vault snapshot [{ts}]\n")
                else:
                    print()

                previous_snapshot = current_snapshot
                save_snapshot_index(vault_path, current_snapshot)

    except KeyboardInterrupt:
        print("\n[watch] Watcher stopped. Your vault is intact.")
        sys.exit(0)
