# scanner.py
# ----------
# This module handles scanning the watched folder and computing file hashes.
# The whole change-detection strategy boils down to: if the MD5 fingerprint
# of a file is different from what we recorded last time, the file changed.
# Simple and works great for a project like this.

import os
import hashlib


def hash_file(filepath):
    """
    Computes and returns the MD5 hash of a single file.
    We're reading in 8KB chunks so this stays memory-efficient even on
    bigger files — no loading the whole thing into RAM at once.
    Returns None if the file can't be read for some reason (permissions, etc).
    """
    h = hashlib.md5()
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
    except (IOError, OSError):
        return None
    return h.hexdigest()


def scan_folder(target_folder, vault_path):
    """
    Walks the entire target folder and returns a snapshot dict:
        { "relative/path/to/file.txt": "md5hashstring", ... }

    We skip the vault directory entirely — otherwise we'd be hashing
    our own backups and treating those as changes, which would be chaos.
    """
    snapshot = {}

    for root, dirs, files in os.walk(target_folder):
        # Prune the vault dir from traversal in-place so os.walk won't enter it
        dirs[:] = [d for d in dirs if os.path.join(root, d) != vault_path]

        for filename in files:
            full_path = os.path.join(root, filename)
            rel_path = os.path.relpath(full_path, target_folder)
            file_hash = hash_file(full_path)
            if file_hash is not None:
                snapshot[rel_path] = file_hash

    return snapshot


def diff_snapshots(old_snapshot, new_snapshot):
    """
    Compares two snapshots and returns what changed between them.
    Returns a tuple: (changed_files, deleted_files)
    - changed_files: new files + files whose hash differs from before
    - deleted_files: files that existed before but are gone now
    """
    changed = []
    deleted = []

    for rel_path, current_hash in new_snapshot.items():
        old_hash = old_snapshot.get(rel_path)
        if old_hash is None:
            # Brand new file that wasn't there before
            changed.append((rel_path, "new"))
        elif old_hash != current_hash:
            # Existing file that's been modified
            changed.append((rel_path, "modified"))

    for rel_path in old_snapshot:
        if rel_path not in new_snapshot:
            deleted.append(rel_path)

    return changed, deleted
