// Results page: load the classification + lap times from our API, then draw the table and chart.
const root = document.getElementById('results');
const table = document.getElementById('results-table');
const chartSlot = document.getElementById('chart-slot');

const tableHeader = table.firstElementChild.outerHTML;
const loadingTable = table.innerHTML;
const loadingChart = chartSlot.innerHTML;
let chart = null;

function formatLapTime(seconds) {
  if (!seconds || seconds <= 0) return '—';
  const m = Math.floor(seconds / 60);
  const s = (seconds % 60).toFixed(3).padStart(6, '0');
  return m > 0 ? `${m}:${s}` : `${s}s`;
}

function rowHtml(r) {
  const colour = r.team_colour ? `#${escapeHtml(r.team_colour)}` : '#3A4455';
  return `
    <div class="grid grid-cols-[3rem_1fr_1fr_auto] items-center gap-4 px-5 py-3.5 border-b border-[rgba(255,255,255,0.05)] last:border-0 hover:bg-white/[0.025] transition-colors duration-100">
      <span class="font-mono text-base font-medium tabular-nums text-right ${r.position <= 3 ? 'text-[#E8002D]' : 'text-[#8A95A3]'}">${r.position}</span>
      <div class="flex items-center gap-2.5 min-w-0">
        <span class="shrink-0 w-[3px] h-5 rounded-full" style="background: ${colour}"></span>
        <span class="text-[#F0F2F5] font-medium text-sm truncate">${escapeHtml(r.full_name)}</span>
      </div>
      <span class="text-[#8A95A3] text-sm truncate hidden sm:block">${escapeHtml(r.team_name)}</span>
      <span class="font-mono text-sm tabular-nums text-[#8A95A3]">${r.best_lap !== null ? formatLapTime(r.best_lap) : '—'}</span>
    </div>`;
}

function errorHtml(message) {
  return `
    <div class="flex flex-col items-center gap-4 py-12 text-center">
      <div class="w-10 h-10 rounded-full bg-[#E8002D]/10 flex items-center justify-center">
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M10 6v4m0 3h.01M10 18a8 8 0 1 0 0-16 8 8 0 0 0 0 16z" stroke="#E8002D" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" /></svg>
      </div>
      <div>
        <p class="text-[#F0F2F5] font-medium text-sm mb-1">Something went wrong</p>
        <p class="text-[#8A95A3] text-xs max-w-xs">${escapeHtml(message)}</p>
      </div>
      <button type="button" data-retry class="inline-flex items-center justify-center gap-2 font-display font-semibold tracking-wide uppercase text-sm transition-all duration-150 rounded-lg cursor-pointer text-[#8A95A3] hover:text-[#F0F2F5] px-3 py-2 hover:bg-white/5 active:scale-[0.97] border border-[rgba(255,255,255,0.08)]">Try again</button>
    </div>`;
}

function chartCardHtml(drivers) {
  const legend = drivers.map((d) => `
    <div class="flex items-center gap-2">
      <span class="w-6 h-[2px] rounded-full shrink-0" style="background: #${escapeHtml(d.colour || '3A4455')}"></span>
      <span class="font-mono text-xs text-[#8A95A3] uppercase tracking-wider">${escapeHtml(d.acronym)}</span>
    </div>`).join('');
  return `
    <div class="bg-[#141920] border border-[rgba(255,255,255,0.08)] rounded-lg p-5 flex flex-col gap-4">
      <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <h2 class="font-display font-semibold text-lg uppercase tracking-wide text-[#F0F2F5]">Lap Times — Top 5</h2>
        <div class="flex flex-wrap gap-x-5 gap-y-2">${legend}</div>
      </div>
      <div class="h-64 relative"><canvas></canvas><div data-tooltip class="pointer-events-none absolute z-10 hidden"></div></div>
    </div>`;
}

// ── Chart ─────────────────────────────────────────────────────────────────────
// Chart.js, configured to reproduce the Recharts look: same axis ranges and tick
// choices, dashed horizontal grid, hover cursor, and a left-to-right reveal.

const AXIS_COLOR = '#4A5568';
const AXIS_FONT = { size: 10, family: 'JetBrains Mono, monospace' };
const CHAR_WIDTH = 6;    // width of one 10px JetBrains Mono character
const MIN_TICK_GAP = 5;
const X_AXIS_HEIGHT = 30;
const Y_AXIS_WIDTH = 58;

