# Sunny Island

**The only plant repo.** One HAOS app for everything:

1. **Tesla EVTV BMS** integration installer (LiteCAN UDP → pack sensors)
2. **Live plant dashboard** (gauges, Enphase, Tessie kWh, start/stop charge)

Vanilla JS over HA WebSocket. No WebBox UI kits.

> Old repos (`tesla_evtv_bms`, `sunny_island_detail`, `sma-webbox-dashboard`, etc.) are retired and point here.

## What it does on start

- Syncs `custom_components/tesla_evtv_bms` into `/config` (when `auto_sync: true`)
- Optionally copies YAML dashboards / examples under `/config`
- Serves the **Sunny Island** Ingress plant UI

## Layout (UI)

- **Left:** live ring gauges (SoC, V, A, power, solar, load)
- **Right:** KPIs, pack tiles, Tessie kWh, charge buttons, power trend

Sign convention: **− discharge · + charge**

## Install

1. Place this folder at `/addons/sunny_island` (or clone this repo)
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

## Hard-delete old GitHub repos

```bash
echo 'ghp_YOUR_TOKEN_WITH_delete_repo' > /root/.github-token
chmod 600 /root/.github-token
/addons/sunny_island/scripts/delete-old-repos.sh
```

## License

MIT
