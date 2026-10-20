#!/bin/bash
set -euo pipefail
cp /opt/tg-guess-bot/tg-guess-bot.service /etc/systemd/system/tg-guess-bot.service
systemctl daemon-reload
systemctl enable --now tg-guess-bot
systemctl status tg-guess-bot --no-pager
