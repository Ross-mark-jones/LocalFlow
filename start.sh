#!/bin/sh
# LocalFlow launcher.
#
# The repo lives in ~/Documents, which iCloud syncs — a Python venv in there
# gets its files evicted/churned by iCloud and imports break intermittently.
# UV_PROJECT_ENVIRONMENT keeps the env in ~/.localflow, outside iCloud.
cd "$(dirname "$0")" || exit 1
export UV_PROJECT_ENVIRONMENT="$HOME/.localflow/venv"
exec uv run localflow "$@"
