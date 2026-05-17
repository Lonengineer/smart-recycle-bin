# vault.py
# --------
# Everything related to the vault: creating it, saving backups, loading/saving
# the snapshot index, and the actual rollback logic.
# I kept this separate from scanner.py because scanning is a read-only concern,
# while vault operations actually write stuff to disk.

import os
import json
import shutil
from datetime import datetime

from config import VAULT_DIR_NAME


def get_vault_path(target_folder):
    """Constructs and returns the full path to the hidden vault directory."""
    return os.path.join(target_folder, VAULT_DIR_NAME)


def make_sure_vault_exists(vault_path):
    """
    Creates the vault directory if it isn't there yet.
    Called once at startup — harmless if the vault already exists.
    """
    if not os.path.exists(vault_path):
        os.makedirs(vault_path)
        print(f"[vault] Created backup vault at: {vault_path}")
    else:
        print(f"[vault] Using existing vault at: {vault_path}")


def load_last_snapshot(vault_path):
    """
    Reads the last recorded snapshot index from disk.
    The index is just a JSON dict mapping relative file paths to their MD5 hashes.
    If there's nothing saved yet, we return an empty dict — caller handles that case.
    """
    index_file = os.path.join(vault_path, "snapshot_index.json")
    if not os.path.exists(index_file):
        return {}
    try:
        with open(index_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        # Index file got corrupted somehow — unusual but let's handle it gracefully
        print("[warn] Snapshot index looks corrupted. Starting with a fresh baseline.")
        return {}


def save_snapshot_index(vault_path, snapshot):
    """
    Writes the current snapshot dict to disk so it survives between runs.
    Pretty-printed JSON makes it easy to inspect manually if needed.
    """
    index_file = os.path.join(vault_path, "snapshot_index.json")
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)


def save_delta_copy(target_folder, vault_path, changed_file_tuples):
    """
    Copies only the changed/new files into a timestamped subfolder inside the vault.
    We don't back up the whole folder every time — just the deltas. This keeps
    the vault lean even after many edits.

    Vault layout after a few changes:
        .my_vault/
            2026-05-17_14-30-22/   <- one snapshot per change event
                notes.txt
            2026-05-17_14-31-05/
                notes.txt
                subdir/code.py

    changed_file_tuples is a list of (rel_path, change_type) where
    change_type is either "new" or "modified".
    """
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_dir = os.path.join(vault_path, timestamp)
    os.makedirs(backup_dir, exist_ok=True)

    backed_up = 0
    for rel_path, change_type in changed_file_tuples:
        src = os.path.join(target_folder, rel_path)
        dst = os.path.join(backup_dir, rel_path)

        # Mirror the subfolder structure so rollback can reconstruct everything
        dst_dir = os.path.dirname(dst)
        if dst_dir:
            os.makedirs(dst_dir, exist_ok=True)

        try:
            shutil.copy2(src, dst)
            tag = "[new]" if change_type == "new" else "[mod]"
            print(f"  {tag} backed up: {rel_path}  ->  vault/{timestamp}/")
            backed_up += 1
        except (IOError, OSError) as e:
            print(f"  [warn] couldn't back up {rel_path}: {e}")

    return timestamp, backed_up


def get_sorted_backup_timestamps(vault_path):
    """
    Returns a sorted list of backup folder names from oldest to newest.
    We only pick up directories — the snapshot_index.json file is excluded naturally
    since it's not a directory.
    Sorting lexicographically works perfectly because of our YYYY-MM-DD_HH-MM-SS format.
    """
    try:
        entries = os.listdir(vault_path)
    except FileNotFoundError:
        return []

    timestamps = [
        e for e in entries
        if os.path.isdir(os.path.join(vault_path, e))
    ]
    timestamps.sort()
    return timestamps


def list_all_backups(vault_path):
    """
    Prints a summary of all backups currently in the vault.
    Useful for debugging or if we want to add a 'history' command later.
    """
    all_ts = get_sorted_backup_timestamps(vault_path)
    if not all_ts:
        print("[vault] No backups found.")
        return
    print(f"[vault] {len(all_ts)} backup(s) on record:")
    for i, ts in enumerate(all_ts, 1):
        backup_dir = os.path.join(vault_path, ts)
        # Count files in this snapshot
        file_count = sum(len(fs) for _, _, fs in os.walk(backup_dir))
        marker = " <- latest" if i == len(all_ts) else ""
        print(f"  {i}. {ts}  ({file_count} file(s)){marker}")


def bring_back_last_version(target_folder):
    """
    Main rollback function. Grabs the most recent timestamped backup from the vault
    and copies those files back into the target folder.

    We're doing a selective restore, not a full wipe-and-replace — so any files
    that were created after the last backup and aren't in the vault stay untouched.
    That felt like the safer behaviour.
    """
    # Need scanner here to refresh the index after rollback — importing locally
    # to avoid a circular import (scanner doesn't import vault, so it's fine)
    from scanner import scan_folder

    if not os.path.isdir(target_folder):
        print(f"[error] The folder '{target_folder}' doesn't exist. Nothing to roll back to.")
        return False

    vault_path = get_vault_path(target_folder)

    if not os.path.exists(vault_path):
        print("[error] No vault found here. Have you run 'watch' on this folder before?")
        return False

    all_backups = get_sorted_backup_timestamps(vault_path)

    if not all_backups:
        print("[error] The vault folder exists but there are no backups inside it yet.")
        return False

    # Grab the most recent one — last in lexicographic order = newest timestamp
    latest_ts = all_backups[-1]
    backup_dir = os.path.join(vault_path, latest_ts)

    print(f"[rollback] Found {len(all_backups)} backup(s). Restoring the latest:")
    print(f"[rollback] Timestamp: {latest_ts}")
    print(f"[rollback] Source:    {backup_dir}\n")

    restored_count = 0
    for root, dirs, files in os.walk(backup_dir):
        for filename in files:
            backed_up_file = os.path.join(root, filename)
            rel_path = os.path.relpath(backed_up_file, backup_dir)
            restore_to = os.path.join(target_folder, rel_path)

            restore_dir = os.path.dirname(restore_to)
            if restore_dir:
                os.makedirs(restore_dir, exist_ok=True)

            try:
                shutil.copy2(backed_up_file, restore_to)
                print(f"  [restored] {rel_path}")
                restored_count += 1
            except (IOError, OSError) as e:
                print(f"  [warn] couldn't restore {rel_path}: {e}")

    print()
    if restored_count == 0:
        print("[rollback] Backup folder was empty. Nothing was actually restored.")
        return False

    print(f"[rollback] Done! {restored_count} file(s) restored from backup [{latest_ts}].")

    # Refresh the snapshot index so the next 'watch' run has an accurate baseline
    fresh_snapshot = scan_folder(target_folder, vault_path)
    save_snapshot_index(vault_path, fresh_snapshot)
    print("[rollback] Snapshot index refreshed.")
    return True
