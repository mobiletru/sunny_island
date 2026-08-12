# Sunny Island

**One HAOS app** for the whole plant (not two sidebar entries):

1. **Tesla EVTV BMS** integration installer (LiteCAN UDP → pack sensors + WebBox)
2. **Ingress plant UI** — the only **Sunny Island** sidebar panel (gauges, grid start, Tessie charge)

Optional **History** Lovelace YAML stays at `/sunny-island/*` but is **hidden from the sidebar**.

Vanilla JS over HA WebSocket.

> Old repos (`tesla_evtv_bms`, `sunny_island_detail`, `sma-webbox-dashboard`, etc.) are retired and point here.

## What it does on start

- Syncs `custom_components/tesla_evtv_bms` into `/config` (when `auto_sync: true`)
- Installs packages / scripts / automations (Tessie charge, pack protection)
- Copies optional History dashboard under `/config/dashboards/sunny_island`
- Unifies sidebar: **Ingress only** (hides Lovelace `sunny-island` from the sidebar)
- Serves the **Sunny Island** Ingress plant UI

## Layout (UI)

- **Left:** live ring gauges (SoC, V, A, power, solar, load)
- **Right:** KPIs, pack tiles, WebBox, grid start, Tessie charge, power trend
- **Footer:** link to History graphs (Lovelace) when you want charts

Sign convention: **− discharge · + charge** (matches `signs.py`)

## Install

1. Place this folder at `/addons/sunny_island` (or clone this repo)
2. Settings → Apps → Local → **Sunny Island** → Install → Start
3. Sidebar → **Sunny Island** (one entry — the plant app)
4. If the BMS integration is new: Devices & services → Add **Tesla EVTV BMS**
5. Set **entity prefix** on the integration to match add-on `pack_prefix` (default `battery_storage_tesla_pack`)
6. Paste a long-lived HA token in the UI (or set `ha_token` in options)

## Options

| Option | Default | Notes |
|--------|---------|--------|
| `auto_sync` | `true` | Copy BMS integration into `/config` |
| `install_dashboard` | `true` | Copy YAML dashboards under `/config/dashboards/sunny_island` |
| `force_overwrite` | `false` | Overwrite existing integration/dashboard files on sync |
| `pack_prefix` | `battery_storage_tesla_pack` | Must match integration **entity_prefix** |
| `envoy_prefix` | `sensor.envoy_…` | Envoy entity prefix |
| `ha_token` | _(empty)_ | Optional long-lived token for the plant UI |

## Development

```bash
# Pure-unit tests (no HA required)
cd /addons/sunny_island && python3 -m pytest tests/ -q
```

## License

MIT
