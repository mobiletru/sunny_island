# Changelog

## 2.2.14

- **Feature:** plant UI ring gauges for each Enphase microinverter
  (`sensor.inverter_<serial>` watts), discovered from HA at connect
- **Refactor:** overlay app `webbox_host` / `webbox_password` through
  `tesla_evtv_bms.set_webbox` (idempotent; empty fields never wipe Configure).
  Dropped the options-flow puppet and `/data/bms_setup.json` `webbox_applied`
  sidecar. BMS existence is the config entry, not `sensor.*_volts`
- Integration **1.9.9**
