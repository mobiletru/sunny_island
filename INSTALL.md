# Install Sunny Island (Home Assistant OS App)

Sunny Island is a Supervisor **app** (formerly add-on). On HAOS it installs from
**Settings → Apps**. This repository is a valid app repository
(`repository.yaml` at the git root; Supervisor discovers `config.yaml`).

Supported architectures: **aarch64** and **amd64**. The image is built on the
HAOS host from the official `ghcr.io/home-assistant/base` image.

## App repository (recommended)

[![Add this app repository](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fmobiletru%2Fsunny_island)

1. Copy the repository URL: `https://github.com/mobiletru/sunny_island`
2. Go to **Settings → Apps → Install app**
3. Top-right **⋮ → Repositories**
4. Paste the URL → **Add**
5. Open the **Sunny Island** card → **Install** → **Start**
6. Enable **Show in sidebar** if the Ingress panel is not visible
7. Open **Sunny Island** for the live plant UI
8. With `auto_setup_bms: true` (default) the app adds **Tesla EVTV BMS** (UDP `6550`)
9. Set **entity prefix** / `pack_prefix` if you changed the default `battery_storage_tesla_pack`
10. Core restarts once after the first integration file install so HA can load it

## Local app (development)

```bash
cd /addons
git clone https://github.com/mobiletru/sunny_island.git sunny_island
# or copy this folder to /addons/sunny_island
```

1. Settings → Apps → ⋮ → Check for updates
2. Install **Sunny Island** (Local) → **Start**
3. Same sidebar / BMS steps as above

## Lovelace YAML dashboards (optional)

The app copies YAML into `/config/dashboards/sunny_island/` and writes
`lovelace_include.yaml`. It adds `homeassistant.packages: !include_dir_named packages`
to `configuration.yaml` when that include is missing; it does not rewrite the rest.

Merge under `lovelace.dashboards` manually, or open the YAML files as needed.

## After upgrading from separate apps

1. Install/rebuild **Sunny Island** 2.1.1+
2. Stop and **uninstall** the old **Tesla EVTV BMS** app (integration files stay in `/config`)
3. Keep using the same EVTV BMS integration config in HA
4. Enable `force_overwrite: true` once if you need to refresh the component from the image

## Options

See README — `auto_sync` keeps the BMS component updated from the app image when
`force_overwrite` allows it.
