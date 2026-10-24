/* Blinks Bright — admin realtime WebSocket client */

let socket = null;
let handler = null;
let globalHandler = null;
let reconnectTimer = null;

export function initWS() {
  if (socket && (socket.readyState === WebSocket.CONNECTING || socket.readyState === WebSocket.OPEN)) {
    return;
  }
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  try {
    socket = new WebSocket(`${proto}://${location.host}/api/ws`);
  } catch (e) { return; }

  socket.onmessage = (ev) => {
    let data;
    try { data = JSON.parse(ev.data); } catch (e) { return; }
    if (data.type === 'ping') return;
    // the global handler (e.g. the notification bell) runs on every view;
    // the per-view handler only when a realtime view has registered one.
    if (globalHandler) { try { globalHandler(data); } catch (e) { /* ignore */ } }
    if (handler) { try { handler(data); } catch (e) { /* ignore */ } }
  };
  socket.onclose = () => {
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(initWS, 2500);
  };
  socket.onerror = () => { try { socket.close(); } catch (e) {} };
}

/** Set the single active event handler (null clears it on view change). */
export function setWSHandler(fn) {
  handler = fn;
}

/** An always-on handler (e.g. the notification bell) that survives view changes. */
export function setGlobalWSHandler(fn) {
  globalHandler = fn;
}
