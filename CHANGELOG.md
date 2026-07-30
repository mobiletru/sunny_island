# Changelog

## 2.1.3

- **Fix:** pack kWh day/hour/week meters — stop rounding every UDP tick (sub-Wh increments were lost; totals worked, period meters stalled)
- **Feature:** add-on installer syncs `ha_config/packages` → `/config/packages` (WebBox Modbus + helpers) and app-managed scripts/automations on start

## 2.1.2

- **Feature:** WebBox **Modbus TCP** package (`packages/webbox_modbus.yaml`) — plant + device parameters; dashboards Modbus view
- **Feature:** WebBox sensors on Pack detail + WebBox plant dashboards (gauges, entities, history)
- **Feature:** Auto Tessie charge amps from EVTV BMS (`tcch_amps` + cell/SoC safety); helpers package + scripts/automations
- **Fix:** plant UI WebSocket client expands HA `subscribe_entities` compressed state (`s`/`a`/`+`/`-`) so gauges and KPIs update live
- **Fix:** default LiteCAN UDP port `6550`; default series count **12S** (2×6S plant)
- **Fix:** Lovelace YAML sources use classic masonry cards (YAML-mode safe; no `type: sections`)
- **Fix:** WebBox options visible and labeled in integration Configure / reconfigure
- **Refactor:** single `normalize_entry_data` for setup / reconfigure / options
- **Refactor:** ha-client compressed-only (no dual wire formats); pure expand helpers + tests
- **Refactor:** `render_config` rewrites shipped template only (no fallback METRICS clone)
- **Fix:** installer version-gates integration sync when manifest version changes (not only `force_overwrite`)
- **Fix:** single app version via `APP_VERSION` / `SI_APP_VERSION` (no hardcoded 2.1.1)
- Integration **1.8.2**

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
