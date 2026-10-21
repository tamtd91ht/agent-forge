#!/bin/sh
# Agent Forge installer for macOS / Linux. Run it from your project's root folder:
#
#   curl -fsSL https://raw.githubusercontent.com/tamtd91ht/agent-forge/main/install.sh | bash
#
# What it does (ADR-0004):
#   1. installs or updates Agent Forge in ~/.agent-forge (its own Python venv + catalog);
#      nothing else on the machine is touched: no PATH change, nothing under ~/.claude
#   2. adds the /agent-forge-upgrade command to the current project (a tracked install that
#      `agent-forge rollback` can undo)
# Then open the project in Claude Code and run /agent-forge-upgrade.
#
# What it installs (safe by default, ADR-0007):
#   - a GitHub Release (the latest, or AGENT_FORGE_VERSION=vX.Y.Z to pin / roll back): the
#     wheel is downloaded from the release, its SHA-256 is checked against the release's
#     SHA256SUMS, and its Sigstore bundle is verified when `cosign` is on PATH (a warning
#     otherwise). A release that fails verification is not installed.
#   - never a moving branch unless you ask: when no release can be resolved (no network, no
#     release yet) the installer stops with exit 1 and installs nothing.
#
# Optional environment variables:
#   AGENT_FORGE_VERSION release tag to install, e.g. v0.3.0 (default: the latest GitHub Release)
#   AGENT_FORGE_REF     any branch or tag, installed from the GitHub archive WITHOUT checksum or
#                       signature verification (development only; overrides AGENT_FORGE_VERSION)
#   AGENT_FORGE_SOURCE  pip-installable source instead of GitHub (a local checkout)
#   AGENT_FORGE_INSTALL_DIR  install directory (default: ~/.agent-forge)
set -eu

REPO="tamtd91ht/agent-forge"
# Identity of the release workflow that signs every release file (docs/operations.md).
SIGN_IDENTITY_RE="^https://github.com/${REPO}/\\.github/workflows/release\\.yml@refs/tags/v"
SIGN_ISSUER="https://token.actions.githubusercontent.com"

say() { printf 'agent-forge: %s\n' "$1"; }
die() { say "$1"; [ -n "${2:-}" ] && say "hint: $2"; exit 1; }

fetch() {
    # fetch URL DEST ; exit non-zero on any failure (no partial file is left behind)
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL --max-time 120 -o "$2" "$1"
    elif command -v wget >/dev/null 2>&1; then
        wget -q --timeout=120 -O "$2" "$1"
    else
        return 1
    fi
}

latest_release() {
    # Prints the tag of the latest GitHub Release, or nothing (no network, no release yet).
    tmp="$(mktemp)"
    if fetch "https://api.github.com/repos/$REPO/releases/latest" "$tmp" 2>/dev/null; then
        tr -d '\n\r' <"$tmp" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p'
    fi
    rm -f "$tmp"
}

