# Sunny Island

Home Assistant OS **app** — live plant dashboard for:

- Tesla pack via **EVTV BMS** (2-line 12S)
- **Enphase** solar / load
- **Tessie** car kWh + start/stop charge

Vanilla JS over the HA WebSocket API. No WebBox, no third-party UI kits.

## Layout

- **Left:** live ring gauges (SoC, V, A, power, solar, load)
- **Right:** KPIs, pack tiles, Tessie kWh, charge buttons, power trend

Sign convention: **− discharge · + charge**

## Install (local)

1. Copy this folder to `/addons/sunny_island` on the HAOS host  
2. Settings → Apps → Local → **Sunny Island** → Install → Start  
3. Open the sidebar **Sunny Island** panel (Ingress)  
4. Paste a long-lived access token once, or set `ha_token` in app options  

Requires the **tesla_evtv_bms** custom integration (and Enphase / Tessie entities as configured).

## Options

| Option | Default | Notes |
|--------|---------|--------|
| `pack_prefix` | `battery_storage_tesla_pack` | BMS sensor prefix (without `sensor.`) |
| `envoy_prefix` | `sensor.envoy_…` | Envoy entity prefix |
| `ha_token` | _(empty)_ | Optional long-lived token auto-inject |
