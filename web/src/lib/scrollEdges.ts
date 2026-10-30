/**
 * Edge cues for tables that scroll sideways, applied to every table in the app.
 *
 * - Long tables get soft white blurred edges on the inside: on the left just past the
 *   pinned (sticky) columns once the table has been scrolled, and on the right while
 *   there are columns still off screen.
 * - Short tables get tall, narrow scroll buttons in the same places instead; they show
 *   while the pointer is over the table and scroll one screenful per click.
 *
 * The cues live in the scroll box's parent, so they stay put while the table scrolls.
 */

/** a table taller than this, or with more rows, counts as long */
const LONG_PX = 460;
const LONG_ROWS = 14;

interface Entry {
  box: HTMLElement;
  host: HTMLElement;
  els: HTMLElement[];
  fadeL: HTMLElement;
  fadeR: HTMLElement;
  btnL: HTMLButtonElement;
  btnR: HTMLButtonElement;
  pinned: number;
  ro: ResizeObserver;
  off: () => void;
}

const entries = new Map<HTMLElement, Entry>();

function scroller(table: HTMLElement): HTMLElement | null {
  for (let el = table.parentElement; el && el !== document.body; el = el.parentElement) {
    if (el.classList.contains("main")) return null;
    const ox = getComputedStyle(el).overflowX;
    if (ox === "auto" || ox === "scroll") return el;
  }
  return null;
}

/** width of the leading sticky columns, so the left cue sits just past them */
function pinnedWidth(box: HTMLElement) {
  const row = box.querySelector("table tr");
  if (!row) return 0;
  let w = 0;
  for (const cell of Array.from(row.children) as HTMLElement[]) {
    // header cells all stick to the top; only those pinned to the left count
    const cs = getComputedStyle(cell);
    if (cs.position !== "sticky" || cs.left === "auto") break;
    w += cell.offsetWidth;
  }
  return w < box.clientWidth / 2 ? w : 0;
}

function make(cls: string, tag: "div" | "button" = "div") {
  const el = document.createElement(tag);
  el.className = cls;
  el.setAttribute("aria-hidden", "true");
  return el;
}

function layout(e: Entry) {
  const { box } = e;
  const x = box.offsetLeft + box.clientLeft;
  const y = box.offsetTop + box.clientTop;
  const w = box.clientWidth;
  const h = box.clientHeight;
  e.pinned = pinnedWidth(box);
  const wide = box.scrollWidth - w > 1;
  const table = box.querySelector("table");
  const long = h > LONG_PX || (table?.rows.length ?? 0) > LONG_ROWS;
  for (const el of e.els) {
    el.style.top = `${y}px`;
    el.style.height = `${h}px`;
    el.classList.toggle("off", !wide);
  }
  e.fadeL.style.left = e.btnL.style.left = `${x + e.pinned}px`;
  e.fadeR.style.left = e.btnR.style.left = `${x + w}px`;
  e.host.classList.toggle("sx-long", long);
  update(e);
}

function update(e: Entry) {
  const { box } = e;
  const left = box.scrollLeft > 1;
  const right = box.scrollLeft + box.clientWidth < box.scrollWidth - 1;
  e.fadeL.classList.toggle("on", left);
  e.btnL.classList.toggle("on", left);
  e.fadeR.classList.toggle("on", right);
  e.btnR.classList.toggle("on", right);
}

function attach(box: HTMLElement) {
  const host = box.parentElement;
  if (!host) return;
  if (getComputedStyle(host).position === "static") host.style.position = "relative";
  host.classList.add("sx-host");

  const fadeL = make("sx-fade l");
  const fadeR = make("sx-fade r");
  const btnL = make("sx-btn l", "button") as HTMLButtonElement;
  const btnR = make("sx-btn r", "button") as HTMLButtonElement;
  btnL.innerHTML = '<i class="codicon codicon-chevron-left"></i>';
  btnR.innerHTML = '<i class="codicon codicon-chevron-right"></i>';
  btnL.tabIndex = btnR.tabIndex = -1;
  const els: HTMLElement[] = [fadeL, fadeR, btnL, btnR];
  host.append(...els);

  const step = (dir: number) => () => box.scrollBy({ left: dir * Math.max(120, (box.clientWidth - entry.pinned) * 0.8), behavior: "smooth" });
  btnL.addEventListener("click", step(-1));
  btnR.addEventListener("click", step(1));

  // the buttons show while the pointer is over the table or over a button
  const enter = () => host.classList.add("sx-hover");
  const leave = (ev: MouseEvent) => {
    const to = ev.relatedTarget as Node | null;
    if (to && (box.contains(to) || els.includes(to as HTMLElement) || btnL.contains(to) || btnR.contains(to))) return;
    host.classList.remove("sx-hover");
  };
  for (const el of [box, btnL, btnR]) {
    el.addEventListener("mouseenter", enter);
    el.addEventListener("mouseleave", leave);
  }
  const onScroll = () => update(entry);
  box.addEventListener("scroll", onScroll, { passive: true });

  const ro = new ResizeObserver(() => layout(entry));
  ro.observe(box);
  ro.observe(host);
  const table = box.querySelector("table");
  if (table) ro.observe(table);

  const entry: Entry = {
    box, host, els, fadeL, fadeR, btnL, btnR, pinned: 0, ro,
    off: () => {
      box.removeEventListener("scroll", onScroll);
      for (const el of [box, btnL, btnR]) {
        el.removeEventListener("mouseenter", enter);
        el.removeEventListener("mouseleave", leave);
      }
    },
  };
  entries.set(box, entry);
  layout(entry);
}

function detach(e: Entry) {
  e.ro.disconnect();
  e.off();
  e.els.forEach((el) => el.remove());
  if (e.host.isConnected && ![...entries.values()].some((o) => o !== e && o.host === e.host)) e.host.classList.remove("sx-host", "sx-long", "sx-hover");
  entries.delete(e.box);
}

function scan() {
  for (const e of entries.values()) {
    if (!e.box.isConnected || e.box.parentElement !== e.host || !e.box.querySelector("table")) detach(e);
  }
  for (const table of Array.from(document.querySelectorAll<HTMLElement>("table"))) {
    const box = scroller(table);
    if (box && !entries.has(box)) attach(box);
  }
  for (const e of entries.values()) layout(e);
}

let started = false;

/** Watches the page and keeps every horizontally scrolling table fitted with its cues. */
export function installScrollEdges() {
  if (started || typeof ResizeObserver === "undefined") return;
  started = true;
  let queued = false;
  const queue = () => {
    if (queued) return;
    queued = true;
    // live prices re-render cells often, so rescans are spaced out
    setTimeout(() => requestAnimationFrame(() => { queued = false; scan(); }), 120);
  };
  new MutationObserver((records) => {
    // ignore the cues' own class and style changes
    if (records.every((r) => r.type === "childList" && [...r.addedNodes, ...r.removedNodes].every((n) => n instanceof HTMLElement && (n.classList.contains("sx-fade") || n.classList.contains("sx-btn"))))) return;
    queue();
  }).observe(document.body, { childList: true, subtree: true });
  window.addEventListener("resize", queue);
  queue();
}
