/**
 * Sunny Island plant app — entity map
 * Tesla EVTV BMS pack + Enphase Envoy only (no WebBox).
 * Pure vanilla JS — no external UI frameworks.
 */
const PACK_PREFIX = 'battery_storage_tesla_pack';
const ENVOY_PREFIX = 'sensor.envoy_122039004946';

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
};

const GROUPS = [
  { id: 'pack', title: 'Pack' },
  { id: 'cells', title: 'Cells & thermal' },
  { id: 'tessie', title: 'Tessie car kWh' },
  { id: 'safety', title: 'Safety & car charger' },
  { id: 'energy', title: 'Pack kWh meters' },
  { id: 'solar', title: 'Enphase site' },
];

function getAllEntityIds() {
  return [...new Set(Object.values(METRICS).map((m) => m.entity))];
}
