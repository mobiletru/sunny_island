"""Parse EVTV LiteCAN UDP packets.

CAN layouts follow the community reference:
https://github.com/wreuvers/tesla_evtv_bms

Extended frames (0x652, 0x654, 0x68F) from mobiletru PRs to the core repo.
Current/power are published as LiteCAN reports them. Physical charge vs
discharge interpretation is only in signs.py (status / kWh), not here.
"""

import logging
import struct

_LOGGER = logging.getLogger(__name__)

# Known frames + 0x655 (float I/V) and 0x68F (per-module 6-cell voltages)
VALID_CAN_IDS = {
    0x150,
    0x151,
    0x650,
    0x651,
    0x652,
    0x654,
    0x655,
    0x683,
    0x68F,
}


def decode_module_cell_byte(raw: int) -> float:
    """Decode one EVTV 0x68F cell byte to volts.

    Observed encoding on multi-module LiteCAN: V = raw/100 + 2.0
    (e.g. 0x7A → 3.22 V, 0x82 → 3.30 V). Matches pack 0x651 min/max.
    """
    return round(int(raw) / 100.0 + 2.0, 3)

FAULT_REASONS = {
    0: "No Fault",
    1: "Cell Undervoltage",
    2: "Cell Overvoltage",
    3: "Module Undertemperature",
    4: "Module Overtemperature",
    5: "Voltage Imbalance",
}


def parse_udp_packet(payload: bytes, port: int) -> dict | None:
    _LOGGER.debug(
        "[tesla_evtv_bms] Received UDP payload on port %s: %s (length=%s)",
        port,
        payload.hex(),
        len(payload),
    )

    if len(payload) < 12:
        _LOGGER.warning(
            "[tesla_evtv_bms] Ignored short packet on port %s (length=%s)",
            port,
            len(payload),
        )
        return None

    can_id = payload[8] + (payload[9] << 8) + (payload[10] << 16) + (payload[11] << 24)
    _LOGGER.debug("[tesla_evtv_bms] Parsed CAN ID: %s", hex(can_id))

    if can_id not in VALID_CAN_IDS:
        # Drop unknown frames — do not create live can_*_raw / can_*_u16 sensors.
        return None

    def u16(b0, b1):
        return b0 + (b1 << 8)

    def s16(b0, b1):
        value = b0 + (b1 << 8)
        return value - 0x10000 if value & 0x8000 else value

    def s32(b):
        return int.from_bytes(b, byteorder="little", signed=True)

    result: dict = {"_can_id": can_id}

    if can_id == 0x650:
        result["state_of_charge"] = payload[0] / 2

    elif can_id == 0x651:
        # Pack-wide min/max/avg in millivolts (summary frame — can lag 0x68F)
        result["lowest_cell"] = round(u16(payload[0], payload[1]) / 1000.0, 3)
        result["highest_cell"] = round(u16(payload[2], payload[3]) / 1000.0, 3)
        result["average_cell"] = round(u16(payload[4], payload[5]) / 1000.0, 3)
        # Byte 6 is often 0xFF on multi-module banks (not a real cell count)
        max_cells = payload[6]
        active_cells = payload[7]
        if max_cells not in (0, 0xFF):
            result["max_cells"] = max_cells
        if active_cells not in (0, 0xFF):
            result["active_cells"] = active_cells

    elif can_id == 0x655:
        # High-res float current (A) + pack voltage (V) — more stable than 0x150/0x151
        try:
            current_f, volts_f = struct.unpack("<ff", bytes(payload[0:8]))
            if abs(current_f) < 5000:
                result["current"] = round(float(current_f), 2)
            if 10.0 < volts_f < 1000.0:
                result["can_655_volts"] = round(float(volts_f), 2)
        except struct.error:
            pass

    elif can_id == 0x151:
        # High-res current (centiamps). Pack V/P are NOT taken from this frame
        # on multi-module 12S banks (full-string ~750 V artifact).
        current = s32(payload[0:4]) / 100.0
        frame_power = s32(payload[4:8]) / 100.0
        frame_volts = frame_power / current if current else 0.0
        result.update(
            {
                "current": round(current, 2),
                "can_151_power": round(frame_power),
                "can_151_volts": round(frame_volts, 1),
            }
        )

    elif can_id == 0x683:
        result["freq_shift_volts"] = u16(payload[2], payload[3]) / 100
        result["tcch_amps"] = u16(payload[4], payload[5]) / 10

    elif can_id == 0x150:
        # Integer-amp current, temps, Ah. V field is pack voltage on some small
        # packs but short-string (~40–50 V) on multi-module 12S banks — never
        # write it to pack `volts`. Integer current is stored as current_150 so
        # it does not clobber high-res 0x151 current (which was causing power
        # flicker between e.g. -11 A and -12.88 A every packet).
        raw_current = u16(payload[0], payload[1])
        frame_volts = u16(payload[2], payload[3]) / 10.0

        # LiteCAN raw encoding: high bit set → opposite polarity of low values.
        # Physical meaning of the resulting sign is defined in signs.py.
        if raw_current > 32768:
            charging_current = 65535 - raw_current
            current = -float(charging_current)
        else:
            current = float(raw_current)

        result.update(
            {
                "current_150": round(current, 2),
                "can_150_volts": round(frame_volts, 1),
                "raw_current": raw_current,
                "pack_ah_used": round(s16(payload[4], payload[5]) / 10.0, 1),
                "highest_temp": payload[6],
                "lowest_temp": payload[7],
            }
        )

    elif can_id == 0x652:
        result["high_voltage_cutoff"] = round(u16(payload[4], payload[5]) / 10.0, 2)
        result["low_voltage_cutoff"] = round(u16(payload[6], payload[7]) / 10.0, 2)

    elif can_id == 0x654:
        status = payload[0]
        result["contactor_negative"] = "Open" if (status & 0x10) else "Closed"
        result["contactor_positive"] = "Open" if (status & 0x20) else "Closed"
        result["charge_enable"] = "On" if (status & 0x04) else "Off"
        result["heat_enable"] = "On" if (status & 0x08) else "Off"
        result["power_source"] = "USB" if (status & 0x40) else "12V"

        fault_code = payload[1] & 0x3F
        result["fault_code"] = fault_code
        result["fault_status"] = FAULT_REASONS.get(fault_code, f"Unknown ({fault_code})")

    elif can_id == 0x68F:
        # Per-module cell voltage broadcast (multi-module packs):
        #   byte0 = module index (0..N-1)
        #   byte1 = total modules on bus
        #   byte2..7 = six cell voltages (V = raw/100 + 2)
        module_idx = int(payload[0])
        total_modules = int(payload[1])
        if total_modules > 0:
            result["total_modules"] = total_modules
            result["total_cells"] = total_modules * 6
            result["active_cells"] = total_modules * 6
        cells = [decode_module_cell_byte(payload[i]) for i in range(2, 8)]
        # Private keys consumed by the sensor platform to rebuild live min/max/avg
        result["_module_idx"] = module_idx
        result["_module_cells"] = cells
        result[f"module_{module_idx:02d}_avg"] = round(sum(cells) / 6.0, 3)
        result[f"module_{module_idx:02d}_min"] = round(min(cells), 3)
        result[f"module_{module_idx:02d}_max"] = round(max(cells), 3)

    return result
