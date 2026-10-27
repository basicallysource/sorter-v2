#!/usr/bin/env bash
# get-on-release.sh: put a Sorter's software on the newest release, whatever
# state its checkout is in, without losing anything on the machine. Run it on
# the machine:
#
#   curl -fsSL https://raw.githubusercontent.com/basicallysource/sorter-v2/main/software/scripts/get-on-release.sh | sudo bash
#   curl -fsSL https://raw.githubusercontent.com/basicallysource/sorter-v2/main/software/scripts/get-on-release.sh | sudo bash -s canary
#
# What it keeps:
#   - Files git ignores (machine.toml, .env, the database, pictures, logs) are
#     never touched.
#   - Edits to the software's own files, and commits made on the machine, go on
#     a branch named backup/<date> before anything changes.
#   - Any other file the release would replace is copied to a folder beside the
#     checkout first. Nothing is deleted but the old release's own files.
# What it repairs: a branch, a merge or rebase stopped halfway, stale git locks,
# files owned by the wrong user, and damaged git files (the .git folder is
# replaced and the old one kept beside the checkout).
#
# SORTER_REPO=/path sets where the checkout is. SORTER_NO_RESTART=1 skips the
# service steps.

main() {
    set -euo pipefail
    exec </dev/null  # piped in through curl: nothing below may read the script as input

    local channel="${1:-stable}"
    case "$channel" in stable|canary) ;; *) die "the channel is stable or canary, not '$channel'" ;; esac
    [ "$(id -u)" -eq 0 ] || die "run it as root: put sudo before bash"

    REPO_URL="https://github.com/basicallysource/sorter-v2"
    STAMP="$(date +%Y%m%d-%H%M%S)"
    BRANCH=""
    SAVED=0

    UNIT=""
    local u wd
    for u in sorter-backend-dev.service sorter-backend.service; do
        if [ "$(systemctl is-enabled "$u" 2>/dev/null)" = enabled ]; then UNIT="$u"; break; fi
    done
    REPO="${SORTER_REPO:-}"
    if [ -z "$REPO" ] && [ -n "$UNIT" ]; then
        wd="$(systemctl show -p WorkingDirectory --value "$UNIT")"
        if [ -n "$wd" ] && [ -d "$wd/../../.." ]; then REPO="$(cd "$wd/../../.." && pwd)"; fi
    fi
    REPO="${REPO:-/home/orangepi/sorter-v2}"
    [ -d "$REPO/software/sorter" ] || die "no Sorter checkout at $REPO. Run it again with SORTER_REPO=/path/to/sorter-v2 after sudo."
    OWNER="$(stat -c %U "$REPO")"
    BACKUP="$REPO-backup-$STAMP"

    say "Checking git in $REPO"
    if git_busy; then die "a git command is running in $REPO (an update from the UI?). Run this again once it has finished."; fi
    if [ -d "$REPO/.git" ]; then
        find "$REPO/.git" -name '*.lock' -not -path '*/objects/*' -print -delete
    fi

    git_ok || rebuild_git

    say "Downloading the list of releases"
    g fetch -q --force --prune "$REPO_URL" '+refs/tags/sorter/*:refs/tags/sorter/*'
    TAG="$(releases "sorter/$channel/v*" | tail -n1)"
    [ -n "$TAG" ] || die "found no $channel release"
    echo "newest $channel release: $TAG"

    if [ -n "${BASE_UNKNOWN:-}" ]; then assume_closest_release; fi
    refuse_older "$channel"
    save_work
    for u in merge rebase cherry-pick revert am; do g "$u" --quit >/dev/null 2>&1 || true; done
    save_untracked_in_the_way

    say "Checking out $TAG"
    g checkout -q -f --detach "refs/tags/$TAG"
    if [ "$OWNER" != root ]; then chown -R --from=root "$OWNER" "$REPO"; fi  # what root's git wrote

    local home uv pnpm
    home="$(getent passwd "$OWNER" | cut -d: -f6)"
    uv="$(pick "$(command -v uv || true)" /usr/local/bin/uv "$home/.local/bin/uv" "$home/.cargo/bin/uv")" || die "can't find uv"
    pnpm="$(pick "$(command -v pnpm || true)" /usr/local/bin/pnpm /usr/bin/pnpm "$home/.local/share/pnpm/pnpm")" || die "can't find pnpm"

    say "Installing the Python packages"
    (cd "$REPO/software/sorter/backend" && as_owner "$uv" sync --locked)

    say "Building the UI (a few minutes)"
    (cd "$REPO/software/sorter/frontend" && as_owner env CI=true "$pnpm" install --frozen-lockfile && as_owner "$pnpm" build)

    if [ "${SORTER_NO_RESTART:-}" = 1 ]; then
        say "Done, not restarted (SORTER_NO_RESTART=1)"
    elif [ -z "$UNIT" ]; then
        say "Done. No sorter service is installed here: restart the backend the way you run it."
    else
        retire_old_ui_units
        say "Restarting $UNIT"
        systemctl restart "$UNIT"
        local i up=0
        for i in $(seq 1 120); do
            if curl -fsS -o /dev/null http://127.0.0.1:8000/health 2>/dev/null; then up=1; break; fi
            sleep 5
        done
        if [ "$up" = 1 ]; then
            say "Done: the machine runs $TAG. Open http://$(hostname).local"
        else
            say "The machine is on $TAG, but the backend hasn't answered in 10 minutes. Its log: journalctl -u $UNIT -n 50"
        fi
    fi
    if [ -n "$BRANCH" ]; then echo "Your edits and commits are on the branch $BRANCH: git -C $REPO show $BRANCH"; fi
    if [ "$SAVED" -gt 0 ]; then echo "$SAVED file(s) the release replaced are copied to $BACKUP"; fi
}

