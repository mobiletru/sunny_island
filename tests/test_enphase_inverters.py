"""Enphase microinverter discovery (mirrors rootfs/www/js/config.js)."""

from __future__ import annotations

import re

INVERTER_POWER_ID = re.compile(r"^sensor\.inverter_\d+$")


def list_enphase_inverters(states):
    out = []
    if not isinstance(states, list):
        return out
    for st in states:
        eid = (st or {}).get("entity_id") or ""
        if not INVERTER_POWER_ID.match(eid):
            continue
        unit = ((st.get("attributes") or {}).get("unit_of_measurement")) or ""
        if unit and unit != "W":
            continue
        serial = eid[len("sensor.inverter_") :]
        out.append({"entity": eid, "serial": serial, "label": serial[-6:]})
    out.sort(key=lambda row: row["serial"])
    return out


def test_skips_aux_channels_and_sorts():
    states = [
        {"entity_id": "sensor.inverter_542539091585", "state": "293", "attributes": {"unit_of_measurement": "W"}},
        {"entity_id": "sensor.inverter_122003022220_ac_voltage", "state": "242", "attributes": {"unit_of_measurement": "V"}},
        {"entity_id": "sensor.inverter_122003022220", "state": "18", "attributes": {"unit_of_measurement": "W"}},
        {"entity_id": "sensor.envoy_122039004946_current_power_production", "state": "5.7"},
    ]
    found = list_enphase_inverters(states)
    assert [row["entity"] for row in found] == [
        "sensor.inverter_122003022220",
        "sensor.inverter_542539091585",
    ]
    assert found[0]["label"] == "022220"
    assert found[1]["label"] == "091585"


def test_empty_and_wrong_unit():
    assert list_enphase_inverters(None) == []
    assert list_enphase_inverters([]) == []
    assert (
        list_enphase_inverters(
            [
                {
                    "entity_id": "sensor.inverter_1",
                    "attributes": {"unit_of_measurement": "kW"},
                }
            ]
        )
        == []
    )
