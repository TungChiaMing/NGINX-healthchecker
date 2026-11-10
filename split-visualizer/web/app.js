"use strict";

/* ---------- setup ---------- */

const BACKEND = (() => {
  const configured = (window.SPLIT_BACKEND_URL || "").replace(/\/+$/, "");
  if (configured) return configured;
  if (["localhost", "127.0.0.1"].includes(location.hostname)) return "http://localhost:10000";
  return "";
})();

const KEY_HELP = {
  "$request_id": "Random for every request, so each request is an independent draw. Not sticky.",
  "$remote_addr": "The client IP. The same client always lands in the same bucket.",
  "$arg_user": "The ?user= query parameter. Sticky per user id; try the demo user id field.",
  "$http_x_user": "The X-User request header. Sticky per user id; try the demo user id field.",
};

const NODE_OF_PORT = { "8080": "self", "8082": "new" };
const MAX_LOG = 60;

const S = {
  server: null,      // last state from the backend
  draft: null,       // settings being edited
  dirty: false,
  requests: [],
  selected: null,
  counter: 0,
  stats: { total: 0, split: {}, served: {} },
  sending: false,
};

const $ = (id) => document.getElementById(id);

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v === true) node.setAttribute(k, "");
    else if (v !== false && v != null) node.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c == null) continue;
    node.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return node;
}

function svg(tag, attrs, ...children) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v != null) node.setAttribute(k, v);
  for (const c of children.flat()) {
    if (c == null) continue;
    node.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return node;
}

const clone = (x) => JSON.parse(JSON.stringify(x));
const sideClass = (target) => (target === "new_nginx" ? "new" : target === "legacy_nginx" ? "legacy" : "none");

/* ---------- the same maths Nginx uses (ngx_http_split_clients_module.c) ---------- */

function murmur2(text) {
  const data = new TextEncoder().encode(text);
  const m = 0x5bd1e995;
  let len = data.length;
  let h = len >>> 0;
  let i = 0;
  while (len >= 4) {
    let k = data[i] | (data[i + 1] << 8) | (data[i + 2] << 16) | (data[i + 3] << 24);
    k = Math.imul(k, m);
    k ^= k >>> 24;
    k = Math.imul(k, m);
    h = Math.imul(h, m) ^ k;
    i += 4;
    len -= 4;
  }
  if (len === 3) h ^= data[i + 2] << 16;
  if (len >= 2) h ^= data[i + 1] << 8;
  if (len >= 1) {
    h ^= data[i];
    h = Math.imul(h, m);
  }
  h ^= h >>> 13;
  h = Math.imul(h, m);
  h ^= h >>> 15;
  return h >>> 0;
}

const SPACE = 4294967296;

// Returns one range per bucket: [lo, hi) over the 32-bit hash space.
function bucketRanges(buckets) {
  let sum = 0;
  let last = 0n;
  let lo = 0;
  let closed = false;
  const ranges = [];
  for (const b of buckets) {
    let p = b.percent === "*" ? 0 : Math.round(parseFloat(b.percent) * 100);
    sum = p ? sum + p : 10000;
    if (sum === 10000) p = 0;
    if (sum > 10000) return null;                 // Nginx rejects this config
    if (closed) {
      ranges.push({ ...b, lo: SPACE, hi: SPACE }); // unreachable after a catch-all
    } else if (p) {
      last += (BigInt(p) * 0xffffffffn) / 10000n;
      ranges.push({ ...b, lo, hi: Number(last) });
      lo = Number(last);
    } else {
      ranges.push({ ...b, lo, hi: SPACE });
      lo = SPACE;
      closed = true;
    }
  }
  return ranges;
}

/* ---------- editable text <-> settings ---------- */

function renderEditable(s) {
  const pad = (v) => v.padEnd(8, " ");
  return [
    `split_clients ${s.key} $split_target {`,
    ...s.buckets.map((b) => `    ${pad(b.percent)}${b.target};`),
    "}",
    "",
    "map $http_x_canary $route {",
    ...s.canary.map((c) => `    ${pad(c.match)}${c.target};`),
    "    default $split_target;",
    "}",
  ].join("\n");
}

