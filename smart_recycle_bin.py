"""
smart_recycle_bin.py
--------------------
The main entry point. This file is intentionally thin — it just parses the
command-line args and delegates to the right module. All the real logic lives
in watcher.py, vault.py, and scanner.py.

Usage:
    python smart_recycle_bin.py watch <folder_path>
    python smart_recycle_bin.py rollback <folder_path>
    python smart_recycle_bin.py history <folder_path>
"""

import sys

from watcher import watch_folder
from vault import bring_back_last_version, get_vault_path, list_all_backups


def print_usage():
    print("=" * 50)
    print("  Smart Recycle Bin — File Versioning Tool")
    print("=" * 50)
    print()
    print("Commands:")
    print("  watch    <folder>   Start monitoring a folder for changes")
    print("  rollback <folder>   Restore the folder to its last backed-up state")
    print("  history  <folder>   List all backups in the vault")
    print()
    print("Examples:")
    print("  python smart_recycle_bin.py watch ./my_project")
    print("  python smart_recycle_bin.py rollback ./my_project")
    print("  python smart_recycle_bin.py history ./my_project")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("[error] Not enough arguments.\n")
        print_usage()
        sys.exit(1)

    command = sys.argv[1].lower().strip()
    folder_arg = sys.argv[2]

    if command == "watch":
        watch_folder(folder_arg)

    elif command == "rollback":
        success = bring_back_last_version(folder_arg)
        sys.exit(0 if success else 1)

    elif command == "history":
        vault_path = get_vault_path(folder_arg)
        list_all_backups(vault_path)

    else:
        print(f"[error] Unknown command: '{command}'\n")
        print_usage()
        sys.exit(1)
