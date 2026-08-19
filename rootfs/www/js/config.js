/**
 * Sunny Island plant app — entity map
 * Tesla EVTV BMS pack + Enphase Envoy (+ pack webbox_* when configured on the BMS integration).
 * Pure vanilla JS — no external UI frameworks.
 *
 * PACK_PREFIX must match the Tesla EVTV BMS integration entity_prefix
 * (and the add-on pack_prefix option). render_config.py rewrites these consts.
 *
 * Sign policy must match custom_components/tesla_evtv_bms/signs.py:
 * DISCHARGE_IS_NEGATIVE = true → negative amps = discharge.
 */
const PACK_PREFIX = 'battery_storage_tesla_pack';
const ENVOY_PREFIX = 'sensor.envoy_122039004946';
const DISCHARGE_IS_NEGATIVE = true;
const IDLE_BAND_A = 1.0;

const BAD_STATES = new Set(['unknown', 'unavailable', 'none', '']);

const APP_CONFIG = {
  title: 'Sunny Island',
  subtitle: 'Tesla 2-line 12S · EVTV BMS · Enphase · − discharge · + charge',
};

function pack(key) {
  return `sensor.${PACK_PREFIX}_${key}`;
}

const METRICS = {
  soc: { entity: pack('state_of_charge'), label: 'State of Charge', format: 'percent', group: 'pack' },
  status: { entity: pack('battery_status'), label: 'Pack Status', format: 'text', group: 'pack' },
  power: { entity: pack('power'), label: 'Pack Power', format: 'power', group: 'pack', chart: true },
  volts: { entity: pack('volts'), label: 'Bus Voltage', format: 'volts', group: 'pack' },
  current: { entity: pack('current'), label: 'Pack Current', format: 'amps', group: 'pack' },
  charge: { entity: pack('charge'), label: 'Charge Power', format: 'power', group: 'pack' },
  discharge: { entity: pack('discharge'), label: 'Discharge Power', format: 'power', group: 'pack' },
  available: { entity: pack('available_energy'), label: 'Available Energy', format: 'energy', group: 'pack' },
  summary: { entity: pack('summary'), label: 'Summary', format: 'text', group: 'pack' },
  fault: { entity: pack('fault_status'), label: 'Fault Status', format: 'text', group: 'pack' },
  faultCode: { entity: pack('fault_code'), label: 'Fault Code', format: 'int', group: 'pack' },
  lowestCell: { entity: pack('lowest_cell'), label: 'Lowest Cell', format: 'cell', group: 'cells' },
  highestCell: { entity: pack('highest_cell'), label: 'Highest Cell', format: 'cell', group: 'cells' },
  averageCell: { entity: pack('average_cell'), label: 'Average Cell', format: 'cell', group: 'cells' },
  cellDiff: { entity: pack('cell_difference'), label: 'Cell Δ', format: 'cell', group: 'cells' },
  triggerCell: { entity: pack('trigger_cell_voltage'), label: 'Trigger Cell', format: 'cell', group: 'cells' },
  lowTemp: { entity: pack('lowest_temp'), label: 'Low Temp', format: 'number', group: 'cells' },
  highTemp: { entity: pack('highest_temp'), label: 'High Temp', format: 'number', group: 'cells' },
  contactorPos: { entity: pack('contactor_positive'), label: 'Contactor +', format: 'text', group: 'safety' },
  contactorNeg: { entity: pack('contactor_negative'), label: 'Contactor −', format: 'text', group: 'safety' },
  chargeEnable: { entity: pack('charge_enable'), label: 'Charge Enable', format: 'text', group: 'safety' },
  carCharger: { entity: 'input_boolean.car_charger', label: 'Car Charger Flag', format: 'text', group: 'safety' },
  carCharge: { entity: 'switch.x_charge', label: 'Tessie Charge Switch', format: 'text', group: 'safety' },
  carStatus: { entity: 'sensor.x_charging', label: 'Tessie Charge Status', format: 'text', group: 'safety' },
  carBattery: { entity: 'sensor.x_battery_level', label: 'Car Battery %', format: 'percent', group: 'safety' },
  evtvTcch: {
    entity: pack('tcch_amps'),
    label: 'EVTV charge rate (TCCH)',
    format: 'amps',
    group: 'safety',
  },
  tessieAmps: {
    entity: 'number.x_charge_current',
    label: 'Tessie charge amps',
    format: 'amps',
    group: 'safety',
  },
  matchEvtv: {
    entity: 'input_boolean.match_evtv_charge_amps',
    label: 'Match EVTV→Tessie',
    format: 'text',
    group: 'safety',
  },
  carSessionKwh: { entity: 'sensor.x_charge_energy_added', label: 'Session kWh Added', format: 'energy', group: 'tessie' },
  carEnergyRem: { entity: 'sensor.x_energy_remaining', label: 'Car Energy Remaining', format: 'energy', group: 'tessie' },
  carLifetimeKwh: { entity: 'sensor.x_lifetime_energy_used', label: 'Lifetime kWh Used', format: 'energy', group: 'tessie' },
  carChargerKw: { entity: 'sensor.x_charger_power', label: 'Charger Power', format: 'power_kw', group: 'tessie' },
  chargeDay: { entity: pack('charge_energy_day'), label: 'Charge Today', format: 'energy', group: 'energy' },
  dischargeDay: { entity: pack('discharge_energy_day'), label: 'Discharge Today', format: 'energy', group: 'energy' },
  chargeTotal: { entity: pack('charge_energy'), label: 'Charge Total', format: 'energy', group: 'energy' },
  dischargeTotal: { entity: pack('discharge_energy'), label: 'Discharge Total', format: 'energy', group: 'energy' },
  chargeWeek: { entity: pack('charge_energy_week'), label: 'Charge Week', format: 'energy', group: 'energy' },
  dischargeWeek: { entity: pack('discharge_energy_week'), label: 'Discharge Week', format: 'energy', group: 'energy' },
  solarKw: { entity: `${ENVOY_PREFIX}_current_power_production`, label: 'Solar Production', format: 'power_kw', group: 'solar' },
  loadKw: { entity: `${ENVOY_PREFIX}_current_power_consumption`, label: 'Home Load', format: 'power_kw', group: 'solar' },
  netKw: { entity: `${ENVOY_PREFIX}_current_net_power_consumption`, label: 'Net Grid', format: 'power_kw', group: 'solar' },
  solarToday: { entity: `${ENVOY_PREFIX}_energy_production_today`, label: 'Solar Today', format: 'energy', group: 'solar' },
  // SMA Sunny WebBox — HTTP overview + Modbus TCP proxy (unit 1 gateway · 2 plant · 3 SI)
  webboxPower: { entity: pack('webbox_power'), label: 'Plant Power', format: 'power', group: 'webbox' },
  webboxPowerKw: { entity: pack('webbox_power_kw'), label: 'Plant Power kW', format: 'power_kw', group: 'webbox' },
  webboxDay: { entity: pack('webbox_daily_yield'), label: 'Daily Yield', format: 'energy', group: 'webbox' },
  webboxTotal: { entity: pack('webbox_total_yield'), label: 'Total Yield', format: 'energy', group: 'webbox' },
  webboxDevicePower: { entity: pack('webbox_device_power'), label: 'Device Power AC', format: 'power', group: 'webbox' },
  webboxGridV: { entity: pack('webbox_grid_voltage'), label: 'Grid Voltage', format: 'volts', group: 'webbox' },
  webboxGridHz: { entity: pack('webbox_grid_frequency'), label: 'Grid Frequency', format: 'hz', group: 'webbox' },
  webboxReactive: { entity: pack('webbox_reactive_power'), label: 'Reactive Power', format: 'var', group: 'webbox' },
  webboxStatus: { entity: pack('webbox_status'), label: 'Device Status', format: 'text', group: 'webbox' },
  webboxStatusCode: { entity: pack('webbox_status_code'), label: 'Status Code', format: 'int', group: 'webbox' },
  webboxRelay: { entity: pack('webbox_grid_relay'), label: 'Grid Relay', format: 'text', group: 'webbox' },
  webboxRelayCode: { entity: pack('webbox_grid_relay_code'), label: 'Grid Relay Code', format: 'int', group: 'webbox' },
  // Grid start / connection (Modbus 30199 · 33003 · 30917 · 40527)
  webboxGridConnTime: {
    entity: pack('webbox_grid_connection_time'),
    label: 'Grid start timer',
    format: 'duration_s',
    group: 'grid',
  },
  webboxOpStatus: {
    entity: pack('webbox_operating_status'),
    label: 'Operating status',
    format: 'text',
    group: 'grid',
  },
  webboxOpStatusCode: {
    entity: pack('webbox_operating_status_code'),
    label: 'Operating status code',
    format: 'int',
    group: 'grid',
  },
  webboxGenStatus: {
    entity: pack('webbox_generator_status'),
    label: 'Generator status',
    format: 'text',
    group: 'grid',
  },
  webboxGridControl: {
    entity: pack('webbox_grid_control'),
    label: 'Grid control mode',
    format: 'text',
    group: 'grid',
  },
  webboxGridControlCode: {
    entity: pack('webbox_grid_control_code'),
    label: 'Grid control code',
    format: 'int',
    group: 'grid',
  },
  webboxBatTyp: {
    entity: pack('webbox_bat_typ'),
    label: 'Battery type (BatTyp)',
    format: 'text',
    group: 'si',
  },
  webboxBattV: { entity: pack('webbox_battery_voltage'), label: 'SI Battery V', format: 'volts', group: 'webbox' },
  webboxBattSoc: { entity: pack('webbox_battery_soc'), label: 'SI Battery SoC', format: 'percent', group: 'webbox' },
  webboxBattTemp: { entity: pack('webbox_battery_temp'), label: 'SI Battery Temp', format: 'temp', group: 'webbox' },
  webboxBattA: { entity: pack('webbox_battery_current'), label: 'SI Battery A', format: 'amps', group: 'webbox' },
  webboxOpTime: { entity: pack('webbox_operating_time'), label: 'Operating Time', format: 'duration_s', group: 'webbox' },
  webboxSerial: { entity: pack('webbox_serial'), label: 'WebBox Serial', format: 'text', group: 'webbox' },
  webboxDeviceSerial: { entity: pack('webbox_device_serial'), label: 'Device Serial', format: 'text', group: 'webbox' },
  webboxProfile: { entity: pack('webbox_modbus_profile'), label: 'Modbus Profile', format: 'int', group: 'webbox' },
  webboxSusyId: { entity: pack('webbox_device_susy_id'), label: 'Device SuSy ID', format: 'int', group: 'webbox' },
  // Sunny Island parameters (limits / feed-in / setpoint mode)
  webboxDischargeLimit: {
    entity: pack('webbox_discharge_limit'),
    label: 'Discharge limit (self-cons)',
    format: 'percent',
    group: 'si',
  },
  webboxReverseFeed: {
    entity: pack('webbox_reverse_feed'),
    label: 'Reverse feed permitted',
    format: 'text',
    group: 'si',
  },
  webboxFeedSocUpper: {
    entity: pack('webbox_feed_soc_upper'),
    label: 'Feed-in SoC upper',
    format: 'percent',
    group: 'si',
  },
  webboxFeedSocLower: {
    entity: pack('webbox_feed_soc_lower'),
    label: 'Feed-in SoC lower',
    format: 'percent',
    group: 'si',
  },
  webboxPowerSpMode: {
    entity: pack('webbox_power_setpoint_mode'),
    label: 'Power setpoint mode',
    format: 'text',
    group: 'si',
  },
  webboxPowerSpTimeout: {
    entity: pack('webbox_power_setpoint_timeout'),
    label: 'Power setpoint timeout',
    format: 'duration_s',
    group: 'si',
  },
  webboxApparent: { entity: pack('webbox_apparent_power'), label: 'Apparent Power', format: 'power', group: 'webbox' },
};

