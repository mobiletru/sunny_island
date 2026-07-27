#!/usr/bin/env sh
set -e

export SI_OPTIONS="${SI_OPTIONS:-/data/options.json}"
export SI_CONFIG_OUT="${SI_CONFIG_OUT:-/data/config.js}"
export SI_CONFIG_TEMPLATE="${SI_CONFIG_TEMPLATE:-/opt/sunny_island/www/js/config.js}"
export SI_STATUS_OUT="${SI_STATUS_OUT:-/data/status.json}"
export SI_HA_CONFIG="${SI_HA_CONFIG:-/config}"
export SI_BUNDLE="${SI_BUNDLE:-/opt/sunny_island}"

echo "[sunny_island] syncing Tesla EVTV BMS integration → /config"
# Do not fail the whole app if config map is missing; UI still serves
python3 /opt/sunny_island/install_integration.py || echo "[sunny_island] integration sync had errors (UI still starts)"

echo "[sunny_island] rendering plant UI config"
python3 /opt/sunny_island/render_config.py

mkdir -p /run/nginx /var/lib/nginx/tmp /var/log/nginx /tmp/nginx
echo "[sunny_island] nginx :8098 (Ingress plant UI)"
exec nginx -g 'daemon off;'
