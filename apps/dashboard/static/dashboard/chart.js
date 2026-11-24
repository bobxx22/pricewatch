// Crosshair and tooltip for the server-rendered price charts.
// The pointer snaps to the nearest recorded change; arrow keys walk the changes too.
(() => {
  "use strict";

  for (const figure of document.querySelectorAll("[data-chart]")) {
    setUp(figure);
  }

  function setUp(figure) {
    const svg = figure.querySelector("svg");
    const data = figure.querySelector("script[type='application/json']");
    const tooltip = figure.querySelector(".chart__tooltip");
    if (!svg || !data || !tooltip) return;

    const points = JSON.parse(data.textContent);
    if (!points.length) return;
    const crosshair = svg.querySelector(".chart__crosshair");
    const focusDot = svg.querySelector(".chart__focus");
    const viewWidth = svg.viewBox.baseVal.width;
    let current = points.length - 1;

    function show(index) {
      current = index;
      const point = points[index];
      crosshair.setAttribute("x1", point.x);
      crosshair.setAttribute("x2", point.x);
      focusDot.style.display = point.y === null ? "none" : "";
      if (point.y !== null) {
        focusDot.setAttribute("cx", point.x);
        focusDot.setAttribute("cy", point.y);
      }

      // Shop data is untrusted: build the tooltip with textContent only.
      const value = document.createElement("strong");
      value.textContent = point.price;
      const details = document.createElement("span");
      details.textContent = `${point.date}, ${point.stock}`;
      tooltip.replaceChildren(value, details);

      const scale = svg.getBoundingClientRect().width / viewWidth;
      const anchorY = point.y === null ? svg.viewBox.baseVal.height / 2 : point.y;
      const half = tooltip.offsetWidth / 2 || 60;
      const left = Math.min(Math.max(point.x * scale, half), figure.clientWidth - half);
      tooltip.style.left = `${left}px`;
      tooltip.style.top = `${anchorY * scale}px`;
      figure.classList.add("is-active");
    }

    function hide() {
      figure.classList.remove("is-active");
    }

    function nearest(clientX) {
      const box = svg.getBoundingClientRect();
      const x = ((clientX - box.left) / box.width) * viewWidth;
      let best = 0;
      for (let i = 1; i < points.length; i += 1) {
        if (Math.abs(points[i].x - x) < Math.abs(points[best].x - x)) best = i;
      }
      return best;
    }

    svg.addEventListener("pointermove", (event) => show(nearest(event.clientX)));
    svg.addEventListener("pointerleave", () => {
      if (document.activeElement !== svg) hide();
    });
    svg.addEventListener("focus", () => show(current));
    svg.addEventListener("blur", hide);
    svg.addEventListener("keydown", (event) => {
      const moves = {
        ArrowLeft: current - 1,
        ArrowRight: current + 1,
        Home: 0,
        End: points.length - 1,
      };
      if (!(event.key in moves)) return;
      event.preventDefault();
      show(Math.min(Math.max(moves[event.key], 0), points.length - 1));
    });
  }
})();
