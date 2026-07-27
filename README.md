# Sunny Island

**One HAOS app** for the whole plant:

1. **Tesla EVTV BMS** custom integration installer (LiteCAN UDP → pack sensors)
2. **Live plant dashboard** (gauges, Enphase, Tessie kWh, start/stop charge)

Vanilla JS over HA WebSocket. No WebBox UI kits.

## What it does on start

- Syncs `custom_components/tesla_evtv_bms` into `/config` (when `auto_sync: true`)
- Optionally copies YAML dashboards / examples under `/config`
- Serves the **Sunny Island** Ingress plant UI

## Layout (UI)

- **Left:** live ring gauges (SoC, V, A, power, solar, load)
- **Right:** KPIs, pack tiles, Tessie kWh, charge buttons, power trend

Sign convention: **− discharge · + charge**

## Install

1. Place this folder at `/addons/sunny_island` (or clone the repo)
2. Settings → Apps → Local → **Sunny Island** → Install → Start
3. Sidebar → **Sunny Island**
4. If the BMS integration is new: Devices & services → Add **Tesla EVTV BMS**
5. Paste a long-lived HA token in the UI (or set `ha_token` in options)

## Options

| Option | Default | Notes |
|--------|---------|--------|
| `auto_sync` | `true` | Copy BMS integration into `/config` |
| `install_dashboard` | `true` | Copy YAML dashboards under `/config/dashboards/sunny_island` |
| `force_overwrite` | `true` | Overwrite existing integration files on sync |
| `pack_prefix` | `battery_storage_tesla_pack` | Sensor prefix (no `sensor.`) |
| `envoy_prefix` | `sensor.envoy_…` | Envoy entity prefix |
| `ha_token` | _(empty)_ | Optional long-lived token for the plant UI |

## Requirements

- HAOS with local add-ons
- For live data: EVTV BMS on LiteCAN UDP, Enphase Envoy, optional Tessie

## Replaces

This **2.0.0** app replaces the separate apps:

- `sunny_island` (UI only)
- `tesla_evtv_bms` (integration installer only)