say() { printf '\n==> %s\n' "$*"; }
die() { printf '\nerror: %s\n' "$*" >&2; exit 1; }

# Git as root on a checkout someone else may own, which root's git refuses.
# `gi INDEX ...` is the same on an index file of its own.
g() { git -c safe.directory="$REPO" -c advice.detachedHead=false -c user.name=sorter -c user.email=sorter@localhost -C "$REPO" "$@"; }
gi() { local index="$1"; shift; env GIT_INDEX_FILE="$index" git -c safe.directory="$REPO" -C "$REPO" "$@"; }

as_owner() { if [ "$OWNER" = root ]; then "$@"; else sudo -u "$OWNER" -H env "PATH=$PATH" "$@"; fi; }

pick() { local c; for c in "$@"; do if [ -n "$c" ] && [ -x "$c" ]; then echo "$c"; return 0; fi; done; return 1; }

# Release tags matching a pattern, oldest to newest by version number.
releases() { g tag -l "$@" | { grep -E '/v[0-9]+(\.[0-9]+)*$' || true; } | sort -V; }

# A git process working in this checkout, by its directory or a `-C` argument.
git_busy() {
    local pid
    for pid in $(pgrep -x git || true); do
        case "$(readlink "/proc/$pid/cwd" 2>/dev/null)/ $(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null)" in
            "$REPO"/*|*" $REPO "*|*" $REPO/"*) return 0 ;;
        esac
    done
    return 1
}

git_ok() {
    [ -d "$REPO/.git" ] || return 1
    g rev-parse -q --verify 'HEAD^{commit}' >/dev/null 2>&1 || return 1
    g ls-files >/dev/null 2>&1 || return 1
    g fsck --connectivity-only --no-dangling >/dev/null 2>&1
}

# A fresh .git in place of a damaged or missing one. The working files stay as
# they are, and the old .git is kept beside the checkout.
rebuild_git() {
    say "Git's files are damaged or missing: downloading fresh ones"
    local old_head="" new="$REPO.git-new-$STAMP" broken="$REPO.git-broken-$STAMP"
    if [ -e "$REPO/.git" ]; then old_head="$(g rev-parse -q --verify HEAD 2>/dev/null || true)"; fi
    git clone -q --no-checkout --filter=blob:none "$REPO_URL" "$new"
    if [ -e "$REPO/.git" ]; then mv "$REPO/.git" "$broken"; echo "the damaged one is kept at $broken"; fi
    mv "$new/.git" "$REPO/.git"
    rmdir "$new"
    if [ -n "$old_head" ] && g cat-file -e "$old_head^{commit}" 2>/dev/null; then
        # The machine was on a commit GitHub has: compare against it, as if nothing broke.
        g update-ref --no-deref HEAD "$old_head"
        g read-tree "$old_head"
    else
        BASE_UNKNOWN=1
    fi
}

# With no record of what the machine had, take the release its files match
# best as what it had, so that the checkout replaces that release's files and
# nothing else, and anything that differs from it is saved like an edit.
assume_closest_release() {
    local all disk tag n best="" most=-1
    all="$(releases 'sorter/stable/v*' 'sorter/canary/v*')"
    disk="$(mktemp)"
    for tag in $all; do g ls-tree -r --name-only "refs/tags/$tag"; done | sort -u |
        while IFS= read -r p; do if [ -f "$REPO/$p" ]; then printf '%s\n' "$p"; fi; done > "$disk.paths"
    paste <(g hash-object --stdin-paths <"$disk.paths") "$disk.paths" > "$disk"
    for tag in $all; do
        n="$(g ls-tree -r "refs/tags/$tag" | awk -F'\t' 'NR == FNR { on_disk[$2] = $1; next }
            { split($1, f, " "); if (on_disk[$2] == f[3]) same++ } END { print same + 0 }' "$disk" -)"
        if [ "$n" -gt "$most" ]; then most="$n"; best="$tag"; fi
    done
    rm -f "$disk" "$disk.paths"
    if [ "$most" -le 0 ]; then best="$TAG"; fi
    echo "its files are closest to $best: taking that as what it had"
    g update-ref --no-deref HEAD "$(g rev-parse "refs/tags/$best^{commit}")"
    g read-tree "refs/tags/$best"
}

# Moving to an older release is what the UI refuses too: newer software can
# change the machine's services and data in ways older software can't run on.
refuse_older() {
    local installed target
    installed="$(releases 'sorter/stable/v*' 'sorter/canary/v*' --merged HEAD | sed 's#.*/v##' | sort -V | tail -n1)"
    target="${TAG##*/v}"
    if [ -n "$installed" ] && [ "$installed" != "$target" ] \
        && [ "$(printf '%s\n%s\n' "$installed" "$target" | sort -V | tail -n1)" = "$installed" ]; then
        die "this machine runs $installed, newer than $TAG, and moving back can break it. Run it with canary instead, or wait for $1 to catch up."
    fi
}

