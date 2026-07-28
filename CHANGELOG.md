# Changelog

## 2.1.1

- **Fix:** stop rewriting host `configuration.yaml`; ship `lovelace_include.yaml` instead
- **Fix:** Lovelace paths only reference shipped YAML (no missing `webbox.yaml`)
- **Fix:** energy totals no longer reset after Core restart (seed accumulator from restore)
- **Fix:** unload dispatcher, utility meters, and rolling-average timers on entry unload
- **Fix:** rolling averages are per-pack (`PackRuntime`), not module-global
- **Fix:** integration `entity_prefix` aligns with add-on `pack_prefix`
- Config flow: unique_id by UDP port, OptionsFlow, reload on options change
- Default `force_overwrite: false`; all copy paths honor the flag
- `render_config.py` rewrites consts line-by-line; writes `/data/runtime.json`
- Unit tests for parser / signs / calculations / energy seed / WebBox ajax parse
- Versions: app **2.1.1**, integration **1.8.0**

## 2.1.0

- SMA WebBox sensors on plant UI: plant power, daily yield, total yield
- WebBox ring gauge + tiles next to Envoy solar

## 2.0.0

- **All-in-one app**: plant UI + Tesla EVTV BMS integration installer
- Syncs `custom_components/tesla_evtv_bms` into `/config` on start
- Ships dashboards + protection / car-charger YAML examples
- Replaces separate `tesla_evtv_bms` and UI-only sunny_island apps

## 1.0.0

- Plant UI only (gauges left · KPIs / Tessie right)