function parseEntries(body) {
  return body.split(";").map((s) => s.trim()).filter(Boolean).map((s) => {
    const parts = s.split(/\s+/);
    if (parts.length !== 2) throw new Error(`Cannot read "${s}". Each line must be "value target;".`);
    return parts;
  });
}

function parseEditable(text) {
  const clean = text.replace(/#.*$/gm, "");
  const split = clean.match(/split_clients\s+(\S+)\s+(\S+)\s*\{([^{}]*)\}/);
  if (!split) throw new Error("Could not find a complete split_clients { ... } block.");
  if (split[2] !== "$split_target") throw new Error("The split variable must stay $split_target.");
  const map = clean.match(/map\s+(\S+)\s+(\S+)\s*\{([^{}]*)\}/);
  if (!map) throw new Error("Could not find a complete map { ... } block.");
  if (map[1] !== "$http_x_canary" || map[2] !== "$route") throw new Error("The map must stay: map $http_x_canary $route.");
  const canary = [];
  for (const [match, target] of parseEntries(map[3])) {
    if (match === "default") {
      if (target !== "$split_target") throw new Error("The map default must stay $split_target.");
    } else {
      canary.push({ match, target });
    }
  }
  return {
    key: split[1],
    buckets: parseEntries(split[3]).map(([percent, target]) => ({ percent, target })),
    canary,
  };
}

/* ---------- backend calls ---------- */

async function api(path, body) {
  const res = await fetch(BACKEND + path, body === undefined ? { cache: "no-store" } : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let data = null;
  try { data = await res.json(); } catch (e) { /* not json */ }
  if (!res.ok) throw new Error((data && data.error) || `HTTP ${res.status}`);
  return data;
}

function setStatus(kind, text) {
  $("status").className = "status status-" + kind;
  $("status").textContent = text;
}

async function boot() {
  if (!BACKEND) {
    setStatus("bad", "No backend configured");
    $("notice").hidden = false;
    $("notice").textContent = "Set the SPLIT_BACKEND_URL environment variable in Vercel to the URL of the Render service, then redeploy.";
    return;
  }
  for (let attempt = 0; attempt < 40; attempt++) {
    try {
      acceptServerState(await api("/api/state"), true);
      $("app").hidden = false;
      $("notice").hidden = true;
      setInterval(poll, 5000);
      return;
    } catch (e) {
      setStatus("wait", "Waking Nginx…");
      $("notice").hidden = false;
      $("notice").textContent = "Waiting for the Nginx container. On the free tier it sleeps when idle and needs about a minute to wake up.";
      await new Promise((r) => setTimeout(r, 3000));
    }
  }
  setStatus("bad", "Backend unreachable");
  $("notice").textContent = "Could not reach the Nginx backend at " + BACKEND + ". Reload the page to try again.";
}

async function poll() {
  try {
    const next = await api("/api/state");
    if (next.version !== S.server.version || next.new_up !== S.server.new_up) acceptServerState(next, false);
    else renderNewState();
    setStatus("ok", "Nginx online");
  } catch (e) {
    setStatus("wait", "Reconnecting…");
  }
}

function acceptServerState(next, force) {
  const configChanged = !S.server || JSON.stringify(next.settings) !== JSON.stringify(S.server.settings);
  S.server = next;
  setStatus("ok", "Nginx online");
  if (force || !S.dirty) {
    S.draft = clone(next.settings);
    S.dirty = false;
    $("editor").value = next.editable;
    $("parse-error").hidden = true;
    $("remote-change").hidden = true;
    renderForm();
  } else if (configChanged) {
    $("remote-change").hidden = false;
    $("remote-change").textContent = "The config on the server was changed by someone else. Your unapplied edits are kept; Apply will overwrite theirs.";
  }
  if (configChanged) clearResults();
  renderConfs();
  renderSendControls();
  renderNewState();
  renderDirty();
}

/* ---------- config panel ---------- */

function renderConfs() {
  const pre = $("legacy-conf");
  pre.textContent = "";
  const conf = S.server.legacy_conf;
  const start = conf.indexOf("# ---- editable section");
  const end = conf.indexOf("# ---- end of editable section");
  if (start >= 0 && end > start) {
    pre.append(conf.slice(0, start), el("mark", {}, conf.slice(start, end)), conf.slice(end));
  } else {
    pre.textContent = conf;
  }
  $("new-conf").textContent = S.server.new_conf;
}

function targetSelect(value, onchange) {
  const options = S.server.targets.map((t) => el("option", { value: t, selected: t === value }, t));
  if (!S.server.targets.includes(value)) options.unshift(el("option", { value, selected: true }, value + " (unknown)"));
  return el("select", { onchange, "aria-label": "Upstream" }, options);
}

function renderForm() {
  const d = S.draft;
  const key = $("key");
  key.textContent = "";
  for (const k of S.server.keys) key.append(el("option", { value: k, selected: k === d.key }, k));
  if (!S.server.keys.includes(d.key)) key.append(el("option", { value: d.key, selected: true }, d.key + " (not allowed)"));
  $("key-help").textContent = KEY_HELP[d.key] || "This key is not in the allowed list; Nginx will not accept it here.";

  const buckets = $("buckets");
  buckets.textContent = "";
  d.buckets.forEach((b, i) => {
    const isRest = b.percent === "*";
    const number = isRest ? 0 : parseFloat(b.percent) || 0;
    const text = el("input", {
      type: "text", value: b.percent, "aria-label": "Percent", oninput: (e) => {
        b.percent = e.target.value.trim();
        const n = parseFloat(b.percent);
        range.disabled = b.percent === "*";
        if (!isNaN(n)) range.value = n;
        formChanged();
      },
    });
    const range = el("input", {
      type: "range", min: "0", max: "100", step: "1", value: number, disabled: isRest, "aria-label": "Percent slider", oninput: (e) => {
        b.percent = e.target.value + "%";
        text.value = b.percent;
        formChanged();
      },
    });
    buckets.append(el("div", { class: "entry" },
      text, range, el("span", { class: "arrow" }, "→"),
      targetSelect(b.target, (e) => { b.target = e.target.value; formChanged(); }),
      el("button", { type: "button", class: "icon", title: "Remove bucket", "aria-label": "Remove bucket", onclick: () => { d.buckets.splice(i, 1); formChanged(true); } }, "✕"),
    ));
  });

  const canary = $("canary");
  canary.textContent = "";
  d.canary.forEach((c, i) => {
    canary.append(el("div", { class: "entry" },
      el("input", { type: "text", value: c.match, "aria-label": "X-Canary value", oninput: (e) => { c.match = e.target.value.trim(); formChanged(); } }),
      el("span", { class: "arrow" }, "→"),
      targetSelect(c.target, (e) => { c.target = e.target.value; formChanged(); }),
      el("button", { type: "button", class: "icon", title: "Remove override", "aria-label": "Remove override", onclick: () => { d.canary.splice(i, 1); formChanged(true); } }, "✕"),
    ));
  });
}

function formChanged(rebuild) {
  S.dirty = true;
  $("editor").value = renderEditable(S.draft);
  $("parse-error").hidden = true;
  if (rebuild) renderForm();
  renderDirty();
}

function renderDirty() {
  $("dirty").hidden = !S.dirty;
}

function showResult(ok, text) {
  const box = $("apply-result");
  box.hidden = false;
  box.className = "result " + (ok ? "good" : "bad");
  box.textContent = text;
}

async function applyConfig() {
  let settings;
  try {
    settings = parseEditable($("editor").value);
  } catch (e) {
    return showResult(false, e.message);
  }
  $("apply").disabled = true;
  try {
    const next = await api("/api/config", settings);
    S.dirty = false;
    acceptServerState(next, true);
    showResult(true, "nginx -t passed and the Legacy Nginx was reloaded with this config.");
  } catch (e) {
    showResult(false, "Nginx did not accept this config:\n" + e.message);
  } finally {
    $("apply").disabled = false;
  }
}

async function resetConfig() {
  $("reset").disabled = true;
  try {
    S.dirty = false;
    acceptServerState(await api("/api/reset", {}), true);
    showResult(true, "Restored the default config and reloaded Nginx.");
  } catch (e) {
    showResult(false, e.message);
  } finally {
    $("reset").disabled = false;
  }
}

/* ---------- sending requests ---------- */

function renderSendControls() {
  const select = $("canary-send");
  const current = select.value;
  select.textContent = "";
  select.append(el("option", { value: "" }, "(not sent)"));
  for (const c of S.server.settings.canary) {
    select.append(el("option", { value: c.match, selected: c.match === current }, `${c.match}  →  ${c.target}`));
  }
}

function renderNewState() {
  const up = S.server.new_up;
  $("toggle-new").textContent = up ? "Stop New Nginx" : "Start New Nginx";
  const left = Math.max(0, Math.round(S.server.new_down_until - Date.now() / 1000));
  $("new-state").textContent = up
    ? "New Nginx is running. Stop it to see the error_page fallback."
    : `New Nginx is stopped for everyone${left ? `; it restarts by itself in about ${left}s` : ""}.`;
}

async function toggleNew() {
  $("toggle-new").disabled = true;
  try {
    S.server = await api("/api/new-nginx", { up: !S.server.new_up });
    renderNewState();
  } catch (e) {
    $("new-state").textContent = e.message;
  } finally {
    $("toggle-new").disabled = false;
  }
}

async function sendOne(canary, user) {
  const started = performance.now();
  const headers = {};
  if (canary) headers["X-Canary"] = canary;
  if (user) headers["X-User"] = user;
  const url = BACKEND + "/hit" + (user ? "?user=" + encodeURIComponent(user) : "");
  const req = { n: ++S.counter, canary, user, settings: S.server.settings };
  try {
    const res = await fetch(url, { headers, cache: "no-store" });
    let body = null;
    try { body = await res.json(); } catch (e) { /* error pages are html */ }
    Object.assign(req, {
      status: res.status,
      id: res.headers.get("X-Request-Id") || "",
      splitTarget: res.headers.get("X-Split-Target") || "",
      route: res.headers.get("X-Route") || "",
      upstreamAddr: res.headers.get("X-Upstream-Addr") || "",
      upstreamStatus: res.headers.get("X-Upstream-Status") || "",
      clientAddr: res.headers.get("X-Client-Addr") || "",
      servedBy: (body && body.served_by) || "",
    });
  } catch (e) {
    Object.assign(req, { status: 0, id: "", splitTarget: "", route: "", upstreamAddr: "", upstreamStatus: "", clientAddr: "", servedBy: "", networkError: e.message });
  }
  req.ms = Math.round(performance.now() - started);
  return req;
}

function record(req) {
  S.requests.unshift(req);
  if (S.requests.length > MAX_LOG) S.requests.pop();
  S.stats.total++;
  const splitKey = req.splitTarget || "(no bucket)";
  const servedKey = req.servedBy || (req.status ? "HTTP " + req.status : "network error");
  S.stats.split[splitKey] = (S.stats.split[splitKey] || 0) + 1;
  S.stats.served[servedKey] = (S.stats.served[servedKey] || 0) + 1;
}

async function sendBatch(count) {
  if (S.sending) return;
  S.sending = true;
  document.querySelectorAll("[data-send]").forEach((b) => (b.disabled = true));
  const canary = $("canary-send").value;
  const fixedUser = $("user").value.trim();
  const randomUser = $("random-user").checked;
  let next = 0;
  let done = 0;
  let last = null;
  const worker = async () => {
    while (next < count) {
      next++;
      const user = randomUser ? "user-" + Math.random().toString(36).slice(2, 8) : fixedUser;
      last = await sendOne(canary, user);
      record(last);
      done++;
      if (count > 1) $("progress").textContent = `${done} / ${count}`;
    }
  };
  await Promise.all(Array.from({ length: Math.min(8, count) }, worker));
  $("progress").textContent = count > 1 ? `Sent ${count} requests.` : "";
  S.sending = false;
  document.querySelectorAll("[data-send]").forEach((b) => (b.disabled = false));
  renderStats();
  renderLog();
  select(last);
}

function clearResults() {
  S.requests = [];
  S.selected = null;
  S.stats = { total: 0, split: {}, served: {} };
  renderStats();
  renderLog();
  $("sequence").replaceChildren(el("p", { class: "empty" }, "Send a request to see its path."));
  $("why").replaceChildren(el("p", { class: "empty" }, "Nothing sent yet."));
  $("hashline").textContent = "";
  $("seq-title").textContent = "";
  $("trace").textContent = "Select a request.";
}

/* ---------- one request: sequence, explanation, hash line ---------- */

function attempts(req) {
  const addrs = req.upstreamAddr.match(/[\d.]+:\d+/g) || [];
  const statuses = req.upstreamStatus.match(/\d{3}|-/g) || [];
  return addrs.map((addr, i) => ({
    addr,
    node: NODE_OF_PORT[addr.split(":")[1]] || "self",
    status: statuses[i] || "-",
  }));
}

function select(req) {
  if (!req) return;
  S.selected = req;
  $("seq-title").textContent = `request #${req.n}`;
  renderSequence(req);
  renderWhy(req);
  renderLog();
  loadTrace(req);
}

function buildSteps(req) {
  const steps = [];
  const tries = attempts(req);
  const overridden = req.canary && req.route && req.route !== req.splitTarget;
  const forcedSame = req.canary && req.route && req.route === req.splitTarget;

  if (req.networkError) {
    steps.push({ type: "msg", from: "client", to: "front", label: "GET /hit", kind: "err" });
    steps.push({ type: "note", at: "front", kind: "err", lines: ["The request never reached Nginx:", req.networkError] });
    return steps;
  }

  steps.push({ type: "msg", from: "client", to: "front", label: "GET /hit" + (req.canary ? `   X-Canary: ${req.canary}` : "") });
  if (req.status === 429) {
    steps.push({ type: "note", at: "front", kind: "err", lines: ["limit_req: too many requests from this client"] });
    steps.push({ type: "msg", from: "front", to: "client", label: "429 Too Many Requests", kind: "err", res: true });
    return steps;
  }

  const lines = [`split_clients ${req.settings.key}  →  ${req.splitTarget || "(no bucket matched)"}`];
  if (overridden) lines.push(`map: X-Canary "${req.canary}" overrides it  →  ${req.route}`);
  else if (forcedSame) lines.push(`map: X-Canary "${req.canary}" also says ${req.route}`);
  else lines.push(`map: no X-Canary match, $route = ${req.route || "(empty)"}`);
  steps.push({ type: "note", at: "front", lines });

  if (!tries.length) {
    steps.push({ type: "note", at: "front", kind: "err", lines: ["$route is empty, so proxy_pass has nowhere to go"] });
  }
  tries.forEach((t, i) => {
    const side = t.node === "new" ? "new" : "legacy";
    const name = i === 0 ? req.route : "legacy_nginx";
    steps.push({ type: "msg", from: "front", to: t.node, label: `proxy_pass http://${name}  (${t.addr})`, kind: side });
    if (t.status === "200") {
      steps.push({ type: "msg", from: t.node, to: "front", label: "200 OK", kind: side, res: true });
    } else {
      steps.push({ type: "msg", from: t.node, to: "front", label: `${t.status} (upstream not reachable)`, kind: "err", res: true });
      if (i + 1 < tries.length) steps.push({ type: "note", at: "front", kind: "err", lines: ["error_page 502 503 504 = @legacy", "retry on the Legacy side"] });
    }
  });
  const ok = req.status === 200;
  steps.push({
    type: "msg", from: "front", to: "client", res: true,
    label: ok ? `200 OK   served by ${req.servedBy}` : `${req.status} error`,
    kind: ok ? sideClass(req.servedBy) : "err",
  });
  return steps;
}

function renderSequence(req) {
  const X = { client: 76, front: 246, self: 436, new: 626 };
  const W = 700;
  const steps = buildSteps(req);
  let y = 112;
  const body = [];

  steps.forEach((s, i) => {
    const g = svg("g", { class: "seq-step", style: `animation-delay:${i * 0.28}s` });
    if (s.type === "msg") {
      const x1 = X[s.from];
      const x2 = X[s.to];
      const dir = x2 > x1 ? 1 : -1;
      const kind = s.kind && s.kind !== "none" ? " " + s.kind : "";
      g.append(
        svg("text", { class: "seq-text", x: (x1 + x2) / 2, y: y - 7, "text-anchor": "middle" }, s.label),
        svg("line", { class: "seq-line" + kind + (s.res ? " res" : ""), x1, y1: y, x2: x2 - dir * 8, y2: y }),
        svg("path", { class: "seq-arrow" + kind, d: `M${x2} ${y} l${-dir * 10} -5 v10 z` }),
      );
      y += 44;
    } else {
      const h = 14 + s.lines.length * 16;
      const w = 340;
      const x = Math.min(Math.max(X[s.at] - 60, 8), W - w - 8);
      g.append(svg("rect", { class: "seq-note" + (s.kind ? " " + s.kind : ""), x, y: y - 18, width: w, height: h, rx: 6 }));
      s.lines.forEach((line, j) => g.append(svg("text", { class: "seq-text", x: x + 10, y: y + j * 16 }, line)));
      y += h + 24;
    }
    body.push(g);
  });

  const H = y;
  const head = (x, cls, title, sub) => [
    svg("line", { class: "seq-life", x1: x, y1: 68, x2: x, y2: H - 8 }),
    svg("rect", { class: "seq-head " + cls, x: x - 70, y: 26, width: 140, height: 42, rx: 8 }),
    svg("text", { class: "seq-text", x, y: 44, "text-anchor": "middle", "font-weight": "600" }, title),
    svg("text", { class: "seq-sub", x, y: 60, "text-anchor": "middle" }, sub),
  ];

  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `Message sequence for request ${req.n}` },
    svg("rect", { class: "seq-group", x: X.front - 80, y: 18, width: X.self - X.front + 160, height: 58, rx: 10 }),
    svg("text", { class: "seq-sub", x: (X.front + X.self) / 2, y: 12, "text-anchor": "middle" }, "one Nginx process"),
    head(X.client, "", "Client", "your browser"),
    head(X.front, "legacy", "Legacy Nginx", "front door"),
    head(X.self, "legacy", "Legacy Nginx", "itself, :8080"),
    head(X.new, "new", "New Nginx", "separate process, :8082"),
    body,
  );
  $("sequence").replaceChildren(root);
}

