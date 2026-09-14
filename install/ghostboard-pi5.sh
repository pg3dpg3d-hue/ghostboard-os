#!/usr/bin/env bash
# Raspberry Pi OS 64-bit (Debian 13). Ne lance aucune étape Intel.
set -euo pipefail
exec python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/pi5.py" "$@"
