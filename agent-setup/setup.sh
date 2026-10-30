#!/usr/bin/env bash
# Democratizing Google Data Studio: build agent setup for macOS/Linux (untested there; contracts/conventions.md, Build agent).
# Run it as the Build stage shows it:
#   curl -fsSL https://raw.githubusercontent.com/Gjandane/democratizing-google-data-studio/main/agent-setup/setup.sh | bash -s -- --server <origin> --job <CODE>
# The setup step passes --check <CODE> instead of --job. Optional: --update (fresh repo zip), --dry-run
# (rehearsal: no sign-in, the agent passes --dry-run), --source <zip path or URL>, --home <install folder>.
# Needs Google Chrome; installs uv when missing. No Git, .env or GCP project on this machine.

REPO_ZIP=https://github.com/Gjandane/democratizing-google-data-studio/archive/refs/heads/main.zip
USAGE='Usage: setup.sh --server <URL> (--job <CODE> | --check <CODE>) [--update] [--dry-run] [--source <zip>] [--home <folder>]'

find_chrome() {
    # The engine's own lookup (dsengine chrome_path): DSS_CHROME_PATH alone when set, else the usual places.
    local candidate
    if [ -n "${DSS_CHROME_PATH:-}" ]; then
        [ -f "$DSS_CHROME_PATH" ] && return 0
        return 1
    fi
    for candidate in "$(command -v google-chrome 2>/dev/null)" "$(command -v google-chrome-stable 2>/dev/null)" \
        "${PROGRAMFILES:-C:/Program Files}/Google/Chrome/Application/chrome.exe" \
        "${LOCALAPPDATA:-}/Google/Chrome/Application/chrome.exe" \
        "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe" \
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; do
        [ -n "$candidate" ] && [ -f "$candidate" ] && return 0
    done
    return 1
}

native_path() {
    # Git Bash: uv and Python are Windows programs, so hand them C:/ paths.
    if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s\n' "$1"; fi
}

get_app() {
    # Download (or copy, with --source) the repo zip and put its one top folder at app/; the rest of
    # the install folder (chrome-profile/, data/) stays as it is.
    local app=$1 temp from top
    temp=$(mktemp -d "$home/download-XXXXXX") || return 1
    from=${source:-$REPO_ZIP}
    case $from in
        http://*|https://*) echo "Downloading $from ..."; curl -fsSL -o "$temp/repo.zip" "$from" || { rm -rf "$temp"; return 1; } ;;
        *) echo "Copying $from ..."; cp "$from" "$temp/repo.zip" || { rm -rf "$temp"; return 1; } ;;
    esac
    if command -v unzip >/dev/null 2>&1; then
        unzip -q "$temp/repo.zip" -d "$temp/unpacked" || { rm -rf "$temp"; return 1; }
    else
        uv run --no-project python -m zipfile -e "$(native_path "$temp/repo.zip")" "$(native_path "$temp/unpacked")" </dev/null \
            || { rm -rf "$temp"; return 1; }
    fi
    top=$(find "$temp/unpacked" -mindepth 1 -maxdepth 1 -type d)
    if [ "$(printf '%s\n' "$top" | wc -l)" -ne 1 ] || [ ! -f "$top/backend/pyproject.toml" ] || [ ! -f "$top/engine/pyproject.toml" ]; then
        echo "The zip is not this repository (no backend/ and engine/ under one top folder)"
        rm -rf "$temp"; return 1
    fi
    rm -rf "$app" && mv "$top" "$app"
    local moved=$?
    rm -rf "$temp"
    return $moved
}

main() {
    local server='' job='' check='' update=0 dry_run=0 source='' home=''
    while [ $# -gt 0 ]; do
        case $1 in
            --server|--job|--check|--source|--home) [ $# -ge 2 ] || { echo "$USAGE"; return 2; } ;;
        esac
        case $1 in
            --server) server=${2:-}; shift 2 ;;
            --job) job=${2:-}; shift 2 ;;
            --check) check=${2:-}; shift 2 ;;
            --update) update=1; shift ;;
            --dry-run) dry_run=1; shift ;;
            --source) source=${2:-}; shift 2 ;;
            --home) home=${2:-}; shift 2 ;;
            *) echo "$USAGE"; return 2 ;;
        esac
    done
    if [ -z "$server" ] || { [ -n "$job" ] && [ -n "$check" ]; } || { [ -z "$job" ] && [ -z "$check" ]; }; then
        echo "$USAGE"; return 2
    fi
    if ! find_chrome; then
        echo "Google Chrome is required: https://www.google.com/chrome/"
        return 1
    fi
    if ! command -v uv >/dev/null 2>&1; then
        echo "Installing uv (https://docs.astral.sh/uv/) ..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.local/bin:$PATH"
        if ! command -v uv >/dev/null 2>&1; then
            echo "uv did not install; install it from https://docs.astral.sh/uv/ and rerun the setup command"
            return 1
        fi
    fi

    home=${home:-$HOME/.dss-agent}
    mkdir -p "$home" && home=$(cd "$home" && pwd) || return 1
    local app="$home/app"
    if [ "$update" = 1 ] || [ ! -f "$app/.dss-installed" ]; then
        get_app "$app" || { echo "Download failed; rerun the setup command"; return 1; }
        local part
        for part in backend engine; do
            echo "Installing the $part (uv sync) ..."
            if ! uv sync --no-dev --frozen --project "$(native_path "$app/$part")" </dev/null; then
                echo "uv sync failed for the $part; rerun the setup command with --update"
                return 1
            fi
        done
        date -u +%Y-%m-%dT%H:%M:%SZ > "$app/.dss-installed"
    else
        echo "Using the existing install in $home (rerun with --update for a fresh download)"
    fi

    # The agent and the engine read these instead of the repo's data/ and .chrome-profile/.
    mkdir -p "$home/chrome-profile" "$home/data"
    export DSS_CHROME_PROFILE DSS_DATA_DIR DSS_ENGINE_CMD
    DSS_CHROME_PROFILE=$(native_path "$home/chrome-profile")
    DSS_DATA_DIR=$(native_path "$home/data")
    DSS_ENGINE_CMD='uv run --no-dev --frozen --project ../engine dsengine'
    local engine backend
    engine=$(native_path "$app/engine")
    backend=$(native_path "$app/backend")

    if [ "$dry_run" = 1 ]; then
        echo "Dry run: skipping the Google sign-in"
    elif uv run --no-dev --frozen --project "$engine" dsengine check </dev/null 2>/dev/null | grep -q '"signed_in": *true'; then
        echo "Signed in to Google in the agent's Chrome profile"
    else
        echo "Sign in to Google in the Chrome window that opens, and accept Data Studio's terms if it asks."
        if ! uv run --no-dev --frozen --project "$engine" dsengine login </dev/null; then
            echo "Sign-in did not finish; rerun the setup command to try again"
            return 1
        fi
    fi

    if [ -n "$job" ]; then
        set -- run --server "$server" --job "$job"
        [ "$dry_run" = 1 ] && set -- "$@" --dry-run
    else
        set -- check --server "$server" --code "$check"
    fi
    uv run --no-dev --frozen --project "$backend" dss-agent "$@" </dev/null
}

# Everything above is a definition, so bash has read the whole script before main runs (curl | bash).
main "$@"
exit $?
