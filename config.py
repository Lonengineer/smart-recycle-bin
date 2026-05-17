# config.py
# ---------
# Central place for all the "magic numbers" and constants in this project.
# Keeping them here means I only have to change one file if I want to tweak
# something like the polling speed or the vault folder name.

# The hidden directory where all our backups live.
# Dot-prefix convention makes it feel properly hidden (at least on Unix).
VAULT_DIR_NAME = ".my_vault"

# Polling interval in seconds. 2s is a sweet spot — responsive but not
# burning through unnecessary CPU cycles.
POLL_INTERVAL = 2
