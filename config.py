# config.py
# ---------
# Central place for all the "magic numbers" and constants in this project.
# Keeping them here means I only have to change one file if I want to tweak
# something like the polling speed or the vault folder name.

# The hidden directory where all our backups live.
# Dot-prefix convention makes it feel properly hidden (at least on Unix).
VAULT_DIR_NAME = ".my_vault"

# POLL_INTERVAL was here before — removed after switching to event-driven monitoring.
# The new watcher.py uses ReadDirectoryChangesW (OS-level) so we no longer need
# to define a polling frequency at all.
