#!/bin/bash
# Ink Pusher catalog tools -- Mac setup
#
# Run from Terminal with:
#   curl -fsSL https://raw.githubusercontent.com/Ink-Pusher/Mockup-Creator/main/setup.sh | bash
#
# Installs Homebrew (if missing), GitHub Desktop and Python, then the
# Python packages the catalog scripts need. Idempotent: run it twice and
# the second run just confirms what is already there. Ends by printing
# the four steps only a person can do (accounts and secrets).

set -u

step() { printf '\n\033[36m== %s\033[0m\n' "$1"; }
ok()   { printf '   \033[32mOK\033[0m  %s\n' "$1"; }
skip() { printf '   --  %s\n' "$1"; }
fail() {
  printf '\n   \033[31mPROBLEM:\033[0m %s\n' "$1"
  printf '   Nothing was broken -- fix the line above and run the installer again,\n'
  printf '   or fall back to the manual steps in "Catalog Onboarding - Part 1".\n'
  exit 1
}

printf '\n\033[36mInk Pusher catalog tools -- setup\033[0m\n'
printf 'This takes about five minutes. Homebrew may ask for your Mac password.\n'

# ---- Homebrew (the Mac package manager) ----
step "Homebrew"
if command -v brew >/dev/null 2>&1; then
  skip "already installed"
else
  # Homebrew's own installer; it explains itself and asks for the password.
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" || fail "Homebrew install did not finish."
  # Apple Silicon installs to /opt/homebrew, which isn't on PATH in this shell yet.
  [ -x /opt/homebrew/bin/brew ] && eval "$(/opt/homebrew/bin/brew shellenv)"
  [ -x /usr/local/bin/brew ] && eval "$(/usr/local/bin/brew shellenv)"
  command -v brew >/dev/null 2>&1 || fail "Homebrew installed but isn't on PATH -- close Terminal, reopen, run this again."
  ok "installed"
fi

# ---- GitHub Desktop ----
step "GitHub Desktop"
if [ -d "/Applications/GitHub Desktop.app" ] || [ -d "$HOME/Applications/GitHub Desktop.app" ]; then
  skip "already installed"
else
  brew install --cask github || fail "GitHub Desktop install failed."
  ok "installed"
fi

# ---- Python 3 ----
step "Python"
if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)'; then
  skip "already installed: $(python3 --version)"
else
  brew install python || fail "Python install failed."
  ok "installed"
fi

# ---- The packages the catalog scripts need ----
step "Python packages (9 of them -- this is the slow part)"
PKGS="anthropic requests pillow numpy scipy pytoshop psd-tools six cloudscraper pymupdf"
if python3 -m pip install --quiet --disable-pip-version-check $PKGS 2>/dev/null; then
  ok "all packages installed"
else
  # Newer Macs mark the system Python "externally managed"; this flag is the
  # documented way past it for user tooling like ours.
  python3 -m pip install --quiet --disable-pip-version-check --break-system-packages $PKGS \
    || fail "package install failed -- scroll up for pip's error."
  ok "all packages installed"
fi

# ---- Hand over the human steps ----
printf '\n\033[32mAutomated part: DONE.\033[0m\n'
cat <<'STEPS'

Now finish these 4 steps yourself:

  1. Open GitHub Desktop (Applications folder) and sign in.
     (Accept the collaborator invite from Timm in your email first --
      no GitHub account yet? Create one free at github.com/join.)

  2. In GitHub Desktop: File > Clone Repository > pick Ink-Pusher/Mockup-Creator.
     IMPORTANT: save it somewhere OUTSIDE iCloud -- not Documents or
     Desktop. A folder like ~/Developer is good. (iCloud syncing fights
     with Git and has corrupted this repo before.)

  3. In GitHub Desktop: Repository > Open in Terminal, then run:
        python3 build_descriptions.py setkey
     and paste the API key Timm gives you. (Your paste stays invisible
     on purpose -- paste, press Return.)

  4. In that same window, run:
        python3 build_descriptions.py doctor
     When every line says [OK], you're fully set up.

STEPS
