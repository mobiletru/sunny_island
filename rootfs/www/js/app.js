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
    renderParamPanel();
    renderQuirksPanel();
    renderMetricPlaceholders();
    bindAuth();
    bindSettings();
    bindQuirks();
    bindChargerButtons();
    bindGridStartButtons();
    bindParamPanel();
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
      closeQuirks();
      $('#settings-panel').classList.toggle('open');
    });
    document.addEventListener('click', (e) => {
      if (!e.target.closest('.settings-wrap')) {
        $('#settings-panel').classList.remove('open');
      }
    });
  }

  function openQuirks() {
    $('#settings-panel')?.classList.remove('open');
    const ov = $('#quirks-overlay');
    if (!ov) return;
    ov.classList.remove('hidden');
    ov.setAttribute('aria-hidden', 'false');
    updateQuirksPanel();
  }

  function closeQuirks() {
    const ov = $('#quirks-overlay');
    if (!ov) return;
    ov.classList.add('hidden');
    ov.setAttribute('aria-hidden', 'true');
  }

  function renderQuirksPanel() {
    const body = $('#quirks-body');
    if (!body || typeof QUIRKS === 'undefined') return;
    body.innerHTML = QUIRKS.map((q) => {
      if (q.kind === 'toggle') {
        return `
          <div class="quirk-row" data-quirk="${q.id}">
            <div class="quirk-meta">
              <span class="quirk-label">${q.label}</span>
              <span class="quirk-hint">${q.hint || ''}</span>
            </div>
            <button type="button" class="quirk-toggle" data-quirk-id="${q.id}" aria-pressed="false">
              <span class="quirk-toggle-knob"></span>
              <span class="quirk-toggle-text">off</span>
            </button>
          </div>`;
      }
      return `
        <div class="quirk-row" data-quirk="${q.id}">
          <div class="quirk-meta">
            <span class="quirk-label">${q.label}</span>
            <span class="quirk-hint">${q.hint || ''}</span>
          </div>
          <div class="quirk-num">
            <button type="button" class="param-btn btn-ghost-sm" data-quirk-id="${q.id}" data-quirk-step="-">−</button>
            <span class="quirk-value" id="quirk-val-${q.id}">—</span>
            <button type="button" class="param-btn btn-ghost-sm" data-quirk-id="${q.id}" data-quirk-step="+">+</button>
          </div>
        </div>`;
    }).join('') + `
      <div class="quirk-row quirk-status-row">
        <div class="quirk-meta">
          <span class="quirk-label">Plant automations</span>
          <span class="quirk-hint" id="quirk-auto-status">—</span>
        </div>
      </div>`;
  }

  function bindQuirks() {
    $('#quirks-btn')?.addEventListener('click', (e) => {
      e.stopPropagation();
      const ov = $('#quirks-overlay');
      if (ov?.classList.contains('hidden')) openQuirks();
      else closeQuirks();
    });
    $('#quirks-close')?.addEventListener('click', closeQuirks);
    $('#quirks-overlay')?.addEventListener('click', (e) => {
      if (e.target.id === 'quirks-overlay') closeQuirks();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closeQuirks();
    });

    $('#quirks-body')?.addEventListener('click', async (e) => {
      const btn = e.target.closest('[data-quirk-id]');
      if (!btn) return;
      const q = (QUIRKS || []).find((x) => x.id === btn.dataset.quirkId);
      if (!q || !client) {
        toast('Connect to Home Assistant first', 'error');
        return;
      }
      try {
        if (q.kind === 'toggle') {
          const on = (client.getState(q.entity)?.state || '') === 'on';
          await client.callService(
            'input_boolean',
            on ? 'turn_off' : 'turn_on',
            {},
            { entity_id: q.entity }
          );
          toast(`${q.label} → ${on ? 'off' : 'on'}`, 'success');
        } else if (q.kind === 'number' && btn.dataset.quirkStep) {
          const cur = parseFloat(client.getState(q.entity)?.state);
          let next = Number.isFinite(cur) ? cur : 0;
          const step = Number(q.step) || 1;
          next = btn.dataset.quirkStep === '+' ? next + step : next - step;
          if (q.min != null) next = Math.max(q.min, next);
          if (q.max != null) next = Math.min(q.max, next);
          // honor step precision
          const decimals = String(step).includes('.') ? String(step).split('.')[1].length : 0;
          next = Number(next.toFixed(decimals));
          await client.callService(
            'input_number',
            'set_value',
            { value: next },
            { entity_id: q.entity }
          );
          toast(`${q.label} → ${next}${q.unit ? ' ' + q.unit : ''}`, 'success');
        }
      } catch (err) {
        toast(err.message || 'Quirk write failed', 'error');
      }
    });

    $('#quirks-run-amps')?.addEventListener('click', async () => {
      if (!client) {
        toast('Connect first', 'error');
        return;
      }
      try {
        await client.callService('script', 'set_tessie_amps_from_bms');
        toast('Auto amps script ran', 'success');
      } catch (err) {
        toast(err.message || 'Auto amps failed', 'error');
      }
    });

    $('#quirks-enable-autos')?.addEventListener('click', async () => {
      if (!client) {
        toast('Connect first', 'error');
        return;
      }
      const list = [
        'automation.tessie_auto_amps_from_evtv_bms',
        'automation.evtv_bms_voltage_stop_tessie_charging',
        'automation.evtv_bms_voltage_approaching_stop_warn',
        'automation.sync_car_charger_flag_with_x_charge',
      ];
      try {
        for (const entity_id of list) {
          await client.callService('automation', 'turn_on', {}, { entity_id });
        }
        toast('Plant automations enabled', 'success');
        updateQuirksPanel();
      } catch (err) {
        toast(err.message || 'Could not enable automations', 'error');
      }
    });
  }

  function updateQuirksPanel() {
    if (!client || typeof QUIRKS === 'undefined') return;
    QUIRKS.forEach((q) => {
      const st = client.getState(q.entity);
      const raw = st?.state;
      if (q.kind === 'toggle') {
        const on = raw === 'on';
        const btn = document.querySelector(`.quirk-toggle[data-quirk-id="${q.id}"]`);
        if (btn) {
          btn.classList.toggle('is-on', on);
          btn.setAttribute('aria-pressed', on ? 'true' : 'false');
          const t = btn.querySelector('.quirk-toggle-text');
          if (t) t.textContent = on ? 'on' : 'off';
        }
      } else {
        const el = document.getElementById(`quirk-val-${q.id}`);
        if (el) {
          if (raw == null || BAD_STATES.has(String(raw).toLowerCase())) el.textContent = '—';
          else el.textContent = `${raw}${q.unit ? ' ' + q.unit : ''}`;
        }
      }
    });
    const autoEl = $('#quirk-auto-status');
    if (autoEl) {
      const names = [
        ['amps', 'automation.tessie_auto_amps_from_evtv_bms'],
        ['pack stop', 'automation.evtv_bms_voltage_stop_tessie_charging'],
        ['sync', 'automation.sync_car_charger_flag_with_x_charge'],
      ];
      autoEl.textContent = names
        .map(([label, eid]) => {
          const s = client.getState(eid)?.state || '?';
          return `${label}: ${s}`;
        })
        .join(' · ');
    }
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

    const matchEvtv = async () => {
      if (!client) {
        toast('Connect to Home Assistant first', 'error');
        return;
      }
      try {
        toast('Match EVTV charge rate → Tessie…', 'info');
        await client.callService('script', 'start_evtv_matched_charge');
        const tcch = client.getState(METRICS.evtvTcch?.entity)?.state;
        const amps = client.getState('number.x_charge_current')?.state;
        toast(`EVTV ${tcch ?? '—'} A → Tessie ${amps ?? '—'} A`, 'success');
      } catch (err) {
        toast(err.message || 'EVTV match charge failed', 'error');
      }
    };
    $('#evtv-match-charge-btn')?.addEventListener('click', matchEvtv);
    // param panel action
    window.__siMatchEvtvCharge = matchEvtv;
  }

  /** Build full parameter-as-buttons panel from PARAM_CONTROLS */
  function renderParamPanel() {
    const panel = $('#param-panel');
    if (!panel || typeof PARAM_CONTROLS === 'undefined') return;
    const groups = [];
    const byGroup = {};
    PARAM_CONTROLS.forEach((p) => {
      if (!byGroup[p.group]) {
        byGroup[p.group] = [];
        groups.push(p.group);
      }
      byGroup[p.group].push(p);
    });
    panel.innerHTML = groups
      .map((g) => {
        const rows = byGroup[g]
          .map((ctrl) => {
            const liveId = `param-live-${ctrl.id}`;
            let controls = '';
            if (ctrl.kind === 'enum' || ctrl.kind === 'action') {
              controls = (ctrl.options || [])
                .map(
                  (o) =>
                    `<button type="button" class="param-btn ${o.cls || 'btn-secondary'}" ` +
                    `data-param-id="${ctrl.id}" data-param-value="${o.value}" ` +
                    (o.action ? `data-param-action="${o.action}" ` : '') +
                    `>${o.label}</button>`
                )
                .join('');
            } else if (ctrl.kind === 'number') {
              const presets = (ctrl.presets || [])
                .map(
                  (n) =>
                    `<button type="button" class="param-btn btn-secondary" ` +
                    `data-param-id="${ctrl.id}" data-param-value="${n}">${n}</button>`
                )
                .join('');
              controls =
                `<button type="button" class="param-btn btn-ghost-sm" data-param-id="${ctrl.id}" data-param-step="-">−${ctrl.step || 5}</button>` +
                presets +
                `<button type="button" class="param-btn btn-ghost-sm" data-param-id="${ctrl.id}" data-param-step="+">+${ctrl.step || 5}</button>`;
            } else {
              controls = `<button type="button" class="param-btn param-readonly" disabled data-param-id="${ctrl.id}">Live</button>`;
            }
            return `
              <div class="param-row" data-param-row="${ctrl.id}" data-kind="${ctrl.kind}">
                <div class="param-head">
                  <span class="param-title">${ctrl.title}</span>
                  <span class="param-live" id="${liveId}">—</span>
                </div>
                <div class="param-btns">${controls}</div>
              </div>`;
          })
          .join('');
        return `<div class="param-group"><div class="param-group-title">${g}</div>${rows}</div>`;
      })
      .join('');
  }

  function currentMetricValue(metricKey) {
    if (!client || !metricKey || !METRICS[metricKey]) return null;
    const st = client.getState(METRICS[metricKey].entity);
    if (!st || BAD_STATES.has(String(st.state).toLowerCase())) return null;
    return st.state;
  }

  function writeSiParameter(parameter, value) {
    return client.callService('tesla_evtv_bms', 'set_si_parameter', {
      parameter,
      value: String(value),
      entity_prefix: typeof PACK_PREFIX === 'string' ? PACK_PREFIX : undefined,
    });
  }

  function bindParamPanel() {
    const panel = $('#param-panel');
    if (!panel) return;
    panel.addEventListener('click', async (e) => {
      const btn = e.target.closest('[data-param-id]');
      if (!btn || btn.disabled) return;
      const id = btn.dataset.paramId;
      const ctrl = (PARAM_CONTROLS || []).find((p) => p.id === id);
      if (!ctrl) return;
      if (!client) {
        toast('Connect to Home Assistant first', 'error');
        return;
      }
      // Action buttons (Tessie / EVTV match)
      if (btn.dataset.paramAction === 'match_evtv_charge') {
        if (typeof window.__siMatchEvtvCharge === 'function') window.__siMatchEvtvCharge();
        else $('#evtv-match-charge-btn')?.click();
        return;
      }
      if (btn.dataset.paramAction === 'start_charge') {
        $('#start-charger-main')?.click();
        return;
      }
      if (btn.dataset.paramAction === 'stop_charge') {
        $('#stop-charger-main')?.click();
        return;
      }
      if (ctrl.kind === 'readonly') return;

      let value = btn.dataset.paramValue;
      if (btn.dataset.paramStep) {
        const cur = parseFloat(currentMetricValue(ctrl.metric));
        value = String(
          nextParamStep(cur, ctrl.step, btn.dataset.paramStep, ctrl.min, ctrl.max)
        );
      }
      if (value == null || value === '') return;
      if (!ctrl.write?.parameter) return;
      btn.classList.add('is-busy');
      try {
        await writeSiParameter(ctrl.write.parameter, value);
        toast(`${ctrl.title} → ${value}`, 'success');
        // optimistic live label
        const live = document.getElementById(`param-live-${ctrl.id}`);
        if (live && ctrl.kind === 'number') live.textContent = value;
      } catch (err) {
        toast(err.message || 'Parameter write failed', 'error');
      } finally {
        btn.classList.remove('is-busy');
      }
    });
  }

  function updateParamPanel() {
    if (!client || typeof PARAM_CONTROLS === 'undefined') return;
    PARAM_CONTROLS.forEach((ctrl) => {
      const live = document.getElementById(`param-live-${ctrl.id}`);
      const meta = ctrl.metric && METRICS[ctrl.metric];
      if (live && meta) {
        const st = client.getState(meta.entity);
        live.textContent = formatValue(meta, st);
      }
      // highlight active enum option
      if (ctrl.kind === 'enum') {
        const raw = String(currentMetricValue(ctrl.metric) || '').toLowerCase();
        document
          .querySelectorAll(`[data-param-id="${ctrl.id}"][data-param-value]`)
          .forEach((btn) => {
            const v = (btn.dataset.paramValue || '').toLowerCase();
            let active = false;
            if (ctrl.id === 'grid_control') {
              if (v === 'manual_on')
                active = raw.includes('manual') || raw.includes('request') || raw === 'on';
              else if (v === 'automatic') active = raw.includes('auto');
              else if (v === 'off') active = raw === 'off' || raw.includes('off');
            } else if (ctrl.id === 'reverse_feed') {
              if (v === 'yes') active = raw === 'yes' || raw.includes('yes');
              else if (v === 'no') active = raw === 'no' || raw.includes('no');
            } else if (ctrl.id === 'power_setpoint_mode') {
              if (v === 'off') active = raw === 'off';
              else if (v === 'manual_w') active = raw.includes('manual w') || raw.includes(' w');
              else if (v === 'manual_pct')
                active = raw.includes('%') || raw.includes('percent') || raw.includes('pct');
              else if (v === 'external') active = raw.includes('external');
            } else {
              active = raw === v || raw.includes(v);
            }
            btn.classList.toggle('is-active', active);
          });
      }
      if (ctrl.kind === 'number') {
        const cur = parseFloat(currentMetricValue(ctrl.metric));
        document
          .querySelectorAll(`[data-param-id="${ctrl.id}"][data-param-value]`)
          .forEach((btn) => {
            const v = parseFloat(btn.dataset.paramValue);
            btn.classList.toggle(
              'is-active',
              Number.isFinite(cur) && Number.isFinite(v) && Math.abs(cur - v) < 0.51
            );
          });
      }
    });
  }

  /** Grid start: RPC GdManStr (Start / Auto / Stop). Do not write 40527. */
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
      case 'ah':
        return Math.round(num) + ' Ah';
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
    const chargeSet = num('webboxChargeV');
    const kpiCharge = $('#kpi-charge-set');
    if (kpiCharge) {
      kpiCharge.textContent = isNaN(chargeSet) ? '—' : chargeSet.toFixed(1) + ' V';
    }
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

    // Left gauges — unavailable / NaN must show em-dash, not a leftover number.
    if (!isNaN(soc)) {
      const cls = soc < 20 ? 'mode-low' : soc < 50 ? 'mode-mid' : 'mode-high';
      setRing('g-soc-arc', soc, cls);
      $('#g-soc-val').textContent = soc.toFixed(0);
    } else {
      setRing('g-soc-arc', 0);
      $('#g-soc-val').textContent = '—';
    }
    if (!isNaN(volts)) {
      // 12S Tesla on SI6048 ≈ 36–50 V (live plant ~42 V)
      setRing('g-volts-arc', ((volts - 36) / 14) * 100, 'mode-high');
      $('#g-volts-val').textContent = volts.toFixed(1);
    } else {
      setRing('g-volts-arc', 0);
      $('#g-volts-val').textContent = '—';
    }
    if (!isNaN(current)) {
      // -200..200 → 0..100 with center idle
      const pct = ((current + 200) / 400) * 100;
      const cls =
        flow.mode === 'charge' ? 'mode-charge' : flow.mode === 'discharge' ? 'mode-discharge' : 'mode-idle';
      setRing('g-amps-arc', pct, cls);
      $('#g-amps-val').textContent =
        (current >= 0 ? '+' : '') + (Math.abs(current) >= 100 ? Math.round(current) : current.toFixed(0));
    } else {
      setRing('g-amps-arc', 50, 'mode-idle');
      $('#g-amps-val').textContent = '—';
    }
    if (!isNaN(power)) {
      const pct = Math.min(100, (Math.abs(power) / 15000) * 100);
      const cls =
        power > 20 ? 'mode-charge' : power < -20 ? 'mode-discharge' : 'mode-idle';
      setRing('g-power-arc', pct, cls);
      $('#g-power-val').textContent =
        Math.abs(power) >= 1000 ? (power / 1000).toFixed(1) + 'k' : String(Math.round(power));
    } else {
      setRing('g-power-arc', 0);
      $('#g-power-val').textContent = '—';
    }
    if (!isNaN(solar)) {
      setRing('g-solar-arc', Math.min(100, (solar / 15) * 100), 'mode-high');
      $('#g-solar-val').textContent = solar.toFixed(1);
    } else {
      setRing('g-solar-arc', 0);
      $('#g-solar-val').textContent = '—';
    }
    if (!isNaN(load)) {
      setRing('g-load-arc', Math.min(100, (load / 15) * 100), 'mode-mid');
      $('#g-load-val').textContent = load.toFixed(1);
    } else {
      setRing('g-load-arc', 0);
      $('#g-load-val').textContent = '—';
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
    updateParamPanel();
    updateQuirksPanel();
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
