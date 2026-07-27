/**
 * Minimal Home Assistant WebSocket client for live entity updates.
 */
class HAClient {
  constructor({ url, token, onConnect, onDisconnect, onStateChange, onError }) {
    this.url = url;
    this.token = token;
    this.onConnect = onConnect;
    this.onDisconnect = onDisconnect;
    this.onStateChange = onStateChange;
    this.onError = onError;
    this.ws = null;
    this.msgId = 1;
    this.pending = new Map();
    this.states = new Map();
    this.reconnectTimer = null;
    this.intentionalClose = false;
    this.subscribeId = null;
  }

  connect() {
    this.intentionalClose = false;
    this.ws = new WebSocket(this.url);

    this.ws.onopen = () => {
      this._send({ type: 'auth', access_token: this.token });
    };

    this.ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      this._handleMessage(msg);
    };

    this.ws.onclose = () => {
      this.onDisconnect?.();
      if (!this.intentionalClose) {
        this.reconnectTimer = setTimeout(() => this.connect(), 3000);
      }
    };

    this.ws.onerror = () => {
      this.onError?.('WebSocket connection failed');
    };
  }

  disconnect() {
    this.intentionalClose = true;
    clearTimeout(this.reconnectTimer);
    this.ws?.close();
  }

  async subscribeEntities(entityIds) {
    this.subscribeId = await this._call('subscribe_entities', { entity_ids: entityIds }, true);
  }

  getStates() {
    return Object.fromEntries(this.states);
  }

  getState(entityId) {
    return this.states.get(entityId) || null;
  }

  callService(domain, service, serviceData = {}, target = {}) {
    return this._call('call_service', {
      domain,
      service,
      service_data: serviceData,
      target,
    });
  }

  _mergeState(entityId, patch) {
    const existing = this.states.get(entityId) || { entity_id: entityId, attributes: {} };
    const merged = {
      ...existing,
      ...patch,
      attributes: { ...existing.attributes, ...(patch.attributes || {}) },
    };
    this.states.set(entityId, merged);
    this.onStateChange?.(entityId, merged);
  }

  _handleSubscribeEntitiesEvent(event) {
    if (event.a) {
      for (const [id, state] of Object.entries(event.a)) {
        this.states.set(id, state);
        this.onStateChange?.(id, state);
      }
    }
    if (event.c) {
      for (const [id, changes] of Object.entries(event.c)) {
        this._mergeState(id, changes);
      }
    }
    if (event.r) {
      for (const id of event.r) this.states.delete(id);
    }
  }

  _handleMessage(msg) {
    if (msg.type === 'auth_required') return;

    if (msg.type === 'auth_ok') {
      this.onConnect?.();
      return;
    }

    if (msg.type === 'auth_invalid') {
      this.onError?.('Invalid access token');
      this.disconnect();
      return;
    }

    if (msg.type === 'result' && msg.id && this.pending.has(msg.id)) {
      const { resolve, reject } = this.pending.get(msg.id);
      this.pending.delete(msg.id);
      if (msg.success) resolve(msg.result);
      else reject(new Error(msg.error?.message || 'Request failed'));
      return;
    }

    if (msg.type === 'event' && msg.id === this.subscribeId && msg.event) {
      this._handleSubscribeEntitiesEvent(msg.event);
      return;
    }

    if (msg.type === 'event' && msg.event?.event_type === 'state_changed') {
      const { entity_id, new_state } = msg.event.data;
      if (!new_state) return;
      this.states.set(entity_id, new_state);
      this.onStateChange?.(entity_id, new_state);
    }
  }

  _send(msg) {
    this.ws?.send(JSON.stringify(msg));
  }

  _call(type, payload = {}, returnId = false) {
    return new Promise((resolve, reject) => {
      const id = this.msgId++;
      this.pending.set(id, {
        resolve: (result) => resolve(returnId ? id : result),
        reject,
      });
      this._send({ id, type, ...payload });
    });
  }
}

function detectHAUrl() {
  const { protocol, host } = window.location;
  const wsProto = protocol === 'https:' ? 'wss:' : 'ws:';
  return `${wsProto}//${host}/api/websocket`;
}

const HA_TOKEN_KEY = 'sunny_island_ha_token';

function getStoredToken() {
  return (
    localStorage.getItem(HA_TOKEN_KEY) ||
    localStorage.getItem('sunny_island_detail_ha_token') ||
    ''
  );
}

function storeToken(token) {
  localStorage.setItem(HA_TOKEN_KEY, token);
}

function clearToken() {
  localStorage.removeItem(HA_TOKEN_KEY);
  localStorage.removeItem('sunny_island_detail_ha_token');
}

function getDashboardBasePath() {
  const scripts = document.getElementsByTagName('script');
  for (const script of scripts) {
    const src = script.getAttribute('src') || '';
    if (src.includes('/js/')) {
      return src.replace(/\/js\/[^/]+$/, '');
    }
  }
  return '';
}