function keyValue(req) {
  switch (req.settings.key) {
    case "$request_id": return req.id;
    case "$remote_addr": return req.clientAddr;
    case "$arg_user":
    case "$http_x_user": return req.user;
    default: return null;
  }
}

function renderWhy(req) {
  const items = [];
  const line = $("hashline");
  line.textContent = "";

  if (req.networkError || req.status === 429 || !req.id) {
    items.push(el("li", {}, req.networkError ? "The browser could not reach Nginx: " + req.networkError : `Nginx answered ${req.status} before routing the request.`));
    $("why").replaceChildren(el("ul", {}, items));
    return;
  }

  const value = keyValue(req);
  const ranges = bucketRanges(req.settings.buckets);
  if (value != null && ranges) {
    const hash = murmur2(value);
    const index = ranges.findIndex((r) => hash >= r.lo && hash < r.hi);
    const predicted = index >= 0 ? ranges[index].target : "";
    const position = ((hash / SPACE) * 100).toFixed(2);
    items.push(el("li", {}, "Key ", el("code", {}, req.settings.key), " expanded to ", el("code", {}, value === "" ? '""  (empty)' : value), "."));
    items.push(el("li", {}, "MurmurHash2 of that string is ", el("code", {}, hash.toLocaleString("en-US")), `, which sits ${position}% of the way through the hash space.`));
    items.push(el("li", {}, index >= 0
      ? ["That falls in bucket ", String(index + 1), " (", el("code", {}, `${ranges[index].percent} ${ranges[index].target}`), ")."]
      : "That falls outside every bucket, so $split_target is empty."));
    items.push(el("li", {}, predicted === req.splitTarget
      ? ["Nginx reported ", el("span", { class: "tag " + sideClass(req.splitTarget) }, req.splitTarget || "(empty)"), ": the same answer as this calculation."]
      : ["Nginx reported ", el("code", {}, req.splitTarget || "(empty)"), ", which differs from this calculation (the config may have changed mid-request)."]));
    line.append(renderHashLine(ranges, hash));
  } else {
    items.push(el("li", {}, "Nginx put this request in ", el("code", {}, req.splitTarget || "(no bucket)"), "."));
  }

  if (req.canary && req.route !== req.splitTarget) {
    items.push(el("li", {}, "The ", el("code", {}, "X-Canary: " + req.canary), " header overrode the split and forced ", el("code", {}, req.route), "."));
  }
  const tries = attempts(req);
  if (tries.length > 1) {
    items.push(el("li", {}, `The first upstream answered ${tries[0].status}, so error_page sent the request to the Legacy side instead.`));
  }
  if (!tries.length && req.status >= 500) {
    items.push(el("li", {}, "No bucket matched and there is no catch-all (*), so $route was empty and Nginx returned " + req.status + "."));
  }
  items.push(el("li", {}, "Final answer: ", el("span", { class: "tag " + (req.status === 200 ? sideClass(req.servedBy) : "err") }, req.status === 200 ? "served by " + req.servedBy : "HTTP " + req.status), ` in ${req.ms} ms (as measured by your browser).`));
  $("why").replaceChildren(el("ul", {}, items));
}

