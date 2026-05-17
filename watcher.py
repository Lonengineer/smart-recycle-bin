# watcher.py  (v2 — Event-Driven)
# ---------------------------------
# Previous version: poll every 2 seconds regardless of whether anything changed.
# This version: hand the folder to the OS and BLOCK until something actually changes.
#
# We're using Windows' ReadDirectoryChangesW API through ctypes — no external libs,
# just us talking directly to the kernel. This is exactly how Dropbox, IDEs, and
# Git GUI tools do live file monitoring. Zero CPU wasted while idling.

import os
import sys
import ctypes
import ctypes.wintypes as wintypes
import struct

from config import VAULT_DIR_NAME
from scanner import scan_folder, diff_snapshots
from vault import (
    get_vault_path,
    make_sure_vault_exists,
    load_last_snapshot,
    save_snapshot_index,
    save_delta_copy,
)


# --- Windows API constants ---
# These come straight from the Windows SDK docs (winbase.h / winnt.h)
GENERIC_READ               = 0x80000000
FILE_SHARE_READ            = 0x00000001
FILE_SHARE_WRITE           = 0x00000002
FILE_SHARE_DELETE          = 0x00000004
OPEN_EXISTING              = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000  # required to open a *directory* handle

# Which kinds of changes we want the OS to notify us about
WATCH_FLAGS = (
    0x00000001 |  # FILE_NOTIFY_CHANGE_FILE_NAME   — file added, removed, renamed
    0x00000002 |  # FILE_NOTIFY_CHANGE_DIR_NAME    — subdirectory added/removed
    0x00000008 |  # FILE_NOTIFY_CHANGE_SIZE        — file grew or shrank
    0x00000010    # FILE_NOTIFY_CHANGE_LAST_WRITE  — file content was written
)

# Action codes inside FILE_NOTIFY_INFORMATION
FILE_ACTION_ADDED            = 1
FILE_ACTION_REMOVED          = 2
FILE_ACTION_MODIFIED         = 3
FILE_ACTION_RENAMED_OLD_NAME = 4
FILE_ACTION_RENAMED_NEW_NAME = 5

ACTION_LABELS = {
    FILE_ACTION_ADDED:            "NEW FILE ",
    FILE_ACTION_REMOVED:          "DELETED  ",
    FILE_ACTION_MODIFIED:         "MODIFIED ",
    FILE_ACTION_RENAMED_OLD_NAME: "RENAMED  ",
    FILE_ACTION_RENAMED_NEW_NAME: "RENAMED  ",
}

# Buffer for the raw change records. 64 KB is plenty for any realistic change burst.
BUFFER_SIZE = 65536


def _open_directory_handle(abs_path):
    """
    Opens a Windows HANDLE to a directory (not a file!).
    The FILE_FLAG_BACKUP_SEMANTICS flag is the magic that makes this work on dirs.
    Returns INVALID_HANDLE_VALUE (-1) on failure.
    """
    handle = ctypes.windll.kernel32.CreateFileW(
        abs_path,
        GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None,           # default security attributes
        OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS,
        None            # no template file
    )
    return handle


def _parse_notify_buffer(raw_buf, nbytes):
    """
    The OS gives back a packed binary blob containing FILE_NOTIFY_INFORMATION records.
    Each record looks like:
        DWORD  NextEntryOffset   — byte offset to the next record (0 = last)
        DWORD  Action            — what happened (added, removed, modified…)
        DWORD  FileNameLength    — length of the filename in *bytes* (UTF-16)
        WCHAR  FileName[]        — the filename itself (not null-terminated)

    We walk the linked list and decode each filename from UTF-16-LE.
    """
    results = []
    offset = 0
    while offset < nbytes:
        next_offset, action, name_len = struct.unpack_from('III', raw_buf, offset)
        name_start = offset + 12  # 3 × DWORD (4 bytes each) = 12 bytes header
        filename = raw_buf[name_start: name_start + name_len].decode('utf-16-le')
        results.append((action, filename))
        if next_offset == 0:
            break
        offset += next_offset
    return results


