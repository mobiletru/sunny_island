# Sunny Island app (all-in-one)

## Parts

1. **BMS installer** — copies `tesla_evtv_bms` into `/config/custom_components`
2. **Plant UI** — Ingress dashboard (pack + Enphase + Tessie)

## Integration sync

On start, with `auto_sync: true` and `map: config:rw`:

- `/config/custom_components/tesla_evtv_bms` (honors `force_overwrite`)
- optional `/config/dashboards/sunny_island` + `lovelace_include.yaml`
- examples under `/config/sunny_island_examples`

**Never rewrites** `/config/configuration.yaml`.

Status is written to `/data/status.json`.

## Plant UI connection

WebSocket to HA (`/api/websocket`) using either:

1. A long-lived access token entered in the app, or  
2. The optional `ha_token` app option (injected on first load)

## Entities

- Integration option **entity_prefix** → `sensor.<prefix>_<key>`
- Add-on option **pack_prefix** must match (drives plant UI `config.js`)
- Tessie: `sensor.x_*` / `switch.x_charge`

## SMA Sunny WebBox

WebBox is configured on the **Tesla EVTV BMS** integration (not the Sunny Island add-on options):

1. **Settings → Devices & services → Tesla EVTV BMS → Configure** (gear), or **⋮ → Reconfigure**
2. Set **SMA WebBox IP / hostname** (no `http://`)
3. Optional password (only if JSON-RPC is enabled on the WebBox)
4. Submit — creates `sensor.<prefix>_webbox_power`, `_webbox_daily_yield`, `_webbox_total_yield`

Leave the host empty to disable the solar poller. Pack detail + WebBox plant dashboards show these sensors (unavailable until host is set).

## Auto Tessie charge amps (from EVTV BMS)

While the car is charging, automation **Tessie auto amps from EVTV BMS** sets
`number.x_charge_current` from pack sensors:

| Signal | Role |
|--------|------|
| `sensor.*_tcch_amps` | Base target (BMS charge current command) |
| Lowest cell / SoC / `charge_enable` | Safety clamp → 0 or reduced A |
| Highest cell ≥ 4.00 / 4.05 V | Taper amps |
| Pack current (heavy discharge) | Soft limit while house pack is unloading |
| `input_number.tessie_amps_cap` | Hard ceiling (default 32 A) |
| `input_boolean.auto_tessie_amps` | Master enable (default on) |

Install helpers via package `packages/sunny_island.yaml` and merge
`ha_config/scripts.*.yaml` + `automations.*.yaml` into Core scripts/automations.

## Scripts

Start/stop charge buttons call:

- `script.start_car_charger`
- `script.shutdown_car_charger`