function renderHashLine(ranges, hash) {
  const W = 760;
  const pad = 10;
  const scale = (v) => pad + (v / SPACE) * (W - 2 * pad);
  const parts = [];
  let covered = 0;
  for (const r of ranges) {
    if (r.hi <= r.lo) continue;
    const x = scale(r.lo);
    const w = scale(r.hi) - x;
    parts.push(svg("rect", { class: "hl-" + sideClass(r.target), x, y: 26, width: Math.max(w, 1), height: 18 }));
    if (w > 70) parts.push(svg("text", { class: "seq-sub", x: x + w / 2, y: 62, "text-anchor": "middle" }, `${r.percent}  ${r.target}`));
    covered = r.hi;
  }
  if (covered < SPACE) {
    const x = scale(covered);
    parts.push(svg("rect", { class: "hl-none", x, y: 26, width: scale(SPACE) - x, height: 18, opacity: 0.35 }));
    if (scale(SPACE) - x > 70) parts.push(svg("text", { class: "seq-sub", x: (x + scale(SPACE)) / 2, y: 62, "text-anchor": "middle" }, "no bucket"));
  }
  const hx = scale(hash);
  return svg("svg", { viewBox: `0 0 ${W} 70`, role: "img", "aria-label": "Position of this request's hash among the buckets" },
    parts,
    svg("line", { class: "hl-marker", x1: hx, y1: 16, x2: hx, y2: 48 }),
    svg("circle", { class: "hl-dot", cx: hx, cy: 14, r: 4 }),
    svg("text", { class: "seq-sub", x: Math.min(Math.max(hx, 60), W - 60), y: 8, "text-anchor": "middle" }, "this request's hash"),
  );
}

