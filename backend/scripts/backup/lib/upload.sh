#!/usr/bin/env bash
# Pushing the artifact to Cloudflare R2 and Hoster S3.
#
# aws-cli runs from its official image rather than being installed on the host:
# the VPS has no unzip (the native installer needs it), the version is pinned
# and reproducible, and nothing about the backup job survives on the host but
# this repository. Credentials are handed to the container by name (-e VAR),
# never as `docker run` arguments, so they never appear in `ps`.
#
# Every tier is uploaded independently from the local file rather than
# server-side-copied from the daily object. It costs one more transfer of
# ~100 MB and buys independence: each object is verified, on its own, against
# the checksum of the file on disk.

# aws-cli v2 sends checksum trailers by default, which non-AWS S3
# implementations have historically rejected outright. `when_required` keeps
# the request shape to what both R2 and Hoster definitely accept.
export AWS_REQUEST_CHECKSUM_CALCULATION=when_required
export AWS_RESPONSE_CHECKSUM_VALIDATION=when_required

# The mount is read-only by default: this function exists to push artifacts,
# and a container that cannot write cannot damage the one local copy of a dump.
# `restore.sh fetch` is the exception — it is downloading — and it sets
# BACKUP_AWS_MOUNT_MODE=rw around its own call. That asymmetry was found the
# hard way on 2026-09-22: fetch had never worked, because aws-cli inside the
# container was writing its temporary part-file into a read-only /data. Nothing
# noticed, because the path nobody exercises until an incident is the restore
# path.
run_aws() {
    local dest=$1
    shift
    AWS_ACCESS_KEY_ID="$(dest_var "${dest}" key)" \
        AWS_SECRET_ACCESS_KEY="$(dest_var "${dest}" secret)" \
        AWS_DEFAULT_REGION="$(dest_var "${dest}" region)" \
        docker run --rm \
        -e AWS_ACCESS_KEY_ID \
        -e AWS_SECRET_ACCESS_KEY \
        -e AWS_DEFAULT_REGION \
        -e AWS_REQUEST_CHECKSUM_CALCULATION \
        -e AWS_RESPONSE_CHECKSUM_VALIDATION \
        -v "${BACKUP_ARTIFACT_DIR}:/data:${BACKUP_AWS_MOUNT_MODE:-ro}" \
        "${BACKUP_AWSCLI_IMAGE}" \
        --endpoint-url "$(dest_var "${dest}" endpoint)" \
        "$@"
}

# Uploads one artifact to one tier of one destination and reads the object
# back to confirm what landed. `aws s3 cp` reporting success is not the same
# claim as the bytes being there at the right length.
upload_one() {
    local dest=$1 tier=$2 filename=$3 sha=$4 local_size=$5
    local bucket key attempt remote_size remote_sha

    bucket=$(dest_var "${dest}" bucket)
    key="${tier}/${filename}"

    for attempt in $(seq 1 "${BACKUP_UPLOAD_RETRIES}"); do
        if run_aws "${dest}" s3 cp \
            "/data/${filename}" "s3://${bucket}/${key}" \
            --metadata "sha256=${sha}" \
            --only-show-errors; then
            break
        fi
        if [ "${attempt}" -eq "${BACKUP_UPLOAD_RETRIES}" ]; then
            return 1
        fi
        warn "${dest}:${key} upload attempt ${attempt} failed; retrying in $((attempt * 15))s."
        sleep $((attempt * 15))
    done

    verify_remote_object "${dest}" "${bucket}" "${key}" "${sha}" "${local_size}" || return 1

    log "Uploaded ${dest}:${key} ($(human_bytes "${local_size}"), verified)."
    return 0
}

# Reads the object back and checks it against the local file. Size and checksum
# come from ONE head-object rather than two: a storage that blips on the second
# call would otherwise condemn an upload that is provably fine, which is how
# the first live run reported a failure against a perfectly good object. The
# read is retried for the same reason — a transient 5xx here says nothing about
# the bytes in the bucket.
verify_remote_object() {
    local dest=$1 bucket=$2 key=$3 sha=$4 local_size=$5
    local attempt raw remote_size remote_sha

    for attempt in 1 2 3; do
        raw=$(run_aws "${dest}" s3api head-object \
            --bucket "${bucket}" --key "${key}" \
            --query '[ContentLength, Metadata.sha256]' \
            --output text 2>/dev/null || true)
        remote_size=$(printf '%s' "${raw}" | awk '{print $1}')
        remote_sha=$(printf '%s' "${raw}" | awk '{print $2}')

        if [ -n "${remote_size}" ] && [ "${remote_size}" != "None" ]; then
            break
        fi

        if [ "${attempt}" -lt 3 ]; then
            warn "${dest}:${key} did not answer head-object (attempt ${attempt}); retrying."
            sleep $((attempt * 5))
        fi
    done

    if [ -z "${remote_size}" ] || [ "${remote_size}" = "None" ]; then
        warn "${dest}:${key} could not be read back after the upload."
        return 1
    fi
    if [ "${remote_size}" != "${local_size}" ]; then
        warn "${dest}:${key} is ${remote_size} bytes remotely, ${local_size} locally."
        return 1
    fi
    if [ "${remote_sha}" != "${sha}" ]; then
        warn "${dest}:${key} checksum metadata is ${remote_sha:-<absent>}, expected ${sha}."
        return 1
    fi
    return 0
}

# Fans the artifact out over every destination × tier. Collects failures
# instead of stopping at the first one: if Hoster is down, the run should
# still get the dump into R2 before it reports the failure.
upload_all() {
    local filename=$1 sha=$2 size=$3
    shift 3
    local -a tiers=("$@")
    local dest tier failures=()

    for dest in "${BACKUP_DESTINATIONS[@]}"; do
        for tier in "${tiers[@]}"; do
            if ! upload_one "${dest}" "${tier}" "${filename}" "${sha}" "${size}"; then
                failures+=("${dest}:${tier}")
            fi
        done
    done

    if [ ${#failures[@]} -gt 0 ]; then
        die "Upload failed for: ${failures[*]}. Local artifact kept at ${BACKUP_ARTIFACT_DIR}/${filename}."
    fi
}
