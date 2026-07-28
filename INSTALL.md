# Install Sunny Island (all-in-one)

## Local add-on

```bash
cd /addons
git clone https://github.com/mobiletru/sunny_island.git sunny_island
# or copy this folder to /addons/sunny_island
```

1. Settings → Apps → ⋮ → Check for updates  
2. Install **Sunny Island** → **Start**  
3. Enable **Show in sidebar** if needed  
4. Open **Sunny Island** for the live plant UI  
5. If pack sensors are missing: **Devices & services → Add integration → Tesla EVTV BMS**  
6. Set **entity prefix** to match add-on `pack_prefix` (default `battery_storage_tesla_pack`)  
7. Restart Home Assistant Core after the first integration install/update  

## Lovelace YAML dashboards (optional)

The add-on copies YAML into `/config/dashboards/sunny_island/` and writes
`lovelace_include.yaml`. It does **not** edit `configuration.yaml`.

Merge under `lovelace.dashboards` manually, or open the YAML files as needed.

## After upgrading from separate apps

1. Install/rebuild **Sunny Island** 2.1.1+  
2. Stop and **uninstall** the old **Tesla EVTV BMS** app (integration files stay in `/config`)  
3. Keep using the same EVTV BMS integration config in HA  
4. Enable `force_overwrite: true` once if you need to refresh the component from the image  

## Options

See README — `auto_sync` keeps the BMS component updated from the app image when
`force_overwrite` allows it.
