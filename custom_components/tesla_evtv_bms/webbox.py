"""Poll an SMA Sunny WebBox for plant overview data.

Two transports, both real and observed on hardware:

- ``GET /home.ajax`` — always available, no auth. Backs the WebBox's own
  home page. Returns ``{"Items":[{"Power":"-900 W"}, {"DailyYield":"8.2 kWh"},
  {"TotalYield":"5348.2 kWh"}]}``.
- ``POST /rpc`` — the documented JSON-RPC interface (SWebBoxRPC-BA-de-14),
  MD5-hashed password in the ``passwd`` field. Disabled by default on the
  WebBox (Security settings); when disabled it echoes the static frameset
  page instead of JSON, so calls are best-effort and failures are silent
  after one warning.
"""

import hashlib
import json
import logging

_LOGGER = logging.getLogger(__name__)

RPC_VERSION = "1.0"

# home.ajax "Items" key -> our sensor key
OVERVIEW_KEY_MAP = {
    "Power": "webbox_power",
    "DailyYield": "webbox_daily_yield",
    "TotalYield": "webbox_total_yield",
}


def webbox_password_hash(password: str) -> str:
    """MD5 hash of the WebBox access-level password, per the RPC spec."""
    return hashlib.md5(password.encode("utf-8")).hexdigest()


def parse_overview_ajax(payload: dict) -> dict:
    """Parse the ``home.ajax`` response into {sensor_key: float}.

    Each item value is a string like "-900 W" or "8.2 kWh" — split off the
    leading numeric token and drop the unit (unit is fixed per key so we
    don't need to carry it through).
    """
    result: dict[str, float] = {}
    for item in payload.get("Items", []):
        for name, raw_value in item.items():
            key = OVERVIEW_KEY_MAP.get(name)
            if key is None:
                continue
            token = str(raw_value).strip().split(" ", 1)[0]
            try:
                result[key] = float(token)
            except ValueError:
                _LOGGER.debug("[tesla_evtv_bms] Unparseable WebBox value for %s: %r", name, raw_value)
    return result


def parse_rpc_plant_overview(body: str) -> dict | None:
    """Best-effort parse of a GetPlantOverview RPC response.

    Returns None if the body isn't the expected JSON shape (e.g. RPC is
    disabled on the device and it echoed the default HTML frameset).
    """
    try:
        envelope = json.loads(body)
    except ValueError:
        return None

    result = envelope.get("result")
    if not isinstance(result, dict):
        return None

    out: dict[str, float] = {}
    for channel in result.get("overview", []):
        meta = channel.get("meta")
        value = channel.get("value")
        if meta is None or value is None:
            continue
        try:
            out[f"webbox_rpc_{meta.lower()}"] = float(value)
        except ValueError:
            continue
    return out


def build_rpc_request(proc: str, *, password: str | None = None, params: dict | None = None, request_id: str = "1") -> dict:
    request = {
        "version": RPC_VERSION,
        "proc": proc,
        "id": request_id,
        "format": "JSON",
    }
    if password:
        request["passwd"] = webbox_password_hash(password)
    if params:
        request["params"] = params
    return request


async def async_poll_webbox(session, host: str, password: str | None) -> dict:
    """Fetch current WebBox values. Always tries home.ajax; RPC is best-effort."""
    values: dict[str, float] = {}

    async with session.get(f"http://{host}/home.ajax", timeout=8) as resp:
        resp.raise_for_status()
        values.update(parse_overview_ajax(await resp.json(content_type=None)))

    try:
        async with session.post(
            f"http://{host}/rpc",
            json=build_rpc_request("GetPlantOverview", password=password),
            timeout=8,
        ) as resp:
            body = await resp.text()
        extra = parse_rpc_plant_overview(body)
        if extra:
            values.update(extra)
    except Exception as err:  # noqa: BLE001 - RPC is optional, never fatal
        _LOGGER.debug("[tesla_evtv_bms] WebBox RPC unavailable (falling back to home.ajax only): %s", err)

    return values