# Every edit to a tracked file, staged or not, and any commit only this machine
# has, onto a backup branch. The real index and the files are not touched.
save_work() {
    local index="$REPO/.git/get-on-release.index" tree commit
    gi "$index" read-tree HEAD
    gi "$index" add -u
    g ls-files -z | gi "$index" update-index -q --add --remove -z --stdin
    tree="$(gi "$index" write-tree)"
    rm -f "$index"
    if [ "$tree" != "$(g rev-parse 'HEAD^{tree}')" ]; then
        commit="$(g commit-tree "$tree" -p HEAD -m "Edits on this machine, saved before getting on $TAG")"
    elif [ -z "$(g for-each-ref --contains HEAD --count=1 --format=x)" ]; then
        commit="$(g rev-parse HEAD)"
    else
        return 0
    fi
    BRANCH="backup/$STAMP"
    g branch "$BRANCH" "$commit"
    echo "saved this machine's edits and commits on the branch $BRANCH"
}

# Files the release has that git doesn't track here yet: the checkout would
# write over them.
save_untracked_in_the_way() {
    local p
    while IFS= read -r -d '' p; do
        if [ -e "$REPO/$p" ] || [ -L "$REPO/$p" ]; then keep "$p"; fi
    done < <(comm -z -23 <(g ls-tree -r -z --name-only "refs/tags/$TAG" | sort -z) <(g ls-files -z | sort -z))
}

keep() {
    mkdir -p "$BACKUP/$(dirname "$1")"
    cp -a "$REPO/$1" "$BACKUP/$1"
    SAVED=$((SAVED + 1))
}

# Before the backend served the UI's build, the UI ran in units of its own
# (Vite on port 80). The backend retires them too, but only after building the
# UI again; these are moved to the backup folder, not deleted.
retire_old_ui_units() {
    [ -e "$REPO/software/systemd/sorter-ui-dev.service" ] && return 0
    local u moved=0
    for u in sorter-ui-dev.service sorter-ui.service; do
        if [ -e "/etc/systemd/system/$u" ]; then
            systemctl disable --now "$u" >/dev/null 2>&1 || true
            mkdir -p "$BACKUP/etc-systemd"
            mv "/etc/systemd/system/$u" "$BACKUP/etc-systemd/$u"
            echo "retired $u (the UI's old service; the backend serves the UI now)"
            moved=1
        fi
    done
    if [ "$moved" = 1 ]; then
        if [ -f /var/lib/sorteros/active-services ]; then sed -i '/^sorter-ui/d' /var/lib/sorteros/active-services; fi
        systemctl daemon-reload
    fi
}

main "$@"
