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
6. Restart Home Assistant Core after the first integration install/update  

## After upgrading from separate apps

1. Install/rebuild **Sunny Island** 2.0.0  
2. Stop and **uninstall** the old **Tesla EVTV BMS** app (integration files stay in `/config`)  
3. Keep using the same EVTV BMS integration config in HA  

## Options

See README — `auto_sync` keeps the BMS component updated from the app image.
