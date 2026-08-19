# Changelog

## 2.2.12

- **Fix:** Ingress crash `mkdir: can't create directory '/var/lib/nginx/tmp': Permission denied`
  — HAOS AppArmor cannot write `/var/lib/nginx` or `/var/log/nginx`. nginx now uses
  `/tmp/nginx` + `/dev/stderr` only
- **Fix:** `SUPERVISOR_TOKEN` missing under s6-overlay — `run.sh` re-execs via
  `with-contenv` so Core API calls work
- **Feature:** auto-add **Tesla EVTV BMS** config entry (`auto_setup_bms`, UDP port
  `6550`, optional `webbox_host` / `webbox_password`). Requests one Core restart
  if the custom component is not loaded yet
- **Feature:** surgically add `homeassistant.packages: !include_dir_named packages`
  when missing so plant helpers load

## 2.2.11

- **HAOS App store:** add `repository.yaml` so this GitHub repo can be added under
  Settings → Apps → Repositories (no `/addons` copy required)
- **Packaging:** `icon.png`, `logo.png`, `translations/en.yaml`, custom `apparmor.txt`
- **config.yaml:** map Home Assistant config as `homeassistant_config` → `/config`
  (replaces deprecated `config:rw` / unused `addon_config`)
- **Dockerfile:** official multi-arch `ghcr.io/home-assistant/base:3.21` default
  (Supervisor 2026.04+ no longer injects `BUILD_FROM`); `io.hass.type=app`
- **Ingress:** nginx allows Supervisor `172.30.32.2` and localhost health only
- README / INSTALL document the App repository install path

## 2.2.10

- **EVTV match charge:** button + automation set Tessie amps = floor(EVTV `tcch_amps`), including **0 A** (stops charge when EVTV rate is 0)
- Helper `input_boolean.match_evtv_charge_amps`; script `start_evtv_matched_charge`

## 2.2.9

- **Wrench · Quirks:** 🔧 drawer on plant UI — toggle auto Tessie amps, amps cap, pack/cell stop thresholds, car charger flag; show automation on/off; one-tap enable plant automations + run auto amps now

## 2.2.8

- **Plant UI:** **all parameters as buttons** — full control panel for grid, reverse feed, power setpoint mode, discharge / feed SoC limits, setpoint timeout, Tessie charge, plus live readout buttons (pack, SI, solar, car)
- **Service:** `tesla_evtv_bms.set_si_parameter` writes SI Modbus params (unit 3); grid control still prefers RPC `GdManStr`
- Integration **1.9.8**

## 2.2.7

- **One app:** combine dual sidebar entries into a **single Sunny Island** Ingress panel
  - Lovelace `sunny-island` is **History only** (`show_in_sidebar: false`, retitled)
  - Installer hides the Lovelace path in user sidebars and drops the legacy root `dashboards/sunny_island.yaml` duplicate
  - Plant UI footer links to `/sunny-island/overview` for graphs when needed

## 2.2.6

- **Fix Start charging (Tessie):** when car SoC is already at `number.x_charge_limit`, Tesla stays `complete` and ignores start — script now raises limit by +5% (max 100%) before `switch.x_charge` on
- **Fix:** `script.start_car_charger` mode `restart` (plant UI double-tap no longer “Already running”)
- **Fix:** cable-not-connected guard, longer wake/retry, clear failure notification if charge does not start
- **Plant UI:** better start-charge toasts (at-limit, live charge status)

## 2.2.5

- **Fix Start grid:** HA was still running pre-RPC grid control (Modbus 40527 only → fail on SI6048). Integration **1.9.6** reloads SetParameter `GdManStr` path
- **Fix:** WebBox RPC retries + `Connection: close` (connection-reset under concurrent polls)
- **Fix:** service / select raise `HomeAssistantError` instead of 500 `RuntimeError`
- **Fix:** password MD5 test uses real `sma` hash; GetParameter docs note string channel names

## 2.2.4

- **Fix:** grid control writes use WebBox **SetParameter** (`GdManStr`) first — Modbus 40527 is fallback only (illegal address on many SI6048 + WebBox plants)
- **Fix:** store WebBox password + device key on runtime so parameter writes authenticate
- **Fix:** select entity available with RPC-only (no longer requires Modbus enabled)
- **Fix:** Modbus poll no longer overwrites RPC-sourced grid control parameters

## 2.2.3

- **SI parameters:** battery current, discharge limit, reverse feed, feed-in SoC upper/lower, power setpoint mode/timeout
- **Plant UI:** **SUNNY ISLAND · PARAMETERS** tile section
- Reactive power scale FIX2 (var)

## 2.2.2

- **Plant UI:** Grid start section — timer, operating status, generator, relay + **Start grid / Automatic / Off** (writes SMA 40527 via `tesla_evtv_bms.set_grid_control`)

## 2.2.0

- **Feature:** WebBox Modbus TCP **proxy** built into Tesla EVTV BMS integration (plant + SI parameters → `sensor.<pack>_webbox_*`)
- Config: enable Modbus, port 502, unit IDs gateway/plant/device; HTTP + Modbus share one poller
- Dashboards + plant UI use integration WebBox entities only
- **Feature:** full Modbus param set on plant UI tiles + metrics (grid V/Hz, SI batt, status, reactive/apparent, serials, profile)
- Sensors: `webbox_apparent_power`, `webbox_power_kw`; Lovelace Modbus views wired to `sensor.<pack>_webbox_*`
- **Remove:** legacy `packages/webbox_modbus.yaml` (duplicate HA Modbus poller) and dual HTTP/Modbus dashboard cards
- **Refactor:** one Lovelace dashboard **Sunny Island** (replaces Pack detail + WebBox plant)

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
