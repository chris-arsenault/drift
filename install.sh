#!/usr/bin/env bash
# drift-semantic installer
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/chris-arsenault/drift/main/install.sh | bash
#   bash install.sh
#
# Installs to ~/.drift-semantic and adds to PATH via shell profile.
# Re-running upgrades an existing installation.

set -euo pipefail

INSTALL_DIR="${DRIFT_SEMANTIC_INSTALL_DIR:-$HOME/.drift-semantic}"
REPO_URL="https://github.com/chris-arsenault/drift.git"
BRANCH="main"

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

if [[ -t 2 ]]; then
    _R='\033[0m' _G='\033[0;32m' _Y='\033[0;33m' _B='\033[0;34m' _RED='\033[0;31m' _BOLD='\033[1m'
else
    _R='' _G='' _Y='' _B='' _RED='' _BOLD=''
fi

info()    { printf "${_B}[*]${_R} %s\n" "$*" >&2; }
success() { printf "${_G}[+]${_R} %s\n" "$*" >&2; }
warn()    { printf "${_Y}[!]${_R} %s\n" "$*" >&2; }
error()   { printf "${_RED}[-]${_R} %s\n" "$*" >&2; }

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------

check_prerequisites() {
    local ok=true

    if ! command -v git &>/dev/null; then
        error "git is required but not found."
        ok=false
    fi

    if ! command -v node &>/dev/null; then
        error "Node.js is required but not found."
        error "Install: https://nodejs.org/ or via your package manager"
        ok=false
    fi

    if command -v python3 &>/dev/null; then
        local pyver
        pyver="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
        local pymajor pyminor
        pymajor="${pyver%%.*}"
        pyminor="${pyver#*.}"
        if [[ "$pymajor" -lt 3 ]] || { [[ "$pymajor" -eq 3 ]] && [[ "$pyminor" -lt 10 ]]; }; then
            error "Python 3.10+ required, found $pyver"
            ok=false
        fi
    else
        error "Python 3 is required but not found."
        ok=false
    fi

    if ! command -v sg &>/dev/null; then
        warn "ast-grep (sg) not found — structural pattern matching will be skipped."
        warn "Install: https://ast-grep.github.io/guide/quick-start.html"
    fi

    if [[ "$ok" != "true" ]]; then
        echo "" >&2
        error "Missing prerequisites. Install them and re-run."
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# Install or upgrade
# ---------------------------------------------------------------------------

install_or_upgrade() {
    if [[ -d "$INSTALL_DIR" ]]; then
        if [[ -d "$INSTALL_DIR/.git" ]]; then
            info "Existing installation found — upgrading..."
            if ! git -C "$INSTALL_DIR" pull --ff-only 2>&1; then
                error "git pull failed. You may have local modifications."
                error "Resolve with: cd $INSTALL_DIR && git status"
                exit 1
            fi
            success "Upgraded to latest."
        else
            error "$INSTALL_DIR exists but is not a drift-semantic installation."
            error "Remove it manually or set DRIFT_SEMANTIC_INSTALL_DIR to a different path."
            exit 1
        fi
    else
        info "Cloning drift-semantic to $INSTALL_DIR..."
        git clone "$REPO_URL" "$INSTALL_DIR" --depth 1 --branch "$BRANCH" 2>&1
        success "Cloned."
    fi

    chmod +x "$INSTALL_DIR/bin/drift"
}

# ---------------------------------------------------------------------------
# Shell profile integration
# ---------------------------------------------------------------------------

PROFILE_BLOCK='# --- drift-semantic ---
export DRIFT_SEMANTIC="$HOME/.drift-semantic"
export PATH="$HOME/.drift-semantic/bin:$PATH"
# --- drift-semantic end ---'

configure_shell() {
    local profiles=()
    local updated=false

    # Detect shell profiles
    [[ -f "$HOME/.bashrc" ]]       && profiles+=("$HOME/.bashrc")
    [[ -f "$HOME/.zshrc" ]]        && profiles+=("$HOME/.zshrc")
    [[ -f "$HOME/.bash_profile" ]] && profiles+=("$HOME/.bash_profile")
    [[ -f "$HOME/.profile" ]]      && profiles+=("$HOME/.profile")

    # If nothing found, try creating the default for current shell
    if [[ ${#profiles[@]} -eq 0 ]]; then
        local current_shell
        current_shell="$(basename "${SHELL:-/bin/bash}")"
        case "$current_shell" in
            zsh)  profiles=("$HOME/.zshrc") ;;
            *)    profiles=("$HOME/.bashrc") ;;
        esac
        touch "${profiles[0]}"
        info "Created ${profiles[0]}"
    fi

    for profile in "${profiles[@]}"; do
        if grep -q "# --- drift-semantic ---" "$profile" 2>/dev/null; then
            info "Already configured: $profile"
        else
            printf '\n%s\n' "$PROFILE_BLOCK" >> "$profile"
            success "Updated: $profile"
            updated=true
        fi
    done

    if [[ "$updated" == "true" ]]; then
        return 0  # signal that shell needs restart
    else
        return 1  # already configured
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
    echo "" >&2
    printf "${_BOLD}drift-semantic installer${_R}\n" >&2
    echo "" >&2

    check_prerequisites
    install_or_upgrade

    local needs_restart=false
    if configure_shell; then
        needs_restart=true
    fi

    echo "" >&2
    success "drift-semantic installed to $INSTALL_DIR"
    echo "" >&2

    if [[ "$needs_restart" == "true" ]]; then
        info "Restart your shell or run:"
        local current_shell
        current_shell="$(basename "${SHELL:-/bin/bash}")"
        case "$current_shell" in
            zsh)  info "  source ~/.zshrc" ;;
            *)    info "  source ~/.bashrc" ;;
        esac
        echo "" >&2
    fi

    info "Then run:"
    info "  drift version                  # verify installation"
    info "  drift run --project <path>     # run against a codebase"
    info "  drift install-skill            # install Claude Code skill to a project"
    echo "" >&2
    info "Dependencies install automatically on first run."
}

main
