# Sunny Island app (one plant app)

## Parts

1. **BMS installer** — copies `tesla_evtv_bms` into `/config/custom_components`
2. **Plant UI** — **the only sidebar entry** (Ingress: pack + WebBox + Enphase + Tessie)
3. **History** (optional) — Lovelace YAML at `/sunny-island/*`, **not** in the sidebar

## Integration sync

On start, with `auto_sync: true` and `map: homeassistant_config` at `/config`:

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

## SMA Sunny WebBox (HTTP + Modbus proxy)

WebBox is built into the **Tesla EVTV BMS** integration (Sunny Island app):

1. Enable **Modbus** on the WebBox (Interfaces → Modbus)
2. **Settings → Devices & services → Tesla EVTV BMS → Configure**
   - **SMA WebBox IP** (e.g. `192.168.100.180`)
   - **Password** (optional; JSON-RPC only)
   - **Enable WebBox Modbus TCP** (default on), port **502**
   - Unit IDs: gateway **1**, plant **2**, device/SI **3**
3. Restart Core after first install

Creates `sensor.<pack_prefix>_webbox_*` — plant power/yields, grid V/Hz, SI battery V/temp/SoC, status, reactive/apparent, serials, **grid start** sensors (connection timer, operating status, generator status, grid control mode).

### Grid start / control (parameter write)

**Start grid** (plant UI button / select / service) writes **WebBox JSON-RPC
`SetParameter`** on channel **`GdManStr`** (values `Start` | `Auto` | `Stop`).
Modbus register 40527 is fallback only — on SI6048UM it typically returns
illegal address. After updating the app, **restart HA Core** so the
integration reloads (files alone are not enough while Core is running).

Writes use **WebBox JSON-RPC `SetParameter`** on channel **`GdManStr`**
(`Start` | `Auto` | `Stop`). That is the path that works on SI6048UM + Sunny
WebBox; Modbus holding **40527** often returns illegal address and is only a
fallback. Set the WebBox access password in **Configure** (plain text, e.g.
`sma` — the integration MD5-hashes it for RPC).

| Entity / service | Role |
|------------------|------|
| `select.<prefix>_webbox_grid_control` | **Write** GdManStr via SetParameter — Off · Manual On (request grid) · Automatic |
| `sensor.<prefix>_webbox_grid_connection_time` | Seconds until next grid connection attempt (**30199**) |
| `sensor.<prefix>_webbox_operating_status` | Parallel grid / Backup / Generator / Emergency charge (**33003**) |
| `sensor.<prefix>_webbox_generator_status` | Generator status enum (**30917**) |
| Service `tesla_evtv_bms.set_grid_control` | Same write as the select (`mode: manual_on` / `automatic` / `off`) |

Example:

```yaml
service: tesla_evtv_bms.set_grid_control
data:
  mode: manual_on   # start / request grid (GdManStr=Start)
```

> If the write fails: enable **RPC** on the WebBox, confirm the password, and
> check unit ID **3** is the SI when using the Modbus fallback.

| Unit ID | Role |
|---------|------|
| 1 | Gateway |
| 2 | Plant parameters |
| 3 | First SI / inverter on RS485 |

**Sidebar:** one panel — Ingress **Sunny Island** (plant controls + live gauges).

**History:** optional multi-view Lovelace (Overview · Cells · Energy · WebBox · Solar & car)
at `/sunny-island/overview` — linked from the plant UI footer; hidden from sidebar so
you do not get two “Sunny Island” apps.

Add-on start also installs `packages/sunny_island.yaml` (Tessie helpers) and unifies the sidebar.

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

- `script.start_car_charger` — wake · BMS amps · Tessie start; **auto-raises
  charge limit** if car SoC is already at/above `number.x_charge_limit`
  (otherwise Tesla stays `complete` and will not charge)
- `script.shutdown_car_charger`