/** Select entity that writes SMA 40527 (Off / Manual On / Automatic). */
function gridControlSelectId() {
  return `select.${PACK_PREFIX}_webbox_grid_control`;
}

/**
 * Full plant control map — every parameter is a button row.
 * kind: 'enum' | 'number' | 'action' | 'readonly'
 * write.parameter → tesla_evtv_bms.set_si_parameter
 */
const PARAM_CONTROLS = [
  {
    id: 'grid_control',
    title: 'Grid control',
    group: 'Grid start',
    metric: 'webboxGridControl',
    kind: 'enum',
    write: { parameter: 'grid_control' },
    options: [
      { value: 'manual_on', label: 'Start grid', cls: 'btn-ok' },
      { value: 'automatic', label: 'Automatic', cls: 'btn-secondary' },
      { value: 'off', label: 'Control off', cls: 'btn-danger' },
    ],
  },
  {
    id: 'bat_typ',
    title: 'Battery type (BatTyp 221.01)',
    group: 'SI parameters',
    metric: 'webboxBatTyp',
    kind: 'enum',
    write: { parameter: 'bat_typ' },
    options: [
      { value: 'LiIon_Ext-BMS', label: 'LiIon_Ext-BMS (Tesla EVTV)', cls: 'btn-ok' },
      { value: 'VRLA', label: 'VRLA', cls: 'btn-secondary' },
      { value: 'FLA', label: 'FLA', cls: 'btn-secondary' },
      { value: 'NiCd', label: 'NiCd', cls: 'btn-secondary' },
      { value: 'Other', label: 'Other', cls: 'btn-secondary' },
    ],
  },
  {
    id: 'reverse_feed',
    title: 'Reverse feed permitted',
    group: 'SI parameters',
    metric: 'webboxReverseFeed',
    kind: 'enum',
    write: { parameter: 'reverse_feed' },
    options: [
      { value: 'yes', label: 'Yes', cls: 'btn-ok' },
      { value: 'no', label: 'No', cls: 'btn-danger' },
    ],
  },
  {
    id: 'power_setpoint_mode',
    title: 'Power setpoint mode',
    group: 'SI parameters',
    metric: 'webboxPowerSpMode',
    kind: 'enum',
    write: { parameter: 'power_setpoint_mode' },
    options: [
      { value: 'off', label: 'Off', cls: 'btn-danger' },
      { value: 'manual_w', label: 'Manual W', cls: 'btn-secondary' },
      { value: 'manual_pct', label: 'Manual %', cls: 'btn-secondary' },
      { value: 'external', label: 'External', cls: 'btn-ok' },
    ],
  },
  {
    id: 'discharge_limit',
    title: 'Discharge limit (self-cons %)',
    group: 'SI parameters',
    metric: 'webboxDischargeLimit',
    kind: 'number',
    write: { parameter: 'discharge_limit' },
    min: 0,
    max: 100,
    step: 5,
    presets: [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
  },
  {
    id: 'feed_soc_upper',
    title: 'Feed-in SoC upper %',
    group: 'SI parameters',
    metric: 'webboxFeedSocUpper',
    kind: 'number',
    write: { parameter: 'feed_soc_upper' },
    min: 0,
    max: 100,
    step: 5,
    presets: [50, 60, 70, 80, 90, 100],
  },
  {
    id: 'feed_soc_lower',
    title: 'Feed-in SoC lower %',
    group: 'SI parameters',
    metric: 'webboxFeedSocLower',
    kind: 'number',
    write: { parameter: 'feed_soc_lower' },
    min: 0,
    max: 100,
    step: 5,
    presets: [10, 20, 30, 40, 50, 60],
  },
  {
    id: 'power_setpoint_timeout',
    title: 'Power setpoint timeout (s)',
    group: 'SI parameters',
    metric: 'webboxPowerSpTimeout',
    kind: 'number',
    write: { parameter: 'power_setpoint_timeout' },
    min: 0,
    max: 86400,
    step: 60,
    presets: [0, 60, 300, 600, 1800, 3600],
  },
  {
    id: 'tessie_charge',
    title: 'Tessie charge',
    group: 'Car',
    metric: 'carStatus',
    kind: 'action',
    options: [
      { value: 'match', label: 'Match EVTV amps + charge', cls: 'btn-ok', action: 'match_evtv_charge' },
      { value: 'start', label: 'Start charging', cls: 'btn-secondary', action: 'start_charge' },
      { value: 'stop', label: 'Stop charging', cls: 'btn-danger', action: 'stop_charge' },
    ],
  },
  // Read-only live parameters as buttons (display value, not writable)
  {
    id: 'ro_grid_timer',
    title: 'Grid start timer',
    group: 'Live status',
    metric: 'webboxGridConnTime',
    kind: 'readonly',
  },
  {
    id: 'ro_op_status',
    title: 'Operating status',
    group: 'Live status',
    metric: 'webboxOpStatus',
    kind: 'readonly',
  },
  {
    id: 'ro_gen_status',
    title: 'Generator status',
    group: 'Live status',
    metric: 'webboxGenStatus',
    kind: 'readonly',
  },
  {
    id: 'ro_relay',
    title: 'Grid relay',
    group: 'Live status',
    metric: 'webboxRelay',
    kind: 'readonly',
  },
  {
    id: 'ro_grid_v',
    title: 'Grid voltage',
    group: 'Live status',
    metric: 'webboxGridV',
    kind: 'readonly',
  },
  {
    id: 'ro_grid_hz',
    title: 'Grid frequency',
    group: 'Live status',
    metric: 'webboxGridHz',
    kind: 'readonly',
  },
  {
    id: 'ro_plant_w',
    title: 'Plant power',
    group: 'Live status',
    metric: 'webboxPower',
    kind: 'readonly',
  },
  {
    id: 'ro_si_v',
    title: 'SI battery V',
    group: 'Live status',
    metric: 'webboxBattV',
    kind: 'readonly',
  },
  {
    id: 'ro_si_soc',
    title: 'SI battery SoC',
    group: 'Live status',
    metric: 'webboxBattSoc',
    kind: 'readonly',
  },
  {
    id: 'ro_si_a',
    title: 'SI battery A',
    group: 'Live status',
    metric: 'webboxBattA',
    kind: 'readonly',
  },
  {
    id: 'ro_si_temp',
    title: 'SI battery temp',
    group: 'Live status',
    metric: 'webboxBattTemp',
    kind: 'readonly',
  },
  {
    id: 'ro_status',
    title: 'Device status',
    group: 'Live status',
    metric: 'webboxStatus',
    kind: 'readonly',
  },
  {
    id: 'ro_pack_soc',
    title: 'Pack SoC',
    group: 'Pack',
    metric: 'soc',
    kind: 'readonly',
  },
  {
    id: 'ro_pack_v',
    title: 'Pack voltage',
    group: 'Pack',
    metric: 'volts',
    kind: 'readonly',
  },
  {
    id: 'ro_pack_a',
    title: 'Pack current',
    group: 'Pack',
    metric: 'current',
    kind: 'readonly',
  },
  {
    id: 'ro_pack_w',
    title: 'Pack power',
    group: 'Pack',
    metric: 'power',
    kind: 'readonly',
  },
  {
    id: 'ro_low_cell',
    title: 'Lowest cell',
    group: 'Pack',
    metric: 'lowestCell',
    kind: 'readonly',
  },
  {
    id: 'ro_high_cell',
    title: 'Highest cell',
    group: 'Pack',
    metric: 'highestCell',
    kind: 'readonly',
  },
  {
    id: 'ro_solar',
    title: 'Solar kW',
    group: 'Site',
    metric: 'solarKw',
    kind: 'readonly',
  },
  {
    id: 'ro_load',
    title: 'Home load kW',
    group: 'Site',
    metric: 'loadKw',
    kind: 'readonly',
  },
  {
    id: 'ro_car_batt',
    title: 'Car battery %',
    group: 'Car',
    metric: 'carBattery',
    kind: 'readonly',
  },
  {
    id: 'ro_car_kw',
    title: 'Charger kW',
    group: 'Car',
    metric: 'carChargerKw',
    kind: 'readonly',
  },
];

const GROUPS = [
  { id: 'pack', title: 'Pack' },
  { id: 'cells', title: 'Cells & thermal' },
  { id: 'tessie', title: 'Tessie car kWh' },
  { id: 'safety', title: 'Safety & car charger' },
  { id: 'energy', title: 'Pack kWh meters' },
  { id: 'solar', title: 'Enphase site' },
  { id: 'webbox', title: 'SMA WebBox Modbus (plant + SI)' },
  { id: 'grid', title: 'Grid start (WebBox)' },
  { id: 'si', title: 'Sunny Island parameters' },
];

/**
 * Wrench · Quirks — plant workarounds & thresholds (HA helpers).
 * kind: toggle | number
 */
const QUIRKS = [
  {
    id: 'match_evtv_charge_amps',
    entity: 'input_boolean.match_evtv_charge_amps',
    kind: 'toggle',
    label: 'Match EVTV charge amps → Tessie',
    hint: 'Always set Tessie A = floor(EVTV TCCH), including 0 A',
  },
  {
    id: 'auto_tessie_amps',
    entity: 'input_boolean.auto_tessie_amps',
    kind: 'toggle',
    label: 'Auto Tessie amps (from BMS)',
    hint: 'While charging, keep Tessie A matched to EVTV rate',
  },
  {
    id: 'tessie_amps_cap',
    entity: 'input_number.tessie_amps_cap',
    kind: 'number',
    label: 'Tessie amps cap',
    unit: 'A',
    min: 0,
    max: 48,
    step: 1,
    hint: 'Hard ceiling for matched amps',
  },
  {
    id: 'stop_on_pack_v',
    entity: 'input_boolean.tessie_stop_on_pack_volts',
    kind: 'toggle',
    label: 'Stop charge on low pack V',
    hint: 'Pack protection uses this toggle',
  },
  {
    id: 'stop_pack_v',
    entity: 'input_number.tessie_stop_pack_volts',
    kind: 'number',
    label: 'Stop below pack V',
    unit: 'V',
    min: 30,
    max: 50,
    step: 0.1,
    hint: '12S default 38.4 V ≈ 3.2 V/cell',
  },
  {
    id: 'stop_on_cell_v',
    entity: 'input_boolean.tessie_stop_on_cell_volts',
    kind: 'toggle',
    label: 'Stop charge on low cell V',
    hint: 'Lowest / trigger cell hard stop',
  },
  {
    id: 'stop_cell_v',
    entity: 'input_number.tessie_stop_cell_volts',
    kind: 'number',
    label: 'Stop below cell V',
    unit: 'V',
    min: 2.8,
    max: 3.6,
    step: 0.01,
    hint: 'Default 3.2 V',
  },
  {
    id: 'stop_soc',
    entity: 'input_number.tessie_stop_soc',
    kind: 'number',
    label: 'Stop below pack SoC',
    unit: '%',
    min: 0,
    max: 50,
    step: 1,
    hint: 'Default 15%',
  },
  {
    id: 'car_charger_flag',
    entity: 'input_boolean.car_charger',
    kind: 'toggle',
    label: 'Car charger flag',
    hint: 'Synced with switch.x_charge (plant automations)',
  },
];

function getAllEntityIds() {
  const ids = Object.values(METRICS).map((m) => m.entity);
  ids.push(gridControlSelectId());
  if (typeof QUIRKS !== 'undefined') {
    QUIRKS.forEach((q) => ids.push(q.entity));
  }
  // Automations so wrench can show on/off
  ids.push(
    'automation.tessie_auto_amps_from_evtv_bms',
    'automation.evtv_bms_voltage_stop_tessie_charging',
    'automation.sync_car_charger_flag_with_x_charge'
  );
  return [...new Set(ids)];
}
