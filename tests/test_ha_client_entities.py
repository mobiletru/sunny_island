"""Unit tests for compressed subscribe_entities expand/diff (ha-client.js logic).

Mirrors rootfs/www/js/ha-client.js pure helpers without a browser.
"""

from __future__ import annotations


def expand_compressed(entity_id: str, compressed: dict) -> dict:
    lc = compressed.get("lc")
    lu = compressed.get("lu")
    # Epoch → ISO is non-critical for state reads; tests assert state/attrs.
    last_changed = f"t{lc}" if lc is not None else "now"
    last_updated = f"t{lu}" if lu is not None else last_changed
    ctx = compressed.get("c")
    if isinstance(ctx, str):
        context = {"id": ctx, "parent_id": None, "user_id": None}
    else:
        context = ctx or {"id": None, "parent_id": None, "user_id": None}
    return {
        "entity_id": entity_id,
        "state": compressed["s"],
        "attributes": dict(compressed.get("a") or {}),
        "context": context,
        "last_changed": last_changed,
        "last_updated": last_updated,
    }


def apply_event(states: dict, event: dict) -> dict:
    if event.get("a"):
        for eid, compressed in event["a"].items():
            states[eid] = expand_compressed(eid, compressed)
    if event.get("r"):
        for eid in event["r"]:
            states.pop(eid, None)
    if event.get("c"):
        for eid, diff in event["c"].items():
            prev = states.get(eid)
            if not prev:
                continue
            entity = {
                **prev,
                "attributes": dict(prev.get("attributes") or {}),
            }
            to_add = diff.get("+")
            to_remove = diff.get("-")
            if to_add:
                if "s" in to_add:
                    entity["state"] = to_add["s"]
                if "a" in to_add:
                    entity["attributes"].update(to_add["a"])
            if to_remove and to_remove.get("a"):
                for key in to_remove["a"]:
                    entity["attributes"].pop(key, None)
            states[eid] = entity
    return states


def test_expand_exposes_state_not_s():
    entity = expand_compressed(
        "sensor.pack_soc",
        {"s": "37.0", "a": {"unit_of_measurement": "%"}, "c": "abc", "lc": 1.0, "lu": 1.0},
    )
    assert entity["state"] == "37.0"
    assert "s" not in entity
    assert entity["attributes"]["unit_of_measurement"] == "%"
    assert entity["entity_id"] == "sensor.pack_soc"


def test_diff_updates_state_and_attributes():
    states: dict = {}
    apply_event(
        states,
        {
            "a": {
                "sensor.pack_power": {
                    "s": "1000",
                    "a": {"unit_of_measurement": "W"},
                    "c": "x",
                    "lc": 1.0,
                    "lu": 1.0,
                }
            }
        },
    )
    apply_event(
        states,
        {
            "c": {
                "sensor.pack_power": {
                    "+": {"s": "2853", "a": {"friendly_name": "Pack"}},
                    "-": {"a": []},
                }
            }
        },
    )
    ent = states["sensor.pack_power"]
    assert ent["state"] == "2853"
    assert ent["attributes"]["unit_of_measurement"] == "W"
    assert ent["attributes"]["friendly_name"] == "Pack"


def test_remove_entity():
    states = {
        "sensor.gone": {
            "entity_id": "sensor.gone",
            "state": "1",
            "attributes": {},
            "context": {},
            "last_changed": "t",
            "last_updated": "t",
        }
    }
    apply_event(states, {"r": ["sensor.gone"]})
    assert "sensor.gone" not in states


def test_unknown_diff_is_ignored():
    states: dict = {}
    apply_event(states, {"c": {"sensor.missing": {"+": {"s": "1"}}}})
    assert states == {}
