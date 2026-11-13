/* ============================================================================
   SIID-01 shared chart helpers.

   One reusable time-series renderer (area + 2px line, hairline gridlines, y
   ticks, crosshair + tooltip on hover) plus the source palette map, so the
   dashboard and activity pages draw identical-looking charts.

   Colours come from the .viz custom properties in abu.css, which hold the
   validated categorical palette. Callers must put class="viz" on an ancestor.
   ========================================================================== */

// Fixed categorical order -- never cycled, never reassigned by rank.
// Only the three real positioning methods carry a hue; bench test is neutral.
const SRC = {
  gps:      { label: 'GPS satellites', tag: 'GPS',  css: 'var(--series-1)', cls: 'gps'  },
  gps_hold: { label: 'Last GPS fix',   tag: 'HOLD', css: 'var(--series-3)', cls: 'hold' },
  cell:     { label: 'Cell tower',     tag: 'CELL', css: 'var(--series-2)', cls: 'cell' },
  test:     { label: 'Bench test',     tag: 'TEST', css: 'var(--series-4)', cls: 'test' }
};

const CW = 320, CH = 110, PADL = 26, PADR = 6, PADT = 8, PADB = 16;

/**
 * Draw a single-series time chart.
 * pts  : [{ v: number, label: string }]  (oldest -> newest)
 * opts : { stroke, fill, unit, min0 }    min0 = minimum value for the y scale
 */
function drawSeries(svgId, wrapId, tipId, pts, opts) {
  const svg = document.getElementById(svgId);
  const wrap = document.getElementById(wrapId);
  const tip = document.getElementById(tipId);
  if (!svg || !wrap || !tip) return;
  if (!pts.length) { svg.innerHTML = ''; return; }

  const vals = pts.map(p => p.v);
  const vmax = Math.max(opts.min0 != null ? opts.min0 : 1, Math.max.apply(null, vals));
  const x = i => PADL + (i / Math.max(1, pts.length - 1)) * (CW - PADL - PADR);
  const y = v => CH - PADB - (v / vmax) * (CH - PADT - PADB);

  const ticks = [0, Math.round(vmax / 2), Math.round(vmax)].filter((v, i, a) => a.indexOf(v) === i);
  const grid = ticks.map(t =>
    '<line x1="' + PADL + '" x2="' + (CW - PADR) + '" y1="' + y(t) + '" y2="' + y(t) +
    '" stroke="var(--grid)" stroke-width="1"/>' +
    '<text class="tick" x="' + (PADL - 6) + '" y="' + (y(t) + 3) + '" text-anchor="end">' + t + '</text>'
  ).join('');

  const line = pts.map((p, i) => x(i).toFixed(1) + ',' + y(p.v).toFixed(1)).join(' ');
  const area = 'M' + x(0).toFixed(1) + ',' + (CH - PADB) +
               ' L' + pts.map((p, i) => x(i).toFixed(1) + ',' + y(p.v).toFixed(1)).join(' L') +
               ' L' + x(pts.length - 1).toFixed(1) + ',' + (CH - PADB) + ' Z';

  svg.innerHTML = grid
    + '<path d="' + area + '" fill="' + opts.fill + '"/>'
    + '<polyline points="' + line + '" fill="none" stroke="' + opts.stroke +
      '" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
    + '<line id="' + svgId + '-cross" x1="0" y1="' + PADT + '" x2="0" y2="' + (CH - PADB) +
      '" stroke="var(--axis)" stroke-width="1" opacity="0"/>'
    + '<circle id="' + svgId + '-cur" r="4" fill="' + opts.stroke +
      '" stroke="var(--surface)" stroke-width="2" opacity="0"/>'
    + '<line x1="' + PADL + '" x2="' + (CW - PADR) + '" y1="' + (CH - PADB) + '" y2="' + (CH - PADB) +
      '" stroke="var(--axis)" stroke-width="1"/>';

  const cross = document.getElementById(svgId + '-cross');
  const cur = document.getElementById(svgId + '-cur');

  wrap.onmousemove = ev => {
    const r = wrap.getBoundingClientRect();
    const rel = ((ev.clientX - r.left) / r.width) * CW;
    let i = Math.round(((rel - PADL) / (CW - PADL - PADR)) * (pts.length - 1));
    i = Math.max(0, Math.min(pts.length - 1, i));
    const p = pts[i];
    cross.setAttribute('x1', x(i)); cross.setAttribute('x2', x(i)); cross.setAttribute('opacity', '.6');
    cur.setAttribute('cx', x(i)); cur.setAttribute('cy', y(p.v)); cur.setAttribute('opacity', '1');
    tip.innerHTML = p.label + '<br><b>' + p.v + '</b> ' + opts.unit;
    tip.classList.add('on');
    const px = (x(i) / CW) * r.width;
    tip.style.left = Math.min(Math.max(px - tip.offsetWidth / 2, 0), r.width - tip.offsetWidth) + 'px';
    tip.style.top = Math.max((y(p.v) / CH) * r.height - tip.offsetHeight - 10, 0) + 'px';
  };
  wrap.onmouseleave = () => {
    tip.classList.remove('on');
    cross.setAttribute('opacity', '0');
    cur.setAttribute('opacity', '0');
  };
}

/** Stacked categorical bar + legend. Each segment is directly labelled. */
function drawSourceBar(barId, legendId, counts) {
  const total = Object.keys(counts).reduce((a, k) => a + counts[k], 0) || 1;
  const used = Object.keys(SRC).filter(k => counts[k]);
  const bar = document.getElementById(barId), leg = document.getElementById(legendId);
  if (bar) {
    bar.innerHTML = used.map(k => {
      const pct = (counts[k] / total) * 100;
      return '<span style="width:' + pct.toFixed(1) + '%;background:' + SRC[k].css + '">' +
             (pct >= 12 ? Math.round(pct) + '%' : '') + '</span>';
    }).join('');
  }
  if (leg) {
    leg.innerHTML = used.map(k =>
      '<div class="li"><span class="sw" style="background:' + SRC[k].css + '"></span>' +
      '<span class="nm2">' + SRC[k].label + '</span>' +
      '<span class="ct">' + counts[k] + ' &middot; ' + Math.round((counts[k] / total) * 100) + '%</span></div>'
    ).join('');
  }
}

const timeAgo = iso => {
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  return s < 60 ? s + 's ago' : s < 3600 ? Math.round(s / 60) + 'm ago' : Math.round(s / 3600) + 'h ago';
};
