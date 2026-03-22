#!/usr/bin/env bash
# Install smart-home Python deps on Raspberry Pi when piwheels / SSL errors occur.
# Usage: bash scripts/install_smart_home_deps.sh
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -f venv/bin/activate ]]; then
  # shellcheck source=/dev/null
  source venv/bin/activate
fi
export PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.org/simple}"
export PIP_EXTRA_INDEX_URL="${PIP_EXTRA_INDEX_URL:-}"
# Avoid piwheels SSL issues: use PyPI only (slower on ARM but reliable)
pip install --upgrade pip setuptools wheel \
  --trusted-host pypi.org --trusted-host files.pythonhosted.org
pip install python-miio python-kasa yeelight \
  --trusted-host pypi.org --trusted-host files.pythonhosted.org
