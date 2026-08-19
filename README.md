# Sunny Island

**One HAOS app** for the whole plant (one sidebar entry):

1. **Tesla EVTV BMS** — LiteCAN UDP pack sensors + SMA WebBox
2. **Ingress plant UI** — gauges, grid start, Tessie charge, wrench/quirks

Optional **History** Lovelace YAML stays at `/sunny-island/*` but is **hidden from the sidebar**.

Vanilla JS over HA WebSocket.

## This is the only plant app

These older apps are **retired** and redirect here. Do not install them:

| Retired repo | Used to be |
|--------------|------------|
| `tesla_evtv_bms` | HACS EVTV BMS integration |
| `tesla_evtv_bms_v3` | 3 add-ons: BMS installer, monitor, plant UI |
| `sunny_island_detail` | Separate Ingress dashboard |
| `HA_SMA_WEBBOX` | WebBox / Sunny Island parameter add-on |
| `sma-webbox-dashboard` | HACS WebBox dashboard |
| `sunny-island-can` | SocketCAN add-on |

Install **only** this repository.

## What it does on start

- Syncs `custom_components/tesla_evtv_bms` into `/config` (when `auto_sync: true`)
- Creates the **Tesla EVTV BMS** config entry when `auto_setup_bms: true`
- Installs packages / scripts / automations (Tessie charge, pack protection)
- Adds `homeassistant.packages` include when missing
- Copies optional History dashboard under `/config/dashboards/sunny_island`
- Unifies sidebar: **Ingress only** (hides Lovelace `sunny-island` from the sidebar)
- Serves the **Sunny Island** Ingress plant UI

## Layout (UI)

- **Left:** live ring gauges (SoC, V, A, power, solar, load)
- **Right:** KPIs, pack tiles, WebBox, grid start, Tessie charge, power trend
- **Footer:** link to History graphs (Lovelace) when you want charts

Sign convention: **− discharge · + charge** (matches `signs.py`)

## Install (Home Assistant OS App)

This GitHub repo is an **app repository**. Add it once, then install **Sunny Island** from **Settings → Apps**.

[![Add this app repository](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fmobiletru%2Fsunny_island)

1. **Settings → Apps → Install app** (the App store)
2. **⋮ → Repositories** → add `https://github.com/mobiletru/sunny_island` → **Add**
3. Find **Sunny Island** → **Install** → **Start**
4. Sidebar → **Sunny Island** (one Ingress entry — the plant app)
5. The app adds **Tesla EVTV BMS** (UDP 6550, prefix `battery_storage_tesla_pack`) unless it already exists
6. Optional: set **WebBox host** in app options, or Configure the BMS integration
7. Paste a long-lived HA token in the UI (or set `ha_token` in options)

If you previously ran **Tesla EVTV BMS**, **Sunny Island Detail**, **WebBox**, or the v3 monitor/combo apps, stop and uninstall them after this app starts (sidebar duplicates go away automatically). See [INSTALL.md](INSTALL.md).

Local / development: clone this repo to `/addons/sunny_island`, then **Settings → Apps → Local → Sunny Island**.

## Options

| Option | Default | Notes |
|--------|---------|--------|
| `auto_sync` | `true` | Copy BMS integration into `/config` |
| `install_dashboard` | `true` | Copy YAML dashboards under `/config/dashboards/sunny_island` |
| `force_overwrite` | `false` | Overwrite existing integration/dashboard files on sync |
| `retire_legacy_apps` | `true` | Stop leftover plant apps and hide their sidebar panels |
| `pack_prefix` | `battery_storage_tesla_pack` | Must match integration **entity_prefix** |
| `envoy_prefix` | `sensor.envoy_…` | Envoy entity prefix |
| `ha_token` | _(empty)_ | Optional long-lived token for the plant UI |
| `auto_setup_bms` | `true` | Create Tesla EVTV BMS config entry if missing |
| `bms_udp_port` | `6550` | LiteCAN UDP listen port |
| `webbox_host` | _(empty)_ | Optional SMA WebBox IP on the BMS entry |
| `webbox_password` | _(empty)_ | Optional WebBox RPC password |

## Development

```bash
# Pure-unit tests (no HA required)
cd /addons/sunny_island && python3 -m pytest tests/ -q
```

## License

MIT
