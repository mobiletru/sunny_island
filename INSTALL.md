# Install Sunny Island (HAOS app)

## From GitHub (local add-on)

1. On the HAOS host:

```bash
cd /addons
git clone https://github.com/mobiletru/sunny_island.git sunny_island
```

2. In Home Assistant: **Settings → Apps → ⋮ → Check for updates** (or reload)
3. Install **Sunny Island** from Local add-ons → **Start**
4. Enable **Show in sidebar** if needed
5. Open **Sunny Island** and paste a long-lived access token (or set `ha_token` in options)

## Requirements

- Custom integration **tesla_evtv_bms** (pack sensors)
- Enphase Envoy sensors (configure `envoy_prefix`)
- Optional: Tessie entities + `script.start_car_charger` / `script.shutdown_car_charger`
