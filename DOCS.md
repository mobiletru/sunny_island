# Sunny Island app

Ingress plant UI for Tesla EVTV BMS + Enphase + Tessie.

## Connection

The UI opens a WebSocket to Home Assistant (`/api/websocket`) using either:

1. A long-lived access token entered in the app, or  
2. The optional `ha_token` app option (injected on first load)

## Entities

Configured via `pack_prefix` and `envoy_prefix` options. Tessie entities use
the `sensor.x_*` / `switch.x_charge` IDs from your Tessie integration.

## Scripts

Start/stop charge buttons call:

- `script.start_car_charger`
- `script.shutdown_car_charger`
