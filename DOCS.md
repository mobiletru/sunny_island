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

## Scripts

Start/stop charge buttons call:

- `script.start_car_charger`
- `script.shutdown_car_charger`
