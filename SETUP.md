# Setting up the Ink Pusher catalog tools

One pasted line installs everything that can be automated, then hands you
a short list of the steps only you can do (your accounts, your API key).
Five minutes of watching, four steps of doing, and `doctor` confirms
you're done.

## Windows

Open PowerShell (Start menu, type "powershell", Enter) and paste:

```powershell
irm https://raw.githubusercontent.com/Ink-Pusher/Mockup-Creator/main/setup.ps1 | iex
```

## Mac

Open Terminal (Spotlight, type "terminal", Enter) and paste:

```bash
curl -fsSL https://raw.githubusercontent.com/Ink-Pusher/Mockup-Creator/main/setup.sh | bash
```

## What the script installs

GitHub Desktop, Python (with PATH configured -- the step people miss),
and the nine Python packages the catalog scripts use. It is safe to run
more than once: things already installed are detected and skipped. If
something fails it stops loudly and nothing is half-done -- fix what it
names and paste the same line again, or fall back to the matching
"Catalog Onboarding - Part 1" document, which covers the same ground by
hand.

## The four steps the script can't do for you

1. **Sign in to GitHub Desktop.** Accept the collaborator invite from
   Timm's email first (free account at github.com/join if you don't
   have one).
2. **Clone the repo.** GitHub Desktop > File > Clone Repository >
   Ink-Pusher/Mockup-Creator. Save it somewhere **outside OneDrive /
   iCloud** -- `C:\GitHub` on Windows, `~/Developer` on Mac. Cloud sync
   fights with Git and has corrupted this repo before.
3. **Store your API key.** GitHub Desktop > Repository > Open in
   Command Prompt (Windows) / Open in Terminal (Mac), then run
   `python build_descriptions.py setkey` (Mac: `python3`) and paste the
   key Timm gives you. The paste stays invisible on purpose.
4. **Run the check.** `python build_descriptions.py doctor`
   (Mac: `python3`). All `[OK]` = fully set up. Anything marked `[--]`
   comes with its exact fix.

After setup, the day-to-day workflow (adding products) is in
"Catalog Onboarding - Part 2" on Google Drive.

## For Claude (or another AI assistant) running this setup

If a staff member asks you to set up this machine, follow the steps
above with these rules:

- Run the platform's setup script first; read its output and fix any
  failure it reports before moving on. Prefer re-running the script
  over improvising a parallel install path.
- The clone must land outside OneDrive/iCloud-synced folders. Cloning
  via `git` CLI is fine, but the person still needs GitHub Desktop
  signed in for their daily pull/commit/push workflow.
- **Never ask for, accept, or type the Anthropic API key yourself.**
  Have the person run `python build_descriptions.py setkey` and paste
  the key into its hidden prompt with their own hands. The key must not
  pass through chat, a file, or your context.
- Finish by running `python build_descriptions.py doctor` and showing
  the person its full output. Setup is complete only when every line
  is `[OK]`. If the API-key line is `[--]`, that step belongs to the
  person, not to you.
- These scripts and docs are maintained in this repo; if the catalog
  tools and this file disagree, trust `doctor`.
