#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${ROOT_DIR}/venv/bin/python"
TESTS_DIR="${ROOT_DIR}/tests"

echo "[smoke] compileall"
PYTHONPYCACHEPREFIX="/tmp/solobot_pycache" "${PYTHON_BIN}" -m compileall "${ROOT_DIR}" -q -x "/venv/|/\\.git/|/__pycache__/"

echo "[smoke] unittest"
cd /tmp
PYTHONPATH="${ROOT_DIR}" "${PYTHON_BIN}" -m unittest discover -s "${TESTS_DIR}" -q

echo "[smoke] ok"
