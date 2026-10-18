#!/usr/bin/env bash
# Optional encryption of backups, sourced by backup.sh and restore.sh.
#
# Set BACKUP_PASSPHRASE_FILE to a file holding a long random passphrase (create one with
#   umask 077; openssl rand -base64 48 > ~/.choud-backup-passphrase
# and keep a copy somewhere that is NOT this machine: without it the backups cannot be read).
# Each part of a backup is then written as <name>.enc, encrypted as it is produced, so no plain
# copy of the database, the files or the .env secrets ever touches the backup folder.
#
#   cipher   AES-256-CBC with a key derived by PBKDF2-SHA256 (600,000 iterations) and a random salt
#   protects confidentiality; integrity of each file is checked by SHA256SUMS, which anyone who
#   can change the backup could also rewrite (this is encryption at rest, not a signature)

_CRYPT_ARGS=(-aes-256-cbc -pbkdf2 -iter 600000 -salt)

crypt_enabled() { [ -n "${BACKUP_PASSPHRASE_FILE:-}" ]; }

# Fail early and clearly if encryption is requested but cannot work.
crypt_check() {
    crypt_enabled || return 0
    command -v openssl >/dev/null 2>&1 || { echo "BACKUP_PASSPHRASE_FILE is set but openssl is not installed." >&2; return 1; }
    [ -r "$BACKUP_PASSPHRASE_FILE" ] && [ -s "$BACKUP_PASSPHRASE_FILE" ] \
        || { echo "BACKUP_PASSPHRASE_FILE='${BACKUP_PASSPHRASE_FILE}' is missing or empty." >&2; return 1; }
    return 0
}

# write_stream <dir> <name>: reads stdin, stores it as <dir>/<name> (or <dir>/<name>.enc).
write_stream() {
    if crypt_enabled; then
        openssl enc "${_CRYPT_ARGS[@]}" -pass "file:${BACKUP_PASSPHRASE_FILE}" > "$1/$2.enc"
    else
        cat > "$1/$2"
    fi
}

# read_stream <dir> <name>: writes the stored part back out in plain form.
read_stream() {
    if [ -f "$1/$2.enc" ]; then
        crypt_enabled || { echo "This backup is encrypted: set BACKUP_PASSPHRASE_FILE." >&2; return 1; }
        openssl enc -d "${_CRYPT_ARGS[@]}" -pass "file:${BACKUP_PASSPHRASE_FILE}" < "$1/$2.enc"
    else
        cat "$1/$2"
    fi
}

# stored_name <dir> <name>: the file name a part was stored under.
stored_name() {
    if [ -f "$1/$2.enc" ]; then echo "$2.enc"; else echo "$2"; fi
}
