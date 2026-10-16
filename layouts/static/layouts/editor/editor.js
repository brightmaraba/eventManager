const SVG = "http://www.w3.org/2000/svg";
const root = document.querySelector("[data-editor]");
const eventId = root.dataset.eventId;
const canEdit = root.dataset.canEdit === "yes";
const canvas = document.querySelector("#room-canvas");
const ticketList = document.querySelector("#ticket-list");
const search = document.querySelector("#ticket-search");
const conflict = document.querySelector("#conflict");
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const SEAT_RADIUS = 0.25;
// Pixels per metre below which seat numbers, status marks and table labels are hidden.
const SEAT_NUMBER_PPM = 30;
const SEAT_MARK_PPM = 14;
const TABLE_LABEL_PPM = 9;
let state = null;
let view = null;
let selectedTicket = null;
let selectedTable = null;
const undo = [];

function headers(json) {
  const value = { Accept: "application/json", "X-CSRFToken": csrf };
  if (json) value["Content-Type"] = "application/json";
  return value;
}

async function load() {
  root.setAttribute("aria-busy", "true");
  const response = await fetch(`/events/${eventId}/layout.json`, { headers: headers(false) });
  state = await response.json();
  conflict.hidden = true;
  render();
}

function statusOf(seat) {
  if (seat.availability === "blocked") return "blocked";
  if (!seat.occupancy) return "available";
  if (seat.occupancy.checked_in) return "checked_in";
  return seat.occupancy.kind === "hold" ? "held" : "assigned";
}

function statusText(seat) {
  return { available: "available", held: "held", assigned: "assigned", blocked: "blocked", checked_in: "checked in" }[statusOf(seat)];
}

function seatDescription(table, seat) {
  const occupant = seat.occupancy && seat.occupancy.label ? ` — ${seat.occupancy.label}` : "";
  return `${table.label} seat ${seat.label}, ${statusText(seat)}${occupant}`;
}

