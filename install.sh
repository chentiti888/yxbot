#!/bin/bash
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
  echo "请用 root 执行：bash install.sh"
  exit 1
fi
DIR="/opt/tg-guess-bot"
mkdir -p "$DIR"
cp app.py requirements.txt tg-guess-bot.service "$DIR/"
python3 -m pip install --break-system-packages -r "$DIR/requirements.txt"
if [ ! -f /etc/tg-guess-bot.env ]; then
  cp .env.example /etc/tg-guess-bot.env
  chmod 600 /etc/tg-guess-bot.env
  echo
  echo "已创建 /etc/tg-guess-bot.env，请编辑填写 BOT_TOKEN 和 ADMIN_ID："
  echo "  nano /etc/tg-guess-bot.env"
  echo "保存后再次执行：bash install.sh"
  exit 0
fi
cp "$DIR/tg-guess-bot.service" /etc/systemd/system/tg-guess-bot.service
systemctl daemon-reload
systemctl enable --now tg-guess-bot
systemctl status tg-guess-bot --no-pager || true
