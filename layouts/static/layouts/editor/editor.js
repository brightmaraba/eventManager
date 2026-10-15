const root = document.querySelector("[data-editor]");
const eventId = root.dataset.eventId;
const canEdit = root.dataset.canEdit === "yes";
const canvas = document.querySelector("#room-canvas");
const ticketList = document.querySelector("#ticket-list");
const search = document.querySelector("#ticket-search");
const conflict = document.querySelector("#conflict");
const csrf = document.querySelector('meta[name="csrf-token"]').content;
let state = null;
let scale = 1;
let selectedTicket = null;
let selectedTable = null;
const undo = [];

function headers(json) {
  const value = { Accept: "application/json", "X-CSRFToken": csrf };
  if (json) value["Content-Type"] = "application/json";
  return value;
}

async function load() {
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

function render() {
  const room = state.room;
  canvas.setAttribute("viewBox", `0 0 ${room.width_m} ${room.height_m}`);
  canvas.replaceChildren();
  const viewport = document.createElementNS("http://www.w3.org/2000/svg", "g");
  viewport.setAttribute("transform", `scale(${scale})`);
  const detail = scale >= 0.55;
  state.tables.forEach((table) => {
    const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
    group.setAttribute("tabindex", "0");
    group.setAttribute("role", "button");
    group.setAttribute("aria-label", `Table ${table.label}`);
    group.dataset.tableId = table.id;
    const shape = document.createElementNS("http://www.w3.org/2000/svg", table.shape === "round" ? "circle" : "rect");
    shape.setAttribute("class", "table-shape");
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
    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("class", "table-label");
    label.setAttribute("x", table.x);
    label.setAttribute("y", table.y);
    label.textContent = table.label;
    group.append(label);
    table.seats.forEach((seat) => {
      const point = world(table, seat.rel_x, seat.rel_y);
      const chair = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      const status = statusOf(seat);
      chair.setAttribute("class", `seat ${status}`);
      chair.setAttribute("cx", point.x);
      chair.setAttribute("cy", point.y);
      chair.setAttribute("r", detail ? 0.25 : 0.18);
      chair.setAttribute("tabindex", "0");
      chair.setAttribute("role", "button");
      chair.setAttribute("aria-label", `${table.label} seat ${seat.label}, ${statusText(seat)}`);
      chair.dataset.seatId = seat.id;
      group.append(chair);
      if (detail) {
        const seatLabel = document.createElementNS("http://www.w3.org/2000/svg", "text");
        seatLabel.setAttribute("class", "seat-label");
        seatLabel.setAttribute("x", point.x + 0.28);
        seatLabel.setAttribute("y", point.y);
        seatLabel.textContent = `${seat.label} ${statusText(seat)}`;
        group.append(seatLabel);
      }
    });
    group.addEventListener("keydown", (event) => onTableKey(event, table));
    group.addEventListener("pointerdown", (event) => startDrag(event, table));
    viewport.append(group);
  });
  canvas.append(viewport);
  renderTickets();
}

function world(table, relX, relY) {
  const radians = table.rotation * Math.PI / 180;
  return {
    x: table.x + relX * Math.cos(radians) - relY * Math.sin(radians),
    y: table.y + relX * Math.sin(radians) + relY * Math.cos(radians),
  };
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
  selectedTable = table;
  const start = event;
  const origin = { x: table.x, y: table.y };
  function move(pointer) {
    const rect = canvas.getBoundingClientRect();
    const dx = (pointer.clientX - start.clientX) / rect.width * state.room.width_m;
    const dy = (pointer.clientY - start.clientY) / rect.height * state.room.height_m;
    table.x = Math.round((origin.x + dx) * 4) / 4;
    table.y = Math.round((origin.y + dy) * 4) / 4;
    render();
  }
  function up() {
    canvas.removeEventListener("pointermove", move);
    moveTable(table, table.x, table.y, table.rotation, true);
  }
  canvas.addEventListener("pointermove", move);
  canvas.addEventListener("pointerup", up, { once: true });
}

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
document.querySelector("#zoom-in").addEventListener("click", () => { scale = Math.min(2.5, scale + 0.15); render(); });
document.querySelector("#zoom-out").addEventListener("click", () => { scale = Math.max(0.35, scale - 0.15); render(); });
document.querySelector("#fit-room").addEventListener("click", () => { scale = 1; render(); });
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