async function loadTrace(req) {
  const pre = $("trace");
  if (!req.id) { pre.textContent = "No request id."; return; }
  pre.textContent = "Loading…";
  try {
    await new Promise((r) => setTimeout(r, 150)); // let Nginx flush the log line
    const data = await api("/api/trace?id=" + encodeURIComponent(req.id));
    if (S.selected !== req) return;
    pre.textContent = data.hops.length
      ? data.hops.map((h) => JSON.stringify(h)).join("\n")
      : "No log lines found (older lines are trimmed).";
  } catch (e) {
    pre.textContent = "Could not load the log lines: " + e.message;
  }
}

/* ---------- distribution and log ---------- */

function barRow(label, cls, count, total, expected) {
  const pct = total ? (count / total) * 100 : 0;
  return el("div", { class: "bar-row" },
    el("div", { class: "bar-label" },
      el("span", {}, el("span", { class: "tag " + cls }, label)),
      el("span", {}, `${count} of ${total} (${pct.toFixed(1)}%)` + (expected != null ? `, expected ${expected.toFixed(1)}%` : "")),
    ),
    el("div", { class: "bar-track" },
      el("div", { class: "bar-fill " + cls, style: `width:${pct}%` }),
      expected != null ? el("div", { class: "bar-expected", style: `left:${expected}%`, title: "expected" }) : null,
    ),
  );
}

