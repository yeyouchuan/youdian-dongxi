#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
sdk_dir="${project_dir}/GALAXEA-A1Z"
venv_dir="${project_dir}/.venv"
sdk_repo="https://github.com/userguide-galaxea/GALAXEA-A1Z.git"
sdk_commit="e931ecd0e25ad35df251097ba42921b3d2fa7224"
python_bin="${PYTHON_BIN:-python3.12}"

cd "${project_dir}"

if ! command -v "${python_bin}" >/dev/null 2>&1 &&
  [[ ! -x "${python_bin}" ]]; then
  echo "Python 3.12 is required. Install it or set PYTHON_BIN." >&2
  exit 1
fi

python_version="$("${python_bin}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "${python_version}" != "3.12" ]]; then
  echo "Python 3.12 is required; ${python_bin} is ${python_version}." >&2
  exit 1
fi

if [[ ! -d "${sdk_dir}/.git" ]]; then
  git clone --branch gripper --single-branch "${sdk_repo}" "${sdk_dir}"
fi

if ! git -C "${sdk_dir}" diff --quiet -- . ':(exclude)**/*.pyc' ||
  ! git -C "${sdk_dir}" diff --cached --quiet -- . ':(exclude)**/*.pyc'; then
  echo "Refusing to replace a modified GALAXEA-A1Z checkout: ${sdk_dir}" >&2
  exit 1
fi

git -C "${sdk_dir}" fetch --depth 1 origin "${sdk_commit}"
git -C "${sdk_dir}" checkout --detach "${sdk_commit}"

"${python_bin}" -m venv "${venv_dir}"
"${venv_dir}/bin/python" -m pip install --upgrade pip
"${venv_dir}/bin/python" -m pip install -r requirements-macos.txt

echo
echo "Ready."
echo "Run offline checks before connecting hardware:"
echo "  cd ${project_dir}"
echo "  PYTHONPATH=. .venv/bin/pytest -q tests"
echo "  PYTHONPATH=. .venv/bin/python scripts/a1z_safe_dance.py --audit-only"