// Y ticks: a "nice" step from the domain minimum, ending exactly on the domain maximum
function yTicks(min, max, count = 5) {
  const rough = (max - min) / (count - 1);
  const digits = Math.floor(Math.log10(rough)) + 1;
  const magnitude = 10 ** digits;
  const scale = digits !== 1 ? 0.05 : 0.1;
  const step = Math.ceil(rough / magnitude / scale) * scale * magnitude;
  const ticks = [];
  for (let i = 0; min + i * step < max; i++) ticks.push(min + i * step);
  ticks.push(max);
  return ticks;
}

// X labels: walk backwards from the last lap and keep every label that fits without touching
function visibleLaps(laps, area, width) {
  const n = laps.length;
  const shown = [];
  let end = width;
  for (let i = n - 1; i >= 0; i--) {
    const half = (String(laps[i]).length * CHAR_WIDTH) / 2;
    let x = area.left + (n > 1 ? (i * (area.right - area.left)) / (n - 1) : 0);
    if (i === n - 1 && x + half > end) x -= x + half - end;
    if (x - half >= 0 && x + half <= end) {
      shown.push({ lap: laps[i], x });
      end = x - (half + MIN_TICK_GAP);
    }
  }
  return shown;
}

function drawChart(card, { laps, drivers }) {
  // Show the whole data range; only widen it further if the padded percentile range is wider
  const times = drivers.flatMap((d) => d.times).filter((v) => v != null).sort((a, b) => a - b);
  const p10 = times[Math.floor(times.length * 0.05)] ?? times[0];
  const p90 = times[Math.floor(times.length * 0.95)] ?? times[times.length - 1];
  const pad = (p90 - p10) * 0.1;
  const yMin = Math.min(Math.max(0, p10 - pad), times[0]);
  const yMax = Math.max(p90 + pad, times[times.length - 1]);
  const ticks = yTicks(yMin, yMax);

  let progress = 0; // 0 → 1 while the lines are revealed

  const plugins = [
    {
      id: 'reveal',
      beforeDatasetsDraw(c) {
        c.ctx.save();
        c.ctx.beginPath();
        c.ctx.rect(0, 0, c.chartArea.left + (c.chartArea.right - c.chartArea.left) * progress, c.height);
        c.ctx.clip();
      },
      afterDatasetsDraw(c) {
        c.ctx.restore();
      },
    },
    {
      id: 'cursorLine', // vertical hover line
      afterDatasetsDraw(c) {
        const active = c.tooltip?.getActiveElements();
        if (!active?.length) return;
        const { ctx, chartArea } = c;
        ctx.save();
        ctx.strokeStyle = '#ccc';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(active[0].element.x, chartArea.top);
        ctx.lineTo(active[0].element.x, chartArea.bottom);
        ctx.stroke();
        ctx.restore();
      },
    },
    {
      id: 'axisLabels', // Y values, lap numbers and the "Lap" caption
      afterDraw(c) {
        const { ctx, chartArea } = c;
        ctx.save();
        ctx.fillStyle = AXIS_COLOR;
        ctx.textBaseline = 'alphabetic';
        ctx.font = `${AXIS_FONT.size}px ${AXIS_FONT.family}`;
        ctx.textAlign = 'right';
        for (const v of ticks) {
          // centred on the gridline, but the top label is kept inside the plot area
          const y = Math.max(c.scales.y.getPixelForValue(v), chartArea.top + 3.5);
          ctx.fillText(formatLapTime(v), chartArea.left - 8, y + 3.55);
        }
        ctx.textAlign = 'center';
        for (const { lap, x } of visibleLaps(laps, chartArea, c.width)) ctx.fillText(lap, x, chartArea.bottom + 15.1);
        ctx.textAlign = 'right';
        ctx.font = `${AXIS_FONT.size}px Inter, sans-serif`;
        ctx.fillText('Lap', chartArea.right + 4, c.height + 4); // mostly below the canvas, as in the original
        ctx.restore();
      },
    },
  ];

  const tip = card.querySelector('[data-tooltip]');

  function showTooltip({ chart: c, tooltip }) {
    if (tooltip.opacity === 0) {
      tip.classList.add('hidden');
      return;
    }
    const rows = tooltip.dataPoints
      .filter((p) => p.raw)
      .sort((a, b) => a.raw - b.raw)
      .map((p) => `
        <div class="flex items-center justify-between gap-4">
          <div class="flex items-center gap-2">
            <span class="w-5 h-[2px] rounded-full" style="background: #${escapeHtml(drivers[p.datasetIndex].colour || '8A95A3')}"></span>
            <span class="font-mono text-[10px] text-[#8A95A3] uppercase">${escapeHtml(p.dataset.label)}</span>
          </div>
          <span class="font-mono text-xs text-[#F0F2F5]">${formatLapTime(p.raw)}</span>
        </div>`).join('');
    tip.innerHTML = `
      <div class="bg-[#1C2330] border border-[rgba(255,255,255,0.12)] rounded-lg px-3 py-2.5 shadow-xl">
        <p class="font-mono text-[10px] text-[#8A95A3] uppercase tracking-wider mb-2">Lap ${escapeHtml(tooltip.title[0])}</p>
        <div class="flex flex-col gap-1.5">${rows}</div>
      </div>`;
    tip.classList.remove('hidden');
    const x = tooltip.caretX;
    const flip = x + 10 + tip.offsetWidth > c.width;
    tip.style.left = `${flip ? x - 10 - tip.offsetWidth : x + 10}px`;
    tip.style.top = `${Math.max(0, Math.min(tooltip.caretY - tip.offsetHeight / 2, c.height - tip.offsetHeight))}px`;
  }

  const current = new Chart(card.querySelector('canvas'), {
    type: 'line',
    plugins,
    data: {
      labels: laps,
      datasets: drivers.map((d) => {
        const colour = `#${d.colour || '8A95A3'}`;
        return {
          label: d.acronym,
          data: d.times,
          borderColor: colour,
          borderWidth: 1.5,
          pointRadius: 0,
          pointHoverRadius: 3,
          pointHoverBorderWidth: 0,
          pointHoverBackgroundColor: colour,
          cubicInterpolationMode: 'monotone',
          spanGaps: false,
        };
      }),
    },
    options: {
      animation: false,
      responsive: true,
      maintainAspectRatio: false,
      layout: { padding: { top: 4, right: 8 } },
      interaction: { mode: 'index', intersect: false },
      plugins: { legend: { display: false }, tooltip: { enabled: false, external: showTooltip } },
      scales: {
        x: {
          grid: { display: false },
          border: { display: false },
          ticks: { display: false }, // drawn by the axisLabels plugin
          afterFit(scale) { scale.height = X_AXIS_HEIGHT; },
        },
        y: {
          min: yMin,
          max: yMax,
          grid: { color: 'rgba(255,255,255,0.05)', drawTicks: false },
          border: { display: false, dash: [4, 4] },
          ticks: { display: false }, // drawn by the axisLabels plugin
          afterBuildTicks(scale) { scale.ticks = ticks.map((value) => ({ value })); },
          afterFit(scale) {
            scale.width = Y_AXIS_WIDTH;
            scale.paddingTop = 0; // keep the top gridline at the top of the plot area
            scale.paddingBottom = 0;
          },
        },
      },
    },
  });
  chart = current;

  const started = performance.now();
  (function frame(now) {
    if (chart !== current) return;
    const t = Math.min((now - started) / 1500, 1);
    progress = t * t * (3 - 2 * t);
    current.draw();
    if (t < 1) requestAnimationFrame(frame);
  })(started);
}

// ── Load ──────────────────────────────────────────────────────────────────────

async function load() {
  chart?.destroy();
  chart = null;
  table.innerHTML = loadingTable;
  chartSlot.innerHTML = loadingChart;

  try {
    const res = await fetch(root.dataset.url);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to load race data.');

    table.innerHTML = tableHeader + data.rows.map(rowHtml).join('');
    chartSlot.innerHTML = '';
    if (data.chart.laps.length) {
      await Promise.all([document.fonts.load('10px "JetBrains Mono"'), document.fonts.load('10px Inter')]).catch(() => {});
      chartSlot.innerHTML = chartCardHtml(data.chart.drivers);
      drawChart(chartSlot, data.chart);
    }
  } catch (e) {
    table.innerHTML = errorHtml(e.message);
    table.querySelector('[data-retry]').addEventListener('click', load);
    chartSlot.innerHTML = '';
  }
}

load();
