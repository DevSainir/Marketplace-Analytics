#!/usr/bin/env bash
# The secrets bundle: backend/.env, encrypted to ONE offline key and pushed to
# the same two buckets as the database archives.
#
# Why this is a separate artifact rather than a file added to the nightly dump.
# The dump already holds every WB token, Fernet-encrypted; .env holds the
# Fernet key. Two artifacts, two keys, two layers — and the layers only mean
# something while the two are apart. Putting .env inside the nightly archive
# would collapse them: one decrypted archive would then yield every customer's
# live WB token, both buckets' credentials and the database password at once.
#
# Why it is manual. Secrets change a few times a year. A nightly job over
# unchanging input is a nightly opportunity to leak it, and the failure this
# job actually has — an operator rotating a key and never re-running it — is
# not fixed by a schedule. It is fixed by secrets_bundle_drift_note below,
# which puts the drift in the Sunday report.
#
# Why nothing here can read it back. The bundle is encrypted to the offline
# recipient only, so this box cannot decrypt what it just wrote. That is the
# entire point: whoever takes the VPS and downloads this object holds a file
# they cannot open. The cost is that "it decrypts" is not a claim any machine
# here can make — the gates below check what is checkable, and the rest is a
# human drill with the key from the password manager.

# Which files go in. One entry per line or space-separated; every one must
# exist, because a bundle silently missing a file is worse than no bundle.
secrets_bundle_files() {
    printf '%s\n' ${BACKUP_SECRETS_FILES:-${ENV_FILE}}
}

# What this job needs, checked before it reads a single secret. Deliberately
# not require_config: the bundle needs no Postgres, no docker network and no
# database encryption identity.
require_secrets_config() {
    local missing=() dest field count

    command -v age >/dev/null || die "age is not installed (apt-get install age)."
    command -v docker >/dev/null || die "docker is not on PATH."

    [ -r "${BACKUP_SECRETS_RECIPIENTS}" ] ||
        die "Recipient list not readable: ${BACKUP_SECRETS_RECIPIENTS}"

    count=$(recipient_count "${BACKUP_SECRETS_RECIPIENTS}")
    [ "${count}" -ge 1 ] ||
        die "${BACKUP_SECRETS_RECIPIENTS} names no recipients."

    # An online recipient here would hand the whole scheme back to anyone with
    # a shell on this box, and it is the kind of edit that looks helpful.
    while read -r line; do
        case ${line} in
        '' | '#'*) continue ;;
        esac
        if grep -qF "${line}" "${BACKUP_DB_RECIPIENTS}" 2>/dev/null; then
            die "A secrets recipient also appears in ${BACKUP_DB_RECIPIENTS##*/}. The bundle must not be readable by a key this machine holds."
        fi
    done <"${BACKUP_SECRETS_RECIPIENTS}"

    while read -r file; do
        [ -r "${file}" ] || missing+=("${file}")
    done < <(secrets_bundle_files)

    for dest in "${BACKUP_DESTINATIONS[@]}"; do
        for field in endpoint bucket key secret; do
            [ -n "$(dest_var "${dest}" "${field}")" ] ||
                missing+=("${dest}/${field}")
        done
    done

    [ ${#missing[@]} -eq 0 ] ||
        die "Missing for the secrets bundle: ${missing[*]}"
}

# tar → gzip → age, with the plaintext tar checked before it is encrypted.
# Reading the archive back is the last chance anything here gets to look
# inside: after encryption this box is locked out on purpose.
create_secrets_bundle() {
    local plain=$1 encrypted=$2 expected stanzas file base
    local -a files=()

    while read -r file; do files+=("${file}"); done < <(secrets_bundle_files)

    log "Bundling ${#files[@]} file(s): ${files[*]##*/}"

    # Staged under basenames rather than tarred in place. `tar -C /` would
    # carry this box's absolute layout into a restore on a different one, and
    # the staging step is also where a name collision becomes an error instead
    # of one file quietly overwriting another inside the archive.
    SECRETS_STAGE=$(mktemp -d "${BACKUP_ARTIFACT_DIR}/secrets-stage.XXXXXX")
    chmod 700 "${SECRETS_STAGE}"
    for file in "${files[@]}"; do
        base=${file##*/}
        [ -e "${SECRETS_STAGE}/${base}" ] &&
            die "Two bundle files are both called ${base}; rename one."
        cp -p "${file}" "${SECRETS_STAGE}/${base}"
    done

    tar -czf "${plain}" -C "${SECRETS_STAGE}" . || die "Could not build the secrets tar."
    chmod 600 "${plain}"
    rm -rf "${SECRETS_STAGE}"
    SECRETS_STAGE=""

    tar -tzf "${plain}" >/dev/null || die "The secrets tar does not read back."
    # Files only: `tar -C dir .` writes a `./` directory entry too, and a line
    # saying "2 entries" for one bundled file is a doubt in the wrong place.
    log "Bundle contents verified: $(tar -tzf "${plain}" | grep -c '[^/]$') file(s)."

    age --encrypt --recipients-file "${BACKUP_SECRETS_RECIPIENTS}" \
        --output "${encrypted}" "${plain}" ||
        die "age encryption of the secrets bundle failed."
    chmod 600 "${encrypted}"

    # The only claim left to check. It does not prove the key is the right one
    # — nothing here can — but it proves the file was encrypted to as many keys
    # as the list names, which is the mistake that would otherwise be silent.
    expected=$(recipient_count "${BACKUP_SECRETS_RECIPIENTS}")
    stanzas=$(count_recipient_stanzas "${encrypted}")
    [ "${stanzas}" -eq "${expected}" ] ||
        die "Bundle carries ${stanzas} recipient stanzas, expected ${expected}."

    log "Encryption: OK (age, ${expected} offline recipient(s), NOT decryptable here by design)."
}

# sha256 of the env file as it stands right now.
secrets_env_fingerprint() {
    sha256_of "${ENV_FILE}"
}

secrets_state_file() {
    printf '%s' "${BACKUP_STATE_DIR}/secrets-env-sha"
}

# One line for the Sunday report: has .env changed since the last bundle?
secrets_bundle_drift_note() {
    local recorded current

    recorded=$(cat "$(secrets_state_file)" 2>/dev/null || true)
    current=$(secrets_env_fingerprint 2>/dev/null || true)

    if [ -z "${recorded}" ]; then
        printf 'secrets bundle: never taken — run backup_secrets.sh'
    elif [ "${recorded}" != "${current}" ]; then
        printf '⚠️ secrets bundle: STALE — .env changed since the last one'
    else
        printf 'secrets bundle: current'
    fi
}
