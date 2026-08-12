/**
 * Sunny Island plant app — mirrors /sunny-island-detail/overview
 * Gauges left · KPIs + Tessie right · vanilla JS only
 */
(function () {
  let client = null;
  let history = [];
  const MAX_HISTORY = 180;
  const $ = (s) => document.querySelector(s);
  // SVG circles use pathLength="100" → dash units are 0–100
  const RING_LEN = 100;

  function init() {
    document.title = APP_CONFIG.title;
    $('#app-title').textContent = APP_CONFIG.title;
    $('#app-subtitle').textContent = APP_CONFIG.subtitle;
    $('#year').textContent = new Date().getFullYear();
    initRingArcs();
    renderMetricPlaceholders();
    bindAuth();
    bindSettings();
    bindChargerButtons();
    bindGridStartButtons();
    tryConnect();
  }

  function initRingArcs() {
    ['g-soc-arc', 'g-volts-arc', 'g-amps-arc', 'g-power-arc', 'g-solar-arc', 'g-load-arc'].forEach((id) => {
      const el = document.getElementById(id);
      if (!el) return;
      el.style.strokeDasharray = String(RING_LEN);
      el.style.strokeDashoffset = String(RING_LEN);
    });
  }

  function setRing(arcId, pct, modeClass) {
    const el = document.getElementById(arcId);
    if (!el) return;
    const p = Math.max(0, Math.min(100, pct));
    el.style.strokeDashoffset = String(RING_LEN - p);
    el.classList.remove('mode-charge', 'mode-discharge', 'mode-idle', 'mode-low', 'mode-mid', 'mode-high');
    if (modeClass) el.classList.add(modeClass);
  }

  function bindAuth() {
    $('#connect-btn').addEventListener('click', () => {
      const token = $('#token-input').value.trim();
      if (!token) return;
      storeToken(token);
      hideAuth();
      tryConnect();
    });
    $('#token-input').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') $('#connect-btn').click();
    });
    $('#disconnect-btn').addEventListener('click', () => {
      client?.disconnect();
      clearToken();
      showAuth();
      setConnectionStatus('disconnected');
    });
  }

  function bindSettings() {
    $('#settings-btn').addEventListener('click', () => {
      $('#settings-panel').classList.toggle('open');
    });
    document.addEventListener('click', (e) => {
      if (!e.target.closest('.settings-wrap')) {
        $('#settings-panel').classList.remove('open');
      }
    });
  }

  function bindChargerButtons() {
    let chargerBusy = false;
    const start = async () => {
      if (!client) {
        toast('Connect to Home Assistant first', 'error');
        return;
      }
      if (chargerBusy) {
        toast('Start charging already running…', 'info');
        return;
      }
      chargerBusy = true;
      try {
        // Pre-check: at charge limit Tesla stays "complete" and will not draw
        const batt = parseFloat(client.getState('sensor.x_battery_level')?.state);
        const lim = parseFloat(client.getState('number.x_charge_limit')?.state);
        if (Number.isFinite(batt) && Number.isFinite(lim) && batt >= lim - 0.5) {
          toast(
            `Car at charge limit (${batt}% / ${lim}%) — raising limit then starting…`,
            'info'
          );
        } else {
          toast('Starting charge (Tessie)…', 'info');
        }
        await client.callService('script', 'start_car_charger');
        // Brief settle then report live status
        await new Promise((r) => setTimeout(r, 1500));
        const st = (client.getState('sensor.x_charging')?.state || '').toLowerCase();
        const sw = (client.getState('switch.x_charge')?.state || '').toLowerCase();
        const amps = client.getState('number.x_charge_current')?.state;
        if (sw === 'on' || st === 'charging' || st === 'starting') {
          toast(`Charging · ${st || sw}${amps != null ? ` · ${amps} A` : ''}`, 'success');
        } else if (st === 'complete') {
          toast(
            'Still complete — raise charge limit above car SoC and retry',
            'error'
          );
        } else {
          toast(
            `Start sent · charge=${st || 'unknown'} switch=${sw || 'unknown'}`,
            'info'
          );
        }
      } catch (err) {
        const msg = err.message || 'Start charging failed';
        if (/already running/i.test(msg)) {
          toast('Start charging already running…', 'info');
        } else {
          toast(msg, 'error');
        }
      } finally {
        chargerBusy = false;
      }
    };
    const stop = async () => {
      if (!client) {
        toast('Connect to Home Assistant first', 'error');
        return;
      }
      try {
        toast('Stopping charge (Tessie)…', 'info');
        await client.callService('script', 'shutdown_car_charger');
        toast('Stop charging (Tessie) requested', 'success');
      } catch (err) {
        toast(err.message || 'Stop charging failed', 'error');
      }
    };
    $('#start-charger-btn')?.addEventListener('click', start);
    $('#shutdown-charger-btn')?.addEventListener('click', stop);
    $('#start-charger-main')?.addEventListener('click', start);
    $('#stop-charger-main')?.addEventListener('click', stop);
  }

  /** WebBox SMA reg 40527 — manual grid request / automatic / off */
  function bindGridStartButtons() {
    const labels = {
      manual_on: 'Start grid (manual request)',
      automatic: 'Grid control → Automatic',
      off: 'Grid control → Off',
    };
    const setMode = async (mode) => {
      if (!client) {
        toast('Connect to Home Assistant first', 'error');
        return;
      }
      try {
        await client.callService('tesla_evtv_bms', 'set_grid_control', {
          mode,
          entity_prefix: typeof PACK_PREFIX === 'string' ? PACK_PREFIX : undefined,
        });
        toast(labels[mode] || `Grid control → ${mode}`, 'success');
      } catch (err) {
        // Fallback: select.select_option with friendly labels
        try {
          const optionMap = {
            manual_on: 'Manual On (request grid)',
            automatic: 'Automatic',
            off: 'Off',
          };
          const entityId =
            typeof gridControlSelectId === 'function'
              ? gridControlSelectId()
              : `select.${PACK_PREFIX}_webbox_grid_control`;
          await client.callService(
            'select',
            'select_option',
            { option: optionMap[mode] || mode },
            { entity_id: entityId }
          );
          toast(labels[mode] || `Grid control → ${mode}`, 'success');
        } catch (err2) {
          toast(err2.message || err.message || 'Grid control failed', 'error');
        }
      }
    };
    document.querySelectorAll('[data-grid-mode]').forEach((btn) => {
      btn.addEventListener('click', () => setMode(btn.dataset.gridMode));
    });
  }

  function updateGridStartButtons() {
    if (!client) return;
    const selectId =
      typeof gridControlSelectId === 'function'
        ? gridControlSelectId()
        : `select.${PACK_PREFIX}_webbox_grid_control`;
    const st = client.getState(selectId);
    const sensorMode = client.getState(METRICS.webboxGridControl?.entity)?.state || '';
    const raw = (st?.state || sensorMode || '').toLowerCase();
    let mode = '';
    if (raw.includes('manual') || raw === 'on' || raw.includes('request')) mode = 'manual_on';
    else if (raw.includes('auto')) mode = 'automatic';
    else if (raw === 'off' || raw.includes('off')) mode = 'off';
    document.querySelectorAll('[data-grid-mode]').forEach((btn) => {
      btn.classList.toggle('is-active', mode && btn.dataset.gridMode === mode);
    });
  }

  function tryConnect() {
    const token = getStoredToken();
    if (!token) {
      showAuth();
      return;
    }
    hideAuth();
    connectHA(token);
  }

  function connectHA(token) {
    client?.disconnect();
    client = new HAClient({
      url: detectHAUrl(),
      token,
      onConnect: async () => {
        setConnectionStatus('connected');
        try {
          await client.subscribeEntities(getAllEntityIds());
          updateAll();
        } catch (err) {
          setConnectionStatus('error', err.message);
        }
      },
      onDisconnect: () => setConnectionStatus('disconnected'),
      onStateChange: () => {
        updateAll();
        recordHistory();
      },
      onError: (msg) => {
        if (String(msg).toLowerCase().includes('token')) {
          clearToken();
          showAuth();
        }
        setConnectionStatus('error', msg);
      },
    });
    setConnectionStatus('connecting');
    client.connect();
  }

  function showAuth() {
    $('#auth-overlay').classList.remove('hidden');
  }
  function hideAuth() {
    $('#auth-overlay').classList.add('hidden');
  }

  function setConnectionStatus(status, detail = '') {
    const el = $('#connection-status');
    el.dataset.status = status;
    const labels = {
      connected: 'Live',
      connecting: 'Connecting…',
      disconnected: 'Offline',
      error: detail || 'Error',
    };
    el.textContent = labels[status] || status;
  }

  function toast(message, type = 'info') {
    const el = $('#toast');
    el.textContent = message;
    el.dataset.type = type;
    el.classList.add('show');
    clearTimeout(toast._t);
    toast._t = setTimeout(() => el.classList.remove('show'), 3500);
  }

  function formatValue(meta, state) {
    if (!state || BAD_STATES.has(String(state.state).toLowerCase())) return '—';
    const raw = state.state;
    if (meta.format === 'text') return raw;
    const num = parseFloat(raw);
    if (isNaN(num)) return raw;
    switch (meta.format) {
      case 'percent':
        return num.toFixed(1) + '%';
      case 'energy':
        return num.toFixed(2) + ' kWh';
      case 'cell':
        return num.toFixed(3) + ' V';
      case 'volts':
        return num.toFixed(2) + ' V';
      case 'amps':
        return (num >= 0 ? '+' : '') + num.toFixed(1) + ' A';
      case 'int':
        return String(Math.round(num));
      case 'power_kw':
        return num.toFixed(2) + ' kW';
      case 'power':
        if (Math.abs(num) >= 1000) return (num / 1000).toFixed(2) + ' kW';
        return Math.round(num) + ' W';
      case 'hz':
        return num.toFixed(2) + ' Hz';
      case 'var':
        if (Math.abs(num) >= 1000) return (num / 1000).toFixed(2) + ' kvar';
        return Math.round(num) + ' var';
      case 'temp':
        return num.toFixed(1) + ' °C';
      case 'duration_s': {
        if (num >= 86400) return (num / 86400).toFixed(1) + ' d';
        if (num >= 3600) return (num / 3600).toFixed(1) + ' h';
        if (num >= 60) return (num / 60).toFixed(0) + ' min';
        return Math.round(num) + ' s';
      }
      case 'number':
        if (Math.abs(num) >= 1000) return (num / 1000).toFixed(2);
        return num.toFixed(Math.abs(num) < 10 ? 2 : 1);
      default:
        return String(raw);
    }
  }

  // Matches signs.py: DISCHARGE_IS_NEGATIVE + idle band (IDLE_BAND_A).
  function flowFromCurrent(current) {
    if (isNaN(current)) return { label: '—', mode: 'idle' };
    const band = typeof IDLE_BAND_A === 'number' ? IDLE_BAND_A : 1.0;
    if (Math.abs(current) <= band) return { label: 'IDLE', mode: 'idle' };
    const dischargeNeg =
      typeof DISCHARGE_IS_NEGATIVE === 'boolean' ? DISCHARGE_IS_NEGATIVE : true;
    if (dischargeNeg) {
      return current < 0
        ? { label: 'DISCHARGE', mode: 'discharge' }
        : { label: 'CHARGE', mode: 'charge' };
    }
    return current > 0
      ? { label: 'DISCHARGE', mode: 'discharge' }
      : { label: 'CHARGE', mode: 'charge' };
  }

  function num(entityKey) {
    const st = client.getState(METRICS[entityKey].entity);
    if (!st || BAD_STATES.has(String(st.state).toLowerCase())) return NaN;
    return parseFloat(st.state);
  }

  function updateAll() {
    if (!client) return;

    for (const [key, meta] of Object.entries(METRICS)) {
      const state = client.getState(meta.entity);
      document.querySelectorAll(`[data-metric="${key}"] .metric-value`).forEach((el) => {
        el.textContent = formatValue(meta, state);
      });
    }

    const status = client.getState(METRICS.status.entity)?.state || '—';
    const soc = num('soc');
    const power = num('power');
    const current = num('current');
    const volts = num('volts');
    const fault = client.getState(METRICS.fault.entity)?.state || '—';
    const solar = num('solarKw');
    const load = num('loadKw');
    const flow = flowFromCurrent(current);

    // Status pill
    const pill = $('#status-pill');
    if (pill) {
      const st = BAD_STATES.has(String(status).toLowerCase()) ? '—' : status;
      pill.textContent = st + ' · ' + flow.label;
      pill.dataset.mode = flow.mode;
    }

    // KPIs
    $('#kpi-volts').textContent = isNaN(volts) ? '—' : volts.toFixed(2) + ' V';
    $('#kpi-soc').textContent = isNaN(soc) ? '—' : soc.toFixed(1) + '%';
    const kpiAmps = $('#kpi-amps');
    kpiAmps.textContent = isNaN(current)
      ? '—'
      : (current >= 0 ? '+' : '') + current.toFixed(1) + ' A';
    kpiAmps.dataset.mode = flow.mode;
    $('#kpi-flow').textContent = flow.label;
    $('#kpi-flow').dataset.mode = flow.mode;
    $('#kpi-power').textContent = isNaN(power)
      ? '—'
      : Math.abs(power) >= 1000
        ? (power / 1000).toFixed(2) + ' kW'
        : Math.round(power) + ' W';

    // Left gauges
    if (!isNaN(soc)) {
      const cls = soc < 20 ? 'mode-low' : soc < 50 ? 'mode-mid' : 'mode-high';
      setRing('g-soc-arc', soc, cls);
      $('#g-soc-val').textContent = soc.toFixed(0);
    }
    if (!isNaN(volts)) {
      // 36–50 V range
      setRing('g-volts-arc', ((volts - 36) / 14) * 100, 'mode-high');
      $('#g-volts-val').textContent = volts.toFixed(1);
    }
    if (!isNaN(current)) {
      // -200..200 → 0..100 with center idle
      const pct = ((current + 200) / 400) * 100;
      const cls =
        flow.mode === 'charge' ? 'mode-charge' : flow.mode === 'discharge' ? 'mode-discharge' : 'mode-idle';
      setRing('g-amps-arc', pct, cls);
      $('#g-amps-val').textContent =
        (current >= 0 ? '+' : '') + (Math.abs(current) >= 100 ? Math.round(current) : current.toFixed(0));
    }
    if (!isNaN(power)) {
      const pct = Math.min(100, (Math.abs(power) / 15000) * 100);
      const cls =
        power > 20 ? 'mode-charge' : power < -20 ? 'mode-discharge' : 'mode-idle';
      setRing('g-power-arc', pct, cls);
      $('#g-power-val').textContent =
        Math.abs(power) >= 1000 ? (power / 1000).toFixed(1) + 'k' : String(Math.round(power));
    }
    if (!isNaN(solar)) {
      setRing('g-solar-arc', Math.min(100, (solar / 15) * 100), 'mode-high');
      $('#g-solar-val').textContent = solar.toFixed(1);
    }
    if (!isNaN(load)) {
      setRing('g-load-arc', Math.min(100, (load / 15) * 100), 'mode-mid');
      $('#g-load-val').textContent = load.toFixed(1);
    }

    // Fault
    const banner = $('#fault-banner');
    if (fault && !BAD_STATES.has(fault.toLowerCase()) && fault !== 'No Fault') {
      banner.classList.remove('hidden');
      banner.textContent = 'BMS fault: ' + fault;
    } else {
      banner.classList.add('hidden');
    }

    updateGridStartButtons();
    drawSparkline();
  }

  function recordHistory() {
    if (!client) return;
    const power = num('power');
    if (isNaN(power)) return;
    history.push({ t: Date.now(), power });
    if (history.length > MAX_HISTORY) history.shift();
  }

  function drawSparkline() {
    const canvas = $('#power-sparkline');
    if (!canvas || history.length < 2) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    const values = history.map((p) => p.power);
    const max = Math.max(...values, 200);
    const min = Math.min(...values, -200);
    const range = max - min || 1;
    const zeroY = h - ((0 - min) / range) * (h - 8) - 4;
    ctx.beginPath();
    ctx.strokeStyle = 'rgba(255,255,255,0.08)';
    ctx.moveTo(0, zeroY);
    ctx.lineTo(w, zeroY);
    ctx.stroke();
    ctx.beginPath();
    ctx.strokeStyle = '#ff7700';
    ctx.lineWidth = 2;
    history.forEach((p, i) => {
      const x = (i / (history.length - 1)) * w;
      const y = h - ((p.power - min) / range) * (h - 8) - 4;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }

  function renderMetricPlaceholders() {
    const grid = $('#metrics-grid');
    if (!grid) return;
    grid.innerHTML = GROUPS.map((g) => {
      const keys = Object.entries(METRICS)
        .filter(([, m]) => m.group === g.id)
        .map(([k]) => k);
      return `
        <section class="metric-group">
          <h3>${g.title}</h3>
          <div class="metric-cards">
            ${keys
              .map(
                (key) => `
              <div class="metric-card" data-metric="${key}">
                <span class="metric-label">${METRICS[key].label}</span>
                <span class="metric-value">—</span>
              </div>`
              )
              .join('')}
          </div>
        </section>`;
    }).join('');
  }

  document.addEventListener('DOMContentLoaded', init);
})();