sha256_of() { "$py" -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$1"; }

main() {
    home_dir="${AGENT_FORGE_INSTALL_DIR:-$HOME/.agent-forge}"
    venv="$home_dir/.venv"
    bin="$home_dir/bin"
    project="$(pwd)"

    # 1. Python >= 3.11
    py=""
    for cand in python3 python; do
        if command -v "$cand" >/dev/null 2>&1 &&
            [ "$("$cand" -c 'import sys; print(int(sys.version_info >= (3, 11)))' 2>/dev/null)" = "1" ]; then
            py="$cand"
            break
        fi
    done
    [ -n "$py" ] || die "Python 3.11 or newer is required. Install it (https://www.python.org/downloads/) and re-run this command."

    # 2. Resolve what to install: SOURCE > REF (unverified) > VERSION / latest release (verified).
    verified="none"
    ref=""
    if [ -n "${AGENT_FORGE_SOURCE:-}" ]; then
        source="$AGENT_FORGE_SOURCE"
        ref="source"
    elif [ -n "${AGENT_FORGE_REF:-}" ]; then
        ref="$AGENT_FORGE_REF"
        source="https://github.com/$REPO/archive/$ref.zip"
        say "AGENT_FORGE_REF=$ref: installing from the GitHub archive WITHOUT checksum or signature verification (development only)"
    else
        ref="${AGENT_FORGE_VERSION:-}"
        if [ -z "$ref" ]; then
            ref="$(latest_release || true)"
            [ -n "$ref" ] || die "could not resolve the latest GitHub Release of $REPO (no network, or no release published yet); nothing was installed." \
                "pin a release with AGENT_FORGE_VERSION=vX.Y.Z (https://github.com/$REPO/releases), or AGENT_FORGE_REF=main for an unverified development install"
        fi
        case "$ref" in
            v[0-9]*) ;;
            *) die "AGENT_FORGE_VERSION must be a release tag like v0.3.0 (got '$ref')" "use AGENT_FORGE_REF for a branch" ;;
        esac
        version="${ref#v}"
        wheel="agent_forge-${version}-py3-none-any.whl"
        base="https://github.com/$REPO/releases/download/$ref"
        dl="$(mktemp -d)"
        trap 'rm -rf "$dl"' EXIT
        say "downloading release $ref"
        fetch "$base/$wheel" "$dl/$wheel" || die "release $ref has no $wheel (https://github.com/$REPO/releases); nothing was installed." \
            "check the tag name, or pin another release with AGENT_FORGE_VERSION"
        fetch "$base/SHA256SUMS" "$dl/SHA256SUMS" || die "release $ref has no SHA256SUMS; nothing was installed."
        expected="$(awk -v f="$wheel" '$2 == f || $2 == "*" f { print $1 }' "$dl/SHA256SUMS")"
        [ -n "$expected" ] || die "SHA256SUMS of release $ref does not list $wheel; nothing was installed."
        actual="$(sha256_of "$dl/$wheel")"
        [ "$actual" = "$expected" ] || die "checksum mismatch for $wheel (expected $expected, got $actual); nothing was installed." \
            "report this through SECURITY.md"
        verified="sha256"
        if command -v cosign >/dev/null 2>&1; then
            fetch "$base/$wheel.sigstore.json" "$dl/$wheel.sigstore.json" || die "release $ref has no Sigstore bundle for $wheel; nothing was installed."
            cosign verify-blob --bundle "$dl/$wheel.sigstore.json" \
                --certificate-identity-regexp "$SIGN_IDENTITY_RE" \
                --certificate-oidc-issuer "$SIGN_ISSUER" "$dl/$wheel" >/dev/null 2>&1 ||
                die "Sigstore verification failed for $wheel; nothing was installed." "report this through SECURITY.md"
            verified="sha256,sigstore"
        else
            say "cosign not found: SHA-256 checked, Sigstore signature not verified (install cosign to verify: https://docs.sigstore.dev/cosign/system_config/installation/)"
        fi
        source="$dl/$wheel"
    fi

    # 3. engine in ~/.agent-forge/.venv
    mkdir -p "$home_dir" "$bin"
    if [ ! -x "$venv/bin/python" ]; then
        say "creating $venv"
        "$py" -m venv "$venv"
    fi
    say "installing Agent Forge $ref"
    "$venv/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade --force-reinstall "$source"

    # 4. launcher used by Claude Code
    cat >"$bin/agent-forge" <<'EOF'
#!/bin/sh
# Agent Forge launcher (generated by install.sh)
d="$(cd "$(dirname "$0")/.." && pwd)"
export AGENT_FORGE_HOME="$d"
if [ -x "$d/.venv/bin/agent-forge" ]; then exec "$d/.venv/bin/agent-forge" "$@"; fi
exec "$d/.venv/Scripts/agent-forge.exe" "$@"
EOF
    chmod +x "$bin/agent-forge"
    af="$bin/agent-forge"

    # 5. what was installed, for `agent-forge doctor`
    printf 'ref=%s\nverified=%s\ninstalled_at=%s\nversion=%s\n' \
        "$ref" "$verified" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$("$af" --version | sed 's/^agent-forge //')" \
        >"$home_dir/VERSION"

    # 6. catalog (workspace) in ~/.agent-forge
    if [ -f "$home_dir/agent-forge.yaml" ]; then
        "$af" init --workspace "$home_dir" --refresh-registry >/dev/null
    else
        "$af" init --workspace "$home_dir" >/dev/null
    fi
    say "installed $ref in $home_dir (verified: $verified)"

    # 7. the /agent-forge-upgrade command in this project
    case "$project" in
        "$HOME" | "$home_dir" | "$home_dir"/*)
            say "run this command again from your project root to add /agent-forge-upgrade to it."
            return 0
            ;;
    esac
    "$af" setup "$project"
}

main "$@"
