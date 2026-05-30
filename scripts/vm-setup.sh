#!/usr/bin/env bash
# ─── One-time provisioning for the Dymphna VoIP host ──────────────────────────
# Target: a fresh Debian/Ubuntu GCP VM (the default image family).
# Installs Docker + the Compose plugin, then builds and starts the stack.
#
# Usage (on the VM, from the repo root where docker-compose.yml lives):
#   cp .env.example .env      # then edit .env and fill in your secrets
#   ./scripts/vm-setup.sh
#
set -euo pipefail

cd "$(dirname "$0")/.."   # repo root

# ── Docker engine ─────────────────────────────────────────────────────────────
if ! command -v docker >/dev/null 2>&1; then
  echo "[setup] Installing Docker Engine…"
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER" || true
  echo "[setup] Added $USER to the docker group — you may need to log out/in for non-sudo docker."
fi

# ── Compose plugin ────────────────────────────────────────────────────────────
if ! docker compose version >/dev/null 2>&1; then
  echo "[setup] Installing docker compose plugin…"
  sudo apt-get update -y
  sudo apt-get install -y docker-compose-plugin
fi

# ── .env guard ────────────────────────────────────────────────────────────────
if [ ! -f .env ]; then
  echo "[setup] ERROR: .env not found." >&2
  echo "        Run:  cp .env.example .env   then fill in JWT_SECRET, VOIPMS_*, etc." >&2
  exit 1
fi

# ── Build + start ─────────────────────────────────────────────────────────────
echo "[setup] Building and starting the stack…"
sudo docker compose up -d --build

echo
echo "[setup] Done. Useful checks:"
echo "  sudo docker compose ps"
echo "  sudo docker compose logs -f acme-companion        # watch the TLS cert get issued"
echo "  sudo docker compose exec asterisk asterisk -rx 'http show status'"
