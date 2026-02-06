#!/usr/bin/env bash
set -euo pipefail

python -c "from app.start_code import initialize_auth_files, get_start_code; initialize_auth_files(); print(f'/start {get_start_code()}')"