function el(name, attributes = {}) {
  const node = document.createElementNS(SVG, name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  return node;
}

// Status is shown by colour and by a mark on the chair, so it never needs text beside the seat.
function statusMark(status, x, y) {
  const r = SEAT_RADIUS;
  if (status === "blocked") {
    const d = r * 0.7;
    return el("line", { class: "seat-mark", x1: x - d, y1: y + d, x2: x + d, y2: y - d });
  }
  if (status === "assigned") return el("circle", { class: "seat-mark", cx: x, cy: y, r: r * 0.78, fill: "none" });
  if (status === "checked_in") {
    const badge = el("g", { class: "seat-badge" });
    const bx = x + r * 0.75;
    const by = y - r * 0.75;
    badge.append(el("circle", { cx: bx, cy: by, r: r * 0.45 }));
    badge.append(el("path", { d: `M${bx - r * 0.22} ${by} l${r * 0.15} ${r * 0.16} l${r * 0.28} ${-r * 0.3}` }));
    return badge;
  }
  return null;
}

function render() {
  canvas.replaceChildren();
  const viewport = el("g");
  state.tables.forEach((table) => {
    const group = el("g", { role: "group", "aria-label": `Table ${table.label}` });
    group.dataset.tableId = table.id;
    const shape = el(table.shape === "round" ? "circle" : "rect", { class: "table-shape" });
    if (table.shape === "round") {
      shape.setAttribute("cx", table.x);
      shape.setAttribute("cy", table.y);
      shape.setAttribute("r", table.width_m / 2);
    } else {
      shape.setAttribute("x", table.x - table.width_m / 2);
      shape.setAttribute("y", table.y - table.height_m / 2);
      shape.setAttribute("width", table.width_m);
      shape.setAttribute("height", table.height_m);
      shape.setAttribute("transform", `rotate(${table.rotation} ${table.x} ${table.y})`);
    }
    group.append(shape);
    const label = el("text", { class: "table-label", x: table.x, y: table.y, "aria-hidden": "true" });
    label.style.fontSize = `${Math.min(0.45, Math.min(table.width_m, table.height_m) * 0.3)}px`;
    label.textContent = table.label;
    group.append(label);
    table.seats.forEach((seat) => {
      const point = world(table, seat.rel_x, seat.rel_y);
      const status = statusOf(seat);
      const chair = el("circle", {
        class: `seat ${status}`, cx: point.x, cy: point.y, r: SEAT_RADIUS,
        tabindex: "0", role: "button", "aria-label": seatDescription(table, seat),
      });
      chair.dataset.seatId = seat.id;
      const tooltip = el("title");
      tooltip.textContent = seatDescription(table, seat);
      chair.append(tooltip);
      group.append(chair);
      const mark = statusMark(status, point.x, point.y);
      if (mark) {
        mark.setAttribute("aria-hidden", "true");
        group.append(mark);
      }
      const number = el("text", { class: "seat-number", x: point.x, y: point.y, "aria-hidden": "true" });
      number.textContent = seat.label;
      group.append(number);
    });
    group.addEventListener("keydown", (event) => onTableKey(event, table));
    group.addEventListener("pointerdown", (event) => startDrag(event, table));
    viewport.append(group);
  });
  canvas.append(viewport);
  if (!view) view = tablesBox() || roomBox();
  applyView();
  renderTickets();
  root.setAttribute("aria-busy", "false");
}

function world(table, relX, relY) {
  const radians = table.rotation * Math.PI / 180;
  return {
    x: table.x + relX * Math.cos(radians) - relY * Math.sin(radians),
    y: table.y + relX * Math.sin(radians) + relY * Math.cos(radians),
  };
}

function roomBox() {
  return { x: 0, y: 0, w: state.room.width_m, h: state.room.height_m };
}

function tablesBox() {
  if (!state.tables.length) return null;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  state.tables.forEach((table) => {
    const reach = Math.max(table.width_m, table.height_m) / 2;
    const points = [{ x: table.x - reach, y: table.y - reach }, { x: table.x + reach, y: table.y + reach }];
    table.seats.forEach((seat) => points.push(world(table, seat.rel_x, seat.rel_y)));
    points.forEach((point) => {
      minX = Math.min(minX, point.x - SEAT_RADIUS);
      minY = Math.min(minY, point.y - SEAT_RADIUS);
      maxX = Math.max(maxX, point.x + SEAT_RADIUS);
      maxY = Math.max(maxY, point.y + SEAT_RADIUS);
    });
  });
  const pad = 1;
  return { x: minX - pad, y: minY - pad, w: maxX - minX + pad * 2, h: maxY - minY + pad * 2 };
}

// Match the box to the canvas aspect ratio so the viewBox maps 1:1 onto the element.
function fitAspect(box) {
  const aspect = canvas.clientWidth / Math.max(1, canvas.clientHeight);
  let { x, y, w, h } = box;
  if (w / h < aspect) {
    const width = h * aspect;
    x -= (width - w) / 2;
    w = width;
  } else {
    const height = w / aspect;
    y -= (height - h) / 2;
    h = height;
  }
  return { x, y, w, h };
}

function applyView() {
  view = fitAspect(view);
  canvas.setAttribute("viewBox", `${view.x} ${view.y} ${view.w} ${view.h}`);
  const ppm = canvas.clientWidth / view.w;
  canvas.dataset.detail = ppm >= SEAT_NUMBER_PPM ? "full" : ppm >= SEAT_MARK_PPM ? "marks" : ppm >= TABLE_LABEL_PPM ? "tables" : "low";
}

function zoom(factor, anchor) {
  const room = roomBox();
  const maxWidth = Math.max(room.w, room.h * canvas.clientWidth / Math.max(1, canvas.clientHeight)) * 1.5;
  const width = Math.min(maxWidth, Math.max(2, view.w / factor));
  const ratio = width / view.w;
  const center = anchor || { x: view.x + view.w / 2, y: view.y + view.h / 2 };
  view = { x: center.x - (center.x - view.x) * ratio, y: center.y - (center.y - view.y) * ratio, w: width, h: view.h * ratio };
  applyView();
}

function toWorld(clientX, clientY) {
  const point = new DOMPoint(clientX, clientY).matrixTransform(canvas.getScreenCTM().inverse());
  return { x: point.x, y: point.y };
}

function renderTickets() {
  const query = search.value.trim().toLowerCase();
  ticketList.replaceChildren();
  state.unassigned.filter((ticket) => `${ticket.display_name} ${ticket.party_name} ${ticket.email}`.toLowerCase().includes(query)).forEach((ticket) => {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    button.textContent = `${ticket.display_name} — ${ticket.party_name || ticket.email}`;
    button.setAttribute("aria-selected", selectedTicket === ticket.ticket_id ? "true" : "false");
    button.addEventListener("click", () => {
      selectedTicket = ticket.ticket_id;
      renderTickets();
    });
    item.append(button);
    ticketList.append(item);
  });
}

async function mutate(url, body) {
  if (!canEdit) return;
  body.expected_version = state.layout_revision;
  body.idempotency_key = crypto.randomUUID();
  const response = await fetch(url, { method: "POST", headers: headers(true), body: JSON.stringify(body) });
  const data = await response.json();
  if (response.status === 409) {
    conflict.hidden = false;
    return;
  }
  if (data.layout) state = data.layout;
  else if (data.layout_revision) await load();
  else state = data.tables ? data : state;
  if (data.layout_revision && data.tables) state = data;
  render();
}

async function moveTable(table, x, y, rotation, remember) {
  if (remember) undo.push({ id: table.id, x: table.x, y: table.y, rotation: table.rotation });
  await fetch(`/events/${eventId}/layout.json`, {
    method: "PATCH",
    headers: headers(true),
    body: JSON.stringify({
      expected_version: state.layout_revision,
      idempotency_key: crypto.randomUUID(),
      tables: [{ id: table.id, x, y, rotation }],
    }),
  }).then(async (response) => {
    const data = await response.json();
    if (response.status === 409) {
      conflict.hidden = false;
      render();
      return;
    }
    state = data;
    render();
  });
}

function startDrag(event, table) {
  if (!canEdit || event.target.dataset.seatId) {
    if (event.target.dataset.seatId && selectedTicket) {
      mutate(`/events/${eventId}/assignments/`, { ticket_id: selectedTicket, seat_id: event.target.dataset.seatId });
    }
    return;
  }
  event.preventDefault();
  event.stopPropagation();
  selectedTable = table;
  const start = toWorld(event.clientX, event.clientY);
  const origin = { x: table.x, y: table.y };
  const group = event.currentTarget;
  let finished = false;
  function move(pointer) {
    const current = toWorld(pointer.clientX, pointer.clientY);
    table.x = Math.round((origin.x + current.x - start.x) * 4) / 4;
    table.y = Math.round((origin.y + current.y - start.y) * 4) / 4;
    group.setAttribute("transform", `translate(${table.x - origin.x} ${table.y - origin.y})`);
  }
  function up() {
    if (finished) return;
    finished = true;
    canvas.removeEventListener("pointermove", move);
    canvas.removeEventListener("pointerup", up);
    canvas.removeEventListener("pointercancel", up);
    if (table.x === origin.x && table.y === origin.y) return;
    undo.push({ id: table.id, x: origin.x, y: origin.y, rotation: table.rotation });
    moveTable(table, table.x, table.y, table.rotation, false);
  }
  canvas.addEventListener("pointermove", move);
  canvas.addEventListener("pointerup", up);
  canvas.addEventListener("pointercancel", up);
}

// Dragging empty canvas pans the view.
canvas.addEventListener("pointerdown", (event) => {
  if (event.defaultPrevented || event.button !== 0 || !view) return;
  const start = { clientX: event.clientX, clientY: event.clientY, x: view.x, y: view.y };
  const metresPerPixel = view.w / canvas.clientWidth;
  canvas.setPointerCapture(event.pointerId);
  function move(pointer) {
    view.x = start.x - (pointer.clientX - start.clientX) * metresPerPixel;
    view.y = start.y - (pointer.clientY - start.clientY) * metresPerPixel;
    applyView();
  }
  function up() {
    canvas.removeEventListener("pointermove", move);
    canvas.removeEventListener("pointerup", up);
    canvas.removeEventListener("pointercancel", up);
  }
  canvas.addEventListener("pointermove", move);
  canvas.addEventListener("pointerup", up);
  canvas.addEventListener("pointercancel", up);
});

canvas.addEventListener("wheel", (event) => {
  if (!view) return;
  event.preventDefault();
  zoom(event.deltaY < 0 ? 1.15 : 1 / 1.15, toWorld(event.clientX, event.clientY));
}, { passive: false });

canvas.addEventListener("keydown", (event) => {
  if (!view) return;
  if (event.key === "+" || event.key === "=") zoom(1.25);
  else if (event.key === "-") zoom(1 / 1.25);
  else return;
  event.preventDefault();
});

function onTableKey(event, table) {
  const step = 0.25;
  const moves = { ArrowUp: [0, -step], ArrowDown: [0, step], ArrowLeft: [-step, 0], ArrowRight: [step, 0] };
  if (moves[event.key] && canEdit) {
    event.preventDefault();
    const [dx, dy] = moves[event.key];
    moveTable(table, table.x + dx, table.y + dy, table.rotation, true);
  }
}

search.addEventListener("input", renderTickets);
document.querySelector("#zoom-in").addEventListener("click", () => zoom(1.25));
document.querySelector("#zoom-out").addEventListener("click", () => zoom(1 / 1.25));
document.querySelector("#fit-tables").addEventListener("click", () => { view = tablesBox() || roomBox(); applyView(); });
document.querySelector("#fit-room").addEventListener("click", () => { view = roomBox(); applyView(); });
window.addEventListener("resize", () => { if (view) applyView(); });
document.querySelector("#refresh-layout").addEventListener("click", load);
document.querySelector("#undo").addEventListener("click", async () => {
  const previous = undo.pop();
  if (previous) await moveTable(previous, previous.x, previous.y, previous.rotation, false);
});
document.querySelector("#add-table")?.addEventListener("click", () => {
  const form = document.querySelector("#add-table").form;
  form.idempotency_key.value = crypto.randomUUID();
});
load();
