#!/bin/bash
# Open Learnage TUI in Terminal.app (or iTerm2 if preferred).
# Headless shells burn CPU on Textual 8.2.8 — always needs a real TTY.

set -e

PROJ=/Users/amre/Projects/Learnage
WORKERS="${1:-8}"

# Try iTerm2 first, then Terminal.app
if osascript -e 'exists application "iTerm"' >/dev/null 2>&1; then
  osascript <<EOF
tell application "iTerm"
  create window with default profile
  tell current session of current window
    write text "cd '$PROJ' && uv run learnage tui --workers $WORKERS"
  end tell
  activate
end tell
EOF
else
  osascript <<EOF
tell application "Terminal"
  activate
  do script "cd '$PROJ' && uv run learnage tui --workers $WORKERS"
end tell
EOF
fi

echo "Launched in terminal — workers=$WORKERS"