function renderStats() {
  const box = $("stats");
  const { total, split, served } = S.stats;
  if (!total) { box.replaceChildren(el("p", { class: "empty" }, "No requests yet.")); return; }

  const expected = {};
  const ranges = bucketRanges(S.server.settings.buckets) || [];
  let covered = 0;
  for (const r of ranges) {
    expected[r.target] = (expected[r.target] || 0) + ((r.hi - r.lo) / SPACE) * 100;
    covered = Math.max(covered, r.hi);
  }
  if (covered < SPACE) expected["(no bucket)"] = ((SPACE - covered) / SPACE) * 100;

  const sticky = S.server.settings.key !== "$request_id";
  const splitKeys = [...new Set([...Object.keys(expected), ...Object.keys(split)])];
  const left = el("div", {},
    el("h4", {}, "What split_clients chose"),
    splitKeys.map((k) => barRow(k, sideClass(k), split[k] || 0, total, expected[k] || 0)),
    sticky ? el("p", { class: "hint" }, `The key is ${S.server.settings.key}, so identical clients always get the same bucket. Counts only approach the expected share across many different key values.`) : null,
  );
  const right = el("div", {},
    el("h4", {}, "Who actually served the request (after X-Canary and fallback)"),
    Object.keys(served).sort().map((k) => barRow(k, k.endsWith("_nginx") ? sideClass(k) : "err", served[k], total, null)),
  );
  box.replaceChildren(el("div", { class: "dist" }, left, right));
}

