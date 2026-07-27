# Example HA config snippets

Copy or merge into your Home Assistant config after the add-on installs the integration.

## Integration setup

1. **Settings → Devices & services → Add integration → Tesla EVTV BMS**
2. Name: e.g. `Battery Storage Tesla Pack`
3. UDP port: `6550` (LiteCAN)
4. `cells_in_series`: `12` for 2-line 12S
5. Optional WebBox host + password

## Plant protection (optional)

See the live plant files on this HAOS host for full automations:

- Low cell ≤ 3.2 V / SoC ≤ 15% → stop Tessie car charge
- Pack |amps| ≥ 300 → stop Tessie car charge
- Device offline watch (BMS 15 min, WebBox 30 min)

Minimal script deps for car control:

- `script.shutdown_car_charger_silent`
- `script.notify_iphone` (Companion)

## Dashboard

Add-on copies dashboards to `/config/dashboards/tesla_evtv_bms/` when
`install_dashboard` is enabled. Wire into `configuration.yaml` lovelace if needed.
