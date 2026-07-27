#!/usr/bin/env sh
set -e

export SI_OPTIONS="${SI_OPTIONS:-/data/options.json}"
export SI_CONFIG_OUT="${SI_CONFIG_OUT:-/data/config.js}"
export SI_CONFIG_TEMPLATE="${SI_CONFIG_TEMPLATE:-/opt/sunny_island/www/js/config.js}"

echo "[sunny_island] rendering config"
python3 /opt/sunny_island/render_config.py

mkdir -p /run/nginx /var/lib/nginx/tmp /var/log/nginx /tmp/nginx
echo "[sunny_island] nginx :8098 (Ingress)"
exec nginx -g 'daemon off;'