function renderLog() {
  const tbody = document.querySelector("#log tbody");
  tbody.textContent = "";
  for (const r of S.requests) {
    const tag = (v) => (v ? el("span", { class: "tag " + sideClass(v) }, v) : el("span", { class: "tag none" }, "none"));
    const tries = attempts(r);
    tbody.append(el("tr", { class: r === S.selected ? "selected" : "", onclick: () => select(r) },
      el("td", {}, r.n),
      el("td", { class: "mono" }, r.id ? r.id.slice(0, 12) + "…" : "n/a"),
      el("td", {}, tag(r.splitTarget)),
      el("td", {}, tag(r.route), r.canary && r.route !== r.splitTarget ? " (X-Canary)" : ""),
      el("td", {}, r.servedBy ? tag(r.servedBy) : el("span", { class: "tag err" }, "nobody"), tries.length > 1 ? " (fallback)" : ""),
      el("td", {}, r.status || "failed"),
      el("td", {}, r.ms),
    ));
  }
}

/* ---------- wiring ---------- */

$("editor").addEventListener("input", () => {
  S.dirty = true;
  renderDirty();
  try {
    S.draft = parseEditable($("editor").value);
    $("parse-error").hidden = true;
    renderForm();
  } catch (e) {
    $("parse-error").hidden = false;
    $("parse-error").textContent = e.message;
  }
});
$("key").addEventListener("change", (e) => { S.draft.key = e.target.value; formChanged(true); });
$("add-bucket").addEventListener("click", () => { S.draft.buckets.push({ percent: "10%", target: S.server.targets[0] }); formChanged(true); });
$("add-canary").addEventListener("click", () => { S.draft.canary.push({ match: "beta", target: S.server.targets[0] }); formChanged(true); });
$("apply").addEventListener("click", applyConfig);
$("reset").addEventListener("click", resetConfig);
$("toggle-new").addEventListener("click", toggleNew);
$("clear").addEventListener("click", clearResults);
document.querySelectorAll("[data-send]").forEach((b) => b.addEventListener("click", () => sendBatch(Number(b.dataset.send))));

boot();
