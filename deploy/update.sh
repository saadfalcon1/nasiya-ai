#!/usr/bin/env bash
# Yangi kodni serverga qo'yish (git yoki scp bilan yuklangan papka):  sudo bash /opt/nasiya_ai/deploy/update.sh
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"
if [ -d .git ]; then
  git config --global --add safe.directory "$APP_DIR" || true
  git pull --ff-only
fi
chown -R nasiya:nasiya "$APP_DIR"
sudo -u nasiya venv/bin/pip install -q -r requirements.txt
if grep -q '^STT_BACKEND=mms' .env; then
  # 1 GB RAM bo'lsa swap (setup.sh yaratgan bo'lmasa)
  if ! swapon --show | grep -q . && [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
  fi
  echo "==> Ovoz modeli: PyTorch (CPU) + transformers"
  sudo -u nasiya venv/bin/pip install -q --index-url https://download.pytorch.org/whl/cpu torch
  sudo -u nasiya venv/bin/pip install -q -r requirements-voice.txt
fi
sudo -u nasiya venv/bin/python manage.py migrate --noinput
sudo -u nasiya venv/bin/python manage.py collectstatic --noinput -v0
chmod -R o+rX staticfiles
systemctl restart nasiya-web nasiya-bot
sleep 2
systemctl is-active --quiet nasiya-web && systemctl is-active --quiet nasiya-bot && echo "✅ Yangilandi" \
  || echo "❌ Xato: journalctl -u nasiya-bot -n 50 ; journalctl -u nasiya-web -n 50"