def watch_folder(target_folder):
    """
    Event-driven folder monitor — the real deal.

    How it works:
      1. We open a Windows directory handle with CreateFileW.
      2. We call ReadDirectoryChangesW, which BLOCKS (suspends the thread)
         until the OS kernel detects a real change in the directory tree.
      3. The OS wakes us up with a packed list of exactly what changed.
      4. We parse it, do a targeted hash check, and back up only what changed.
      5. Repeat from step 2.

    While we're blocked in step 2, this process uses ~0% CPU.
    We're not spinning in a loop or sleeping — we're just parked, waiting for
    the OS to tap us on the shoulder.
    """
    if not os.path.isdir(target_folder):
        print(f"[error] '{target_folder}' is not a valid folder.")
        sys.exit(1)

    vault_path = get_vault_path(target_folder)
    make_sure_vault_exists(vault_path)

    abs_path = os.path.abspath(target_folder)
    print(f"\n[watch] Monitoring  : {abs_path}")
    print(f"[watch] Mode        : Event-Driven via ReadDirectoryChangesW  (zero idle CPU)")
    print(f"[watch] Vault       : {vault_path}")
    print(f"[watch] Press Ctrl+C to stop.\n")

    # Build/load baseline snapshot
    previous_snapshot = load_last_snapshot(vault_path)
    if not previous_snapshot:
        print("[watch] No baseline found — scanning folder to build one...")
        previous_snapshot = scan_folder(target_folder, vault_path)
        save_snapshot_index(vault_path, previous_snapshot)
        print(f"[watch] Baseline set. Tracking {len(previous_snapshot)} file(s).\n")
    else:
        print(f"[watch] Loaded existing baseline ({len(previous_snapshot)} file(s) tracked).\n")

    # Get a directory handle from the OS
    handle = _open_directory_handle(abs_path)
    # INVALID_HANDLE_VALUE is 0xFFFFFFFF which equals -1 as signed, or a very large uint
    if handle in (wintypes.HANDLE(-1).value, -1, 0xFFFFFFFF):
        err = ctypes.GetLastError()
        print(f"[error] Could not open directory handle. Windows error: {err}")
        sys.exit(1)

    kernel32   = ctypes.windll.kernel32
    buf        = ctypes.create_string_buffer(BUFFER_SIZE)
    bytes_back = wintypes.DWORD(0)

    try:
        while True:
            # *** This call parks the thread here. CPU usage = ~0% while waiting. ***
            # The OS will un-park us the instant any file in the tree changes.
            ok = kernel32.ReadDirectoryChangesW(
                handle,
                buf,
                BUFFER_SIZE,
                True,                      # bWatchSubtree — watch subdirectories too
                WATCH_FLAGS,
                ctypes.byref(bytes_back),
                None,                      # lpOverlapped — None = synchronous mode
                None                       # lpCompletionRoutine
            )

            if not ok or bytes_back.value == 0:
                # This usually means the watched folder was deleted while we were running
                print("[watch] Lost directory handle (folder deleted?). Stopping.")
                break

            events = _parse_notify_buffer(buf.raw, bytes_back.value)

            # Print what the OS told us, filtering out vault internals
            has_real_changes = False
            for action, filename in events:
                rel_path = filename.replace('/', os.sep)
                # Ignore anything the vault writes to itself — those aren't user changes
                if rel_path.startswith(VAULT_DIR_NAME):
                    continue
                label = ACTION_LABELS.get(action, "UNKNOWN  ")
                print(f"  {label}  {rel_path}")
                has_real_changes = True

            if not has_real_changes:
                continue

            # Re-scan to get accurate hashes. The OS event tells us *something* changed
            # but we do our own MD5 diff to avoid backing up temp files that vanished
            # (e.g. editor swap files that appear and disappear in milliseconds).
            current_snapshot = scan_folder(target_folder, vault_path)
            changed, _ = diff_snapshots(previous_snapshot, current_snapshot)

            if changed:
                ts, count = save_delta_copy(target_folder, vault_path, changed)
                print(f"  -> {count} file(s) backed up to vault [{ts}]\n")
                previous_snapshot = current_snapshot
                save_snapshot_index(vault_path, current_snapshot)
            else:
                # OS fired an event (e.g. a temp file) but content hash is unchanged
                print("  (hash check: no real content change — skipping backup)\n")

    except KeyboardInterrupt:
        print("\n[watch] Stopped. Your vault is intact.")
    finally:
        # Always close the handle — good citizens return OS resources
        kernel32.CloseHandle(handle)
