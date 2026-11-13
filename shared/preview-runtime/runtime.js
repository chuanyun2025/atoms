(() => {
  "use strict";
  const marker = document.head.querySelector('meta[name="atoms-runtime-config"]');
  const config = JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(marker.content), c => c.charCodeAt(0))));
  let initialized = false, port, sequence = 0;
  const values = new Map(), pending = new Map(), failures = new Map();
  const clone = value => JSON.parse(JSON.stringify(value));
  const validKey = key => typeof key === "string" && /^[A-Za-z0-9_.:-]{1,64}$/.test(key) && !["__proto__", "prototype", "constructor"].includes(key);
  function send(type, payload = {}) {
    const message_id = String(++sequence);
    return new Promise((resolve, reject) => {
      if (pending.size > 128) return reject(new Error("待保存请求过多"));
      const timer = setTimeout(() => { pending.delete(message_id); reject(new Error("保存请求超时")); }, 15000);
      pending.set(message_id, { resolve, reject, timer, key: payload.key });
      port.postMessage({ protocol_version: 1, instance_id: config.instance_id, message_id, type, payload });
    });
  }
  function mutate(type, key, value) {
    if (!validKey(key)) throw new Error("存储键无效");
    if (config.read_only) throw new Error("历史预览为只读");
    if (type === "storage.set") {
      if (value === undefined) throw new Error("不能保存 undefined");
      const copied = clone(value);
      if (new TextEncoder().encode(JSON.stringify(copied)).length > 16384) throw new Error("单项数据超过 16 KiB");
      values.set(key, copied);
      value = copied;
    } else values.delete(key);
    failures.delete(key);
    send(type, type === "storage.set" ? { key, value } : { key }).catch(error => failures.set(key, error));
  }
  window.addEventListener("message", async event => {
    const data = event.data;
    if (initialized || event.source !== window.parent || event.origin !== config.app_origin ||
        !data || data.type !== "atoms.init" || data.instance_id !== config.instance_id ||
        data.channel_nonce !== config.channel_nonce || !event.ports[0]) return;
    initialized = true;
    port = event.ports[0];
    config.read_only = Boolean(data.read_only);
    for (const [key, value] of Object.entries(data.values || {})) if (validKey(key)) values.set(key, clone(value));
    port.onmessage = ({ data: reply }) => {
      if (!reply || reply.instance_id !== config.instance_id) return;
      const task = pending.get(reply.message_id);
      if (!task) return;
      clearTimeout(task.timer);
      pending.delete(reply.message_id);
      if (reply.ok) task.resolve(reply);
      else task.reject(new Error(String(reply.error || "数据尚未保存")));
    };
    port.start();
    const storage = Object.freeze({
      get(key, fallback = null) {
        if (!validKey(key)) throw new Error("存储键无效");
        return values.has(key) ? clone(values.get(key)) : clone(fallback);
      },
      set(key, value) { mutate("storage.set", key, value); },
      remove(key) { mutate("storage.remove", key); },
      async flush() {
        await send("storage.flush");
        if (failures.size) throw failures.values().next().value;
      }
    });
    Object.defineProperty(window, "atoms", { value: Object.freeze({ storage }), writable: false, configurable: false });
    const report = error => {
      const text = String(error && error.message || error || "预览运行错误").slice(0, 1200);
      send("runtime.error", { message: text }).catch(() => {});
    };
    window.addEventListener("error", event => report(event.error || event.message));
    window.addEventListener("unhandledrejection", event => report(event.reason));
    const script = document.createElement("script");
    script.src = "data:application/javascript;base64," + config.js_base64;
    script.onload = () => send("runtime.ready", {}).catch(() => {});
    script.onerror = () => report("应用脚本未能加载");
    document.head.appendChild(script);
  });
})();
