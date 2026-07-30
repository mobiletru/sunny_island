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

## WebBox Modbus TCP

On add-on start, packages are installed into `/config/packages/`:
- `sunny_island.yaml` — helpers (auto amps, voltage stop)
- `webbox_modbus.yaml` — Modbus TCP sensors

Ensure `configuration.yaml` includes:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

1. Enable Modbus on the WebBox (Interfaces → Modbus)
2. Add to `/config/secrets.yaml` (see `ha_config/secrets.example.yaml`):

```yaml
webbox_host: 192.168.x.x
webbox_password: sma   # optional; for BMS JSON-RPC if enabled
```

3. Set the same host/password on **Tesla EVTV BMS → Configure** for HTTP `home.ajax` sensors
4. Restart Core after first install

| Unit ID | Role | Example sensors |
|---------|------|-----------------|
| 1 | Gateway | profile, WebBox serial |
| 2 | Plant | plant power, daily/total yield |
| 3 | Device (SI) | AC power, grid V/Hz, status, battery V/temp |

Dashboards: **WebBox plant → Modbus** and **Pack detail → Solar & car**.

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
