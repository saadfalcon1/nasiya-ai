#!/usr/bin/env bash
# Nasiya AI — Ubuntu 22.04/24.04 serverga bir buyruqda o'rnatish.
#   git clone https://github.com/<siz>/nasiya-ai.git /opt/nasiya_ai
#   sudo bash /opt/nasiya_ai/deploy/setup.sh
# Qayta ishga tushirish xavfsiz: mavjud .env va baza saqlanadi.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_USER=nasiya
WEB_PORT=8001

say() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
[ "$(id -u)" -eq 0 ] || { echo "Root kerak: sudo bash deploy/setup.sh"; exit 1; }

# 1 GB RAM'li serverlar uchun 2 GB swap (pip va gunicorn xotira yetmay qolmasin)
if ! swapon --show | grep -q . && [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

say "1/8 Paketlar o'rnatilmoqda"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q python3 python3-venv python3-pip postgresql ffmpeg curl git ufw openssl unzip \
  debian-keyring debian-archive-keyring apt-transport-https gnupg
if ! command -v caddy >/dev/null; then
  if ! apt-get install -y -q caddy; then
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -q && apt-get install -y -q caddy
  fi
fi

say "2/8 Tizim foydalanuvchisi"
id "$APP_USER" >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"

say "3/8 Server manzili"
IP="$(curl -4 -s --max-time 10 https://api.ipify.org || hostname -I | awk '{print $1}')"
DOMAIN="${DOMAIN:-${IP//./-}.sslip.io}"
echo "IP: $IP   Manzil: https://$DOMAIN"

ENV_FILE="$APP_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
  say "4/8 Sozlamalar (.env) — savollarga javob bering"
  read -rp "Telegram bot token (@BotFather): " BOT_TOKEN
  read -rp "Bot username (@ belgisisiz, masalan BarakaNasiyaBot): " BOT_USERNAME
  BOT_USERNAME="${BOT_USERNAME#@}"
  read -rp "LLM API kaliti (Fireworks/Baseten; hozir yo'q bo'lsa Enter): " LLM_KEY
  read -rp "LLM base URL [https://api.fireworks.ai/inference/v1]: " LLM_URL
  LLM_URL="${LLM_URL:-https://api.fireworks.ai/inference/v1}"
  read -rp "LLM model nomi [accounts/fireworks/models/muse-spark-open]: " LLM_MODEL
  LLM_MODEL="${LLM_MODEL:-accounts/fireworks/models/muse-spark-open}"
  read -rp "Ovozli xabarlar — Meta MMS serverda (kamida 4 GB RAM kerak) [y/N]: " VOICE
  STT_BACKEND=""; [[ "$VOICE" =~ ^[YyHh] ]] && STT_BACKEND=mms
  BACKEND=mock; [ -n "$LLM_KEY" ] && BACKEND=open

  DB_PASS="$(openssl rand -hex 16)"
  sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='nasiya'" | grep -q 1 \
    && sudo -u postgres psql -qc "ALTER USER nasiya WITH PASSWORD '$DB_PASS';" \
    || sudo -u postgres psql -qc "CREATE USER nasiya WITH PASSWORD '$DB_PASS';"
  sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='nasiya'" | grep -q 1 \
    || sudo -u postgres createdb -O nasiya nasiya

  cat > "$ENV_FILE" <<ENV
TELEGRAM_BOT_TOKEN=$BOT_TOKEN
BOT_USERNAME=$BOT_USERNAME
AI_BACKEND=$BACKEND
LLM_BASE_URL=$LLM_URL
LLM_API_KEY=$LLM_KEY
LLM_MODEL=$LLM_MODEL
LLM_REASONING_EFFORT=low
STT_BACKEND=$STT_BACKEND
MMS_DTYPE=bfloat16
DATABASE_URL=postgres://nasiya:$DB_PASS@localhost:5432/nasiya
DJANGO_SECRET_KEY=$(openssl rand -hex 32)
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=$DOMAIN,localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=https://$DOMAIN
WEBAPP_URL=https://$DOMAIN/app/
WEBAPP_DEV_USER=
SMS_BACKEND=console
ENV
else
  say "4/8 .env mavjud — saqlanadi"
fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod 600 "$ENV_FILE"
chmod o+rx "$APP_DIR"

say "5/8 Python muhiti va kutubxonalar"
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/venv"
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install -q --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

if grep -q '^STT_BACKEND=mms' "$ENV_FILE"; then
  say "5b/8 Ovoz modeli uchun PyTorch (CPU) + transformers — bir necha daqiqa"
  sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install -q --index-url https://download.pytorch.org/whl/cpu torch
  sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements-voice.txt"
fi

say "6/8 Baza va statik fayllar"
cd "$APP_DIR"
sudo -u "$APP_USER" venv/bin/python manage.py migrate --noinput
sudo -u "$APP_USER" venv/bin/python manage.py collectstatic --noinput -v0
chmod -R o+rX "$APP_DIR/staticfiles"

say "7/8 Xizmatlar (systemd)"
cat > /etc/systemd/system/nasiya-web.service <<UNIT
[Unit]
Description=Nasiya AI — Mini App va API (gunicorn)
After=network.target postgresql.service

[Service]
User=$APP_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:$WEB_PORT --workers 2 --timeout 120
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/nasiya-bot.service <<UNIT
[Unit]
Description=Nasiya AI — Telegram bot
After=network.target postgresql.service

[Service]
User=$APP_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python manage.py runbot
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/caddy/Caddyfile <<CADDY
$DOMAIN {
    encode gzip
    handle_path /static/* {
        root * $APP_DIR/staticfiles
        file_server
    }
    reverse_proxy 127.0.0.1:$WEB_PORT
}
CADDY

systemctl daemon-reload
systemctl enable --now nasiya-web nasiya-bot
systemctl restart nasiya-web nasiya-bot
systemctl reload caddy || systemctl restart caddy

say "8/8 Firewall"
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null

sleep 3
say "TAYYOR"
systemctl is-active --quiet nasiya-web && echo "✅ Mini App/API ishlayapti" || echo "❌ nasiya-web: journalctl -u nasiya-web -n 50"
systemctl is-active --quiet nasiya-bot && echo "✅ Bot ishlayapti"         || echo "❌ nasiya-bot: journalctl -u nasiya-bot -n 50"
echo
echo "Mini App:  https://$DOMAIN/app/"
echo "Admin:     https://$DOMAIN/admin/   (avval: cd $APP_DIR && sudo -u $APP_USER venv/bin/python manage.py createsuperuser)"
echo "Loglar:    journalctl -u nasiya-bot -f"
