/**
 * Minimal Home Assistant WebSocket client for live entity updates.
 *
 * Handles only the compressed subscribe_entities wire format (HA ≥ 2022.4):
 *   add:    { a: { entity_id: { s, a, c, lc, lu } } }
 *   change: { c: { entity_id: { "+": { s?, a?, ... }, "-": { a?: keys } } } }
 *   remove: { r: [entity_id, ...] }
 * Expanded to normal HassEntity shape { entity_id, state, attributes, ... }.
 *
 * Pure expand/diff helpers are exported on window.__siHaEntities for unit tests.
 */
(function (global) {
  'use strict';

  function expandCompressed(entityId, compressed) {
    const lastChanged = compressed.lc
      ? new Date(compressed.lc * 1000).toISOString()
      : new Date().toISOString();
    const lastUpdated = compressed.lu
      ? new Date(compressed.lu * 1000).toISOString()
      : lastChanged;
    const ctx = compressed.c;
    return {
      entity_id: entityId,
      state: compressed.s,
      attributes: compressed.a || {},
      context:
        typeof ctx === 'string'
          ? { id: ctx, parent_id: null, user_id: null }
          : ctx || { id: null, parent_id: null, user_id: null },
      last_changed: lastChanged,
      last_updated: lastUpdated,
    };
  }

  /**
   * Apply a compressed subscribe_entities event into a Map of HassEntity.
   * Mutates `states` in place; returns the same Map.
   */
  function applySubscribeEntitiesEvent(states, event) {
    if (event.a) {
      for (const [id, compressed] of Object.entries(event.a)) {
        states.set(id, expandCompressed(id, compressed));
      }
    }
    if (event.r) {
      for (const id of event.r) states.delete(id);
    }
    if (event.c) {
      for (const [id, diff] of Object.entries(event.c)) {
        const prev = states.get(id);
        if (!prev) continue;

        const entity = { ...prev, attributes: { ...prev.attributes } };
        const toAdd = diff['+'];
        const toRemove = diff['-'];

        if (toAdd) {
          if (toAdd.s !== undefined) entity.state = toAdd.s;
          if (toAdd.c) {
            if (typeof toAdd.c === 'string') {
              entity.context = { ...entity.context, id: toAdd.c };
            } else {
              entity.context = { ...entity.context, ...toAdd.c };
            }
          }
          if (toAdd.lc) {
            entity.last_changed = entity.last_updated = new Date(
              toAdd.lc * 1000
            ).toISOString();
          } else if (toAdd.lu) {
            entity.last_updated = new Date(toAdd.lu * 1000).toISOString();
          }
          if (toAdd.a) Object.assign(entity.attributes, toAdd.a);
        }
        if (toRemove?.a) {
          for (const key of toRemove.a) delete entity.attributes[key];
        }
        states.set(id, entity);
      }
    }
    return states;
  }

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
      this.subscribeId = await this._call(
        'subscribe_entities',
        { entity_ids: entityIds },
        true
      );
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

    _handleSubscribeEntitiesEvent(event) {
      applySubscribeEntitiesEvent(this.states, event);
      if (event.a) {
        for (const id of Object.keys(event.a)) {
          this.onStateChange?.(id, this.states.get(id));
        }
      }
      if (event.c) {
        for (const id of Object.keys(event.c)) {
          if (this.states.has(id)) {
            this.onStateChange?.(id, this.states.get(id));
          }
        }
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
    const { protocol, host } = global.location;
    const wsProto = protocol === 'https:' ? 'wss:' : 'ws:';
    return `${wsProto}//${host}/api/websocket`;
  }

  const HA_TOKEN_KEY = 'sunny_island_ha_token';

  function getStoredToken() {
    return (
      global.localStorage.getItem(HA_TOKEN_KEY) ||
      global.localStorage.getItem('sunny_island_detail_ha_token') ||
      ''
    );
  }

  function storeToken(token) {
    global.localStorage.setItem(HA_TOKEN_KEY, token);
  }

  function clearToken() {
    global.localStorage.removeItem(HA_TOKEN_KEY);
    global.localStorage.removeItem('sunny_island_detail_ha_token');
  }

  // Browser globals (app.js expects these names)
  global.HAClient = HAClient;
  global.detectHAUrl = detectHAUrl;
  global.getStoredToken = getStoredToken;
  global.storeToken = storeToken;
  global.clearToken = clearToken;
  global.__siHaEntities = { expandCompressed, applySubscribeEntitiesEvent };

  // CommonJS for unit tests (node)
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
      HAClient,
      expandCompressed,
      applySubscribeEntitiesEvent,
      detectHAUrl,
      getStoredToken,
      storeToken,
      clearToken,
    };
  }
})(typeof globalThis !== 'undefined' ? globalThis : this);
