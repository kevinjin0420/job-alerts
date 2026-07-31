import {
  ArcElement,
  CategoryScale,
  Chart,
  Legend,
  LineElement,
  LinearScale,
  PointElement,
  Tooltip,
  type Plugin,
} from "chart.js";

import { chartPalette } from "../../lib/chartPalette";

/** Chart.js ships hover highlighting but no crosshair line - draw a hairline at
 * the active point's x on every redraw. interaction.mode "index" already finds it. */
const crosshairPlugin: Plugin = {
  id: "crosshair",
  afterDatasetsDraw(chart) {
    const active = chart.getActiveElements();
    const first = active[0];
    if (first === undefined) {
      return;
    }
    const { ctx, chartArea } = chart;
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(first.element.x, chartArea.top);
    ctx.lineTo(first.element.x, chartArea.bottom);
    ctx.lineWidth = 1;
    ctx.strokeStyle = chartPalette(document.documentElement.classList.contains("dark")).baseline;
    ctx.stroke();
    ctx.restore();
  },
};

Chart.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  ArcElement,
  Tooltip,
  Legend,
  crosshairPlugin,
);
