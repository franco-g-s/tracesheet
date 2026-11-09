// Tracesheet: two small enhancements to a page that works without them.
// 1. "Last 10 years" hides the older year columns. All years show by default and in print.
// 2. Selecting a figure opens its trail: every report line and observation it was computed
//    from, each linking to its entry in Sources. Without the script, a figure links to its
//    first source and the numbers of the others are shown beside it.
(function () {
  "use strict";

  var body = document.body;
  // With the script running, a figure's further sources are reached through its trail.
  document.documentElement.classList.remove("no-js");

  // ---- Years shown ----
  var toggle = document.querySelector(".span-toggle");
  if (toggle) {
    toggle.hidden = false;
    toggle.addEventListener("click", function (event) {
      var button = event.target.closest("button[data-span]");
      if (!button) return;
      var recent = button.dataset.span === "recent";
      body.classList.toggle("recent", recent);
      toggle.querySelectorAll("button").forEach(function (b) {
        b.setAttribute("aria-pressed", String(b === button));
      });
    });
  }

  // ---- The trail ----
  var trail = document.getElementById("trail");
  if (!trail || typeof trail.showPopover !== "function") return;
  var title = trail.querySelector(".trail-title");
  var value = trail.querySelector(".trail-value");
  var formula = trail.querySelector(".trail-formula");
  var list = trail.querySelector(".trail-list");
  var picked = null;

  function text(node, selector) {
    var found = node && node.querySelector(selector);
    return found ? found.textContent.trim() : "";
  }

  function columnName(cell) {
    var table = cell.closest("table");
    var header = table.tHead && table.tHead.rows[0].cells[cell.cellIndex];
    return header ? header.textContent.trim() : "";
  }

  function element(tag, className, content) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (content) node.textContent = content;
    return node;
  }

  function sourceItem(id) {
    var row = document.getElementById(id);
    var item = element("li");
    var link = element("a");
    link.href = "#" + id;
    if (!row) {
      link.textContent = id;
      item.appendChild(link);
      return item;
    }
    var detail = row.dataset.fy ? "Fiscal " + row.dataset.fy + ", " + row.dataset.doc : row.dataset.doc;
    link.appendChild(element("span", "tn", text(row, ".n")));
    link.appendChild(element("span", "tp", text(row, ".pg")));
    var quote = element("span", "tq", text(row, ".q"));
    quote.appendChild(element("span", "td", detail));
    link.appendChild(quote);
    item.appendChild(link);
    return item;
  }

  function close() {
    if (picked) picked.classList.remove("picked");
    picked = null;
    if (trail.matches(":popover-open")) trail.hidePopover();
  }

  function open(cell) {
    if (picked) picked.classList.remove("picked");
    picked = cell;
    cell.classList.add("picked");
    var row = cell.parentElement;
    var unit = text(row, "td.unit");
    var column = columnName(cell);
    title.textContent = text(row, ".label") + (column ? ", " + column : "");
    var nm = cell.querySelector(".nm");
    if (nm) {
      value.textContent = "n/m: " + nm.title;
    } else {
      var shown = cell.querySelector(".fig").textContent;
      value.textContent = unit === "%" || unit === "\u00d7" ? shown + unit : unit ? shown + " " + unit : shown;
    }
    formula.textContent = text(row, ".formula");
    list.replaceChildren();
    cell.querySelectorAll("a[href^='#src-']").forEach(function (a) {
      list.appendChild(sourceItem(a.getAttribute("href").slice(1)));
    });
    if (!trail.matches(":popover-open")) trail.showPopover();
  }

  document.addEventListener("click", function (event) {
    if (event.target.closest(".trail-close")) {
      close();
      return;
    }
    var hit = event.target.closest(".grid .fig, .grid .nm");
    if (hit) {
      if (event.metaKey || event.ctrlKey || event.shiftKey) return;
      event.preventDefault();
      var cell = hit.closest("td");
      if (cell === picked) close();
      else open(cell);
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      close();
      return;
    }
    if (event.key === "Enter" && event.target.matches && event.target.matches(".grid .nm")) {
      open(event.target.closest("td"));
    }
  });
})();
