// Dropdowns that look like the rest of the page.
//
// A <select> already looks like our other controls while it's closed
// (style.css), but the list it opens is the browser's own: the system's
// font, grey, square. On a computer this opens our list instead, in the
// page's own style, for every <select> on the page (ones made later too).
// The <select> stays the real control: its value, its options, disabled,
// and the change events the rest of the code listens for are all native.
//
// Phones and tablets keep their own picker (a wheel or a sheet), which is
// made for fingers.
"use strict";

(function () {
  const fine = window.matchMedia ? window.matchMedia("(pointer: fine)") : { matches: true };
  let open = null;  // { select, menu, items, active }

  const usable = (sel) => sel instanceof HTMLSelectElement && !sel.multiple && sel.size <= 1 && fine.matches;

  function close(refocus) {
    if (!open) return;
    const { select, menu } = open;
    menu.remove();
    select.removeAttribute("aria-expanded");
    select.classList.remove("open");
    open = null;
    if (refocus) select.focus({ preventScroll: true });
  }

  function choose(i) {
    const { select } = open;
    const changed = select.selectedIndex !== i;
    select.selectedIndex = i;
    close(true);
    if (changed) {
      select.dispatchEvent(new Event("input", { bubbles: true }));
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }

  function highlight(i, scroll = true) {
    const { items } = open;
    if (i < 0 || i >= items.length) return;
    if (open.active >= 0) items[open.active].classList.remove("active");
    open.active = i;
    items[i].classList.add("active");
    open.menu.setAttribute("aria-activedescendant", items[i].id);
    if (scroll) items[i].scrollIntoView({ block: "nearest" });
  }

  // The next option that can be picked, from i going step (+1 / -1)
  function step(i, by) {
    const { select } = open;
    for (let j = i + by; j >= 0 && j < select.options.length; j += by) {
      if (!select.options[j].disabled) return j;
    }
    return i;
  }

  function place(select, menu) {
    const r = select.getBoundingClientRect();
    const gap = 6, margin = 8;
    menu.style.minWidth = r.width + "px";
    menu.style.left = Math.max(margin, Math.min(r.left, innerWidth - menu.offsetWidth - margin)) + "px";
    const below = innerHeight - r.bottom - gap - margin, above = r.top - gap - margin;
    const up = menu.scrollHeight > below && above > below;
    menu.style.maxHeight = Math.max(120, up ? above : below) + "px";
    menu.style.top = (up ? r.top - gap - Math.min(menu.scrollHeight, above) : r.bottom + gap) + "px";
    menu.classList.toggle("up", up);
  }

  function show(select) {
    close(false);
    const menu = document.createElement("div");
    menu.className = "dropdown-menu";
    menu.setAttribute("role", "listbox");
    menu.tabIndex = -1;
    const label = select.getAttribute("aria-label") || (select.labels && select.labels[0] && select.labels[0].textContent);
    if (label) menu.setAttribute("aria-label", label.trim());
    const items = Array.from(select.options).map((o, i) => {
      const it = document.createElement("div");
      it.className = "dropdown-item";
      it.id = `dropdown-${i}`;
      it.setAttribute("role", "option");
      it.textContent = o.textContent;
      if (o.title) it.title = o.title;
      if (i === select.selectedIndex) { it.classList.add("selected"); it.setAttribute("aria-selected", "true"); }
      if (o.disabled) { it.classList.add("disabled"); it.setAttribute("aria-disabled", "true"); }
      it.addEventListener("mousemove", () => { if (!o.disabled && open && open.active !== i) highlight(i, false); });
      it.addEventListener("click", () => { if (!o.disabled) choose(i); });
      menu.appendChild(it);
      return it;
    });
    menu.addEventListener("keydown", onMenuKey);
    menu.addEventListener("mousedown", (e) => e.preventDefault());  // (keep the focus in the list)
    document.body.appendChild(menu);
    open = { select, menu, items, active: -1, typed: "", typedAt: 0 };
    select.setAttribute("aria-expanded", "true");
    select.classList.add("open");
    place(select, menu);
    highlight(Math.max(0, select.selectedIndex));
    menu.focus({ preventScroll: true });
  }

  function onMenuKey(e) {
    if (!open) return;
    const n = open.select.options.length;
    switch (e.key) {
      case "ArrowDown": highlight(step(open.active, 1)); break;
      case "ArrowUp": highlight(step(open.active, -1)); break;
      case "Home": highlight(step(-1, 1)); break;
      case "End": highlight(step(n, -1)); break;
      case "PageDown": highlight(step(Math.min(n, open.active + 7), -1)); break;
      case "PageUp": highlight(step(Math.max(-1, open.active - 7), 1)); break;
      case "Enter": case " ":
        if (open.active >= 0 && !open.select.options[open.active].disabled) choose(open.active);
        break;
      case "Escape": close(true); break;
      case "Tab": close(true); return;  // (let the focus move on from the select)
      default:
        // Type a few letters to jump to an option
        if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
          const now = performance.now();
          open.typed = (now - open.typedAt < 700 ? open.typed : "") + e.key.toLowerCase();
          open.typedAt = now;
          const opts = Array.from(open.select.options);
          const hit = opts.findIndex((o) => !o.disabled && o.textContent.trim().toLowerCase().startsWith(open.typed));
          if (hit >= 0) highlight(hit);
          break;
        }
        return;
    }
    e.preventDefault();
    e.stopPropagation();
  }

  // Open ours instead of the browser's
  document.addEventListener("mousedown", (e) => {
    const sel = e.target;
    if (open && !open.menu.contains(sel)) {
      const same = sel === open.select;
      close(false);
      if (same) { e.preventDefault(); return; }  // (a second click closes it)
    }
    if (e.button !== 0 || !usable(sel) || sel.disabled) return;
    e.preventDefault();
    sel.focus({ preventScroll: true });
    show(sel);
  }, true);

  document.addEventListener("keydown", (e) => {
    const sel = e.target;
    if (open || !usable(sel) || sel.disabled) return;
    const opens = e.key === " " || e.key === "Enter" || e.key === "F4"
      || (e.altKey && (e.key === "ArrowDown" || e.key === "ArrowUp"));
    if (!opens) return;  // (arrow keys still change it in place, as usual)
    e.preventDefault();
    e.stopPropagation();
    show(sel);
  }, true);

  // Anything that moves the page from under it closes it
  const dismiss = (e) => { if (open && !(e && e.target instanceof Node && open.menu.contains(e.target))) close(false); };
  window.addEventListener("resize", () => dismiss(), true);
  document.addEventListener("scroll", dismiss, true);
  window.addEventListener("blur", () => dismiss());

  window.BonkDropdown = { close: () => close(false), isOpen: () => !!open };
})();
