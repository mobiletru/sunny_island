# Changelog

## 2.2.14

- **Refactor:** overlay app `webbox_host` / `webbox_password` through
  `tesla_evtv_bms.set_webbox` (idempotent; empty fields never wipe Configure).
  Dropped the options-flow puppet and `/data/bms_setup.json` `webbox_applied`
  sidecar. BMS existence is the config entry, not `sensor.*_volts`
- Integration **1.9.9**

## 2.2.13

- **Fix:** WebBox sensors stayed unavailable after auto-setup created the BMS
  entry with an empty host. App options `webbox_host` / `webbox_password` are
  now written onto an existing Tesla EVTV BMS entry on start (options flow),
  not only when the entry is first created
