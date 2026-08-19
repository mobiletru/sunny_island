#!/usr/bin/env sh
set -e

# s6-overlay (HA base image) does not pass Docker env to CMD unless
# with-contenv is used. Without SUPERVISOR_TOKEN the installer cannot
# talk to Core (BMS setup, enable automations).
if [ -z "${SUPERVISOR_TOKEN:-}${HASSIO_TOKEN:-}" ] && [ -x /usr/bin/with-contenv ]; then
  exec /usr/bin/with-contenv "$0" "$@"
fi

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

echo "[sunny_island] plant UI :8098 (Ingress)"
# Finish Tesla EVTV BMS config-entry setup after the UI is listening so
# a Core restart / slow API does not keep Ingress down.
python3 /opt/sunny_island/bms_setup.py --ensure-bms &
exec python3 /opt/sunny_island/http_server.py
