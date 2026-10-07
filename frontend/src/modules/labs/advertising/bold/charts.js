/**
 * Bold Clarity — the design kit's charts.js (docs/new-design-kit/bold-clarity/), for the
 * /labs/advertising trial ONLY.
 *
 * The code is the kit's, unchanged but for Prettier's layout: `BC.seriesChart`
 * (lines, areas, bars, stacked layers, the «сегодня» line, day bands, the hover
 * tooltip) and `BC.hbars`, with the kit's number formatters. The one real change
 * is the wrapper — the kit is a classic script that assigns `window.BC`; here it
 * is an ES module that exports `BC`, so it is bundled with the lab's chunk
 * instead of being a global every page carries.
 *
 * Both functions return an HTML string. Tooltips work through ONE pointermove
 * listener on `document`, bound on the first named chart and found again by the
 * `data-chart` id the markup carries — so a Vue wrapper only has to put the
 * string in the DOM and redraw it when its width changes.
 */
const esc = (s) =>
  String(s ?? '').replace(
    /[&<>"]/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c],
  )
// Подсказки графиков: один обработчик на документ, данные графиков — в реестре по id.
const CHARTS = new Map()
let chartSeq = 0,
  tipsBound = false
function bindTips() {
  if (tipsBound || typeof document === 'undefined') return
  tipsBound = true
  let active = null
  const hide = () => {
    if (!active) return
    active.querySelector('.xhair').hidden = true
    active.querySelector('.tip').hidden = true
    active = null
  }
  const move = (e) => {
    const box = e.target.closest && e.target.closest('[data-chart]')
    if (!box) {
      hide()
      return
    }
    if (active && active !== box) hide()
    const c = CHARTS.get(box.dataset.chart),
      svg = box.querySelector('svg')
    if (!c || !svg) return
    const r = svg.getBoundingClientRect(),
      k = r.width / c.W
    const vx = (e.clientX - r.left) / k
    if (vx < c.L - 4 || vx > c.W - c.R + 4) {
      hide()
      return
    }
    const i = Math.max(0, Math.min(c.days - 1, Math.round(c.days <= 1 ? 0 : (vx - c.L) / c.step)))
    const rows = c.series.filter((s) => s.name && s.values[i] != null)
    if (!rows.length) {
      hide()
      return
    }
    active = box
    const xh = box.querySelector('.xhair'),
      tip = box.querySelector('.tip')
    const px = c.x(i) * k + (svg.offsetLeft || 0)
    xh.hidden = false
    xh.style.left = px + 'px'
    xh.style.top = c.T * k + 'px'
    xh.style.height = (c.H - c.T - c.B) * k + 'px'
    tip.innerHTML =
      `<b>${c.esc(c.head(i))}</b>` +
      rows
        .map(
          (s) =>
            `<div class="row"><span><span class="sw" style="background:${s.color}"></span>${c.esc(s.name)}</span><span>${c.esc(s.tip ? (s.tip[i] ?? '—') : c.fmt(s.values[i]))}</span></div>`,
        )
        .join('') +
      (c.note ? c.note(i) : '')
    tip.hidden = false
    const w = tip.offsetWidth,
      bw = box.clientWidth
    tip.style.left = (px + 12 + w > bw ? Math.max(0, px - 12 - w) : px + 12) + 'px'
    tip.style.top = Math.max(0, c.T * k) + 'px'
  }
  document.addEventListener('pointermove', move)
  document.addEventListener('pointerdown', move)
  document.addEventListener('scroll', hide, true)
}

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const fmt = (v) => (v == null || !isFinite(v) ? '—' : nf0.format(Math.round(v)))
const pct = (v) => (v == null || !isFinite(v) ? '—' : nf0.format(v * 100) + '%')
// Деньги: «2,4 млн», «450 тыс», «9 500» + валюта (по умолчанию сом).
let CUR = 'сом'
const money = (v) => {
  if (v == null || !isFinite(v)) return '—'
  const a = Math.abs(v)
  return (
    (a >= 1e6
      ? nf1.format(v / 1e6) + ' млн'
      : a >= 1e4
        ? nf0.format(v / 1e3) + ' тыс'
        : nf0.format(v)) +
    ' ' +
    CUR
  )
}
// Крупное число для .num-xl/.num-l: цифра отдельно от единиц («2,4» + <small>млн сом</small>).
const bigNum = (s) => {
  const m = String(s).match(/^(−?-?[\d\s,]+)\s(.+)$/)
  return m ? `${esc(m[1])}<small>${esc(m[2])}</small>` : esc(s)
}
const chartW = (el) => Math.max(280, Math.round((el && el.clientWidth) || 800))
function hbars(items, { max, valueFmt }) {
  const mx = max || Math.max(1, ...items.map((i) => Math.max(i.v || 0, i.marker || 0)))
  return `<div class="hbar" role="list">${items
    .map(
      (it) => `<div class="r" role="listitem" title="${esc(it.label)}: ${esc(valueFmt(it.v))}">
      <span class="l">${esc(it.label)}</span>
      <span class="t"><span class="b" style="width:${Math.max(0, (100 * (it.v || 0)) / mx).toFixed(2)}%;background:${it.color};${it.dim ? 'opacity:.5;' : ''}"></span>${it.marker != null ? `<span class="m" style="left:${Math.min(100, (100 * it.marker) / mx).toFixed(2)}%"></span>` : ''}</span>
      <span class="v">${esc(valueFmt(it.v))}</span></div>`,
    )
    .join('')}</div>`
}

// Линии и столбики на одной оси (одна шкала). Серии с name попадают в подсказку при наведении.
// series: { values, color, name?, dash?, bar?, opacity?, area?, base?, tip? }; today — индекс дня «сегодня» (линия-маркер).
// base — нижняя граница сплошной заливки (слои с накоплением); tip — подписи значений для подсказки вместо valueFmt.
// bands: [{ a, b, cls, label?, strip? }] — подсвеченные отрезки дней (strip — узкая полоса у оси вместо фона); tipNote(i) — HTML под строками подсказки.
// Ширина рисунка — по ширине колонки, чтобы подписи не масштабировались вместе с графиком.
function seriesChart({
  days,
  series,
  labels,
  H = 150,
  valueFmt = fmt,
  tipHead,
  today,
  W: Wopt,
  bands = [],
  axisFmt,
  tipNote,
  yMax,
}) {
  const W = Math.round(Wopt || chartW()),
    L = 52,
    R = 12,
    T = 10,
    B = 22
  const vals = series.flatMap((s) => s.values.filter((v) => v != null))
  const mx = (yMax || Math.max(1, ...vals)) * 1.08
  const step = days <= 1 ? 0 : (W - L - R) / (days - 1)
  const x = (i) => L + (days <= 1 ? (W - L - R) / 2 : i * step)
  const y = (v) => T + (H - T - B) * (1 - v / mx)
  const axis =
    axisFmt ||
    ((v) =>
      v >= 1e6 ? nf1.format(v / 1e6) + ' млн' : v >= 1e4 ? nf0.format(v / 1e3) + ' тыс' : fmt(v))
  let g = ''
  const half = days <= 1 ? 0 : step / 2
  for (const b of bands) {
    const x0 = Math.max(L, x(b.a) - half),
      x1 = Math.min(W - R, x(b.b) + half)
    if (x1 <= x0) continue
    g += b.strip
      ? `<rect class="band ${b.cls}" x="${x0.toFixed(1)}" y="${(H - B - 4).toFixed(1)}" width="${(x1 - x0).toFixed(1)}" height="4" rx="1"/>`
      : `<rect class="band ${b.cls}" x="${x0.toFixed(1)}" y="${T}" width="${(x1 - x0).toFixed(1)}" height="${H - T - B}"/>` +
        (b.label && x1 - x0 > 60
          ? `<text x="${(x0 + 4).toFixed(1)}" y="${T + 9}" class="band-l">${esc(b.label)}</text>`
          : '')
  }
  for (let k = 0; k <= 2; k++) {
    const v = ((mx / 1.08) * k) / 2
    g += `<line x1="${L}" x2="${W - R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" stroke="var(--grid)"/><text x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${axis(v)}</text>`
  }
  const lstep = Math.max(1, Math.ceil(days / Math.max(3, Math.floor((W - L - R) / 70))))
  for (let i = 0; i < days; i += lstep)
    g += `<text x="${x(i)}" y="${H - 6}" text-anchor="middle">${labels[i]}</text>`
  if (today != null && today >= 0 && today < days - 1)
    g += `<line x1="${x(today)}" x2="${x(today)}" y1="${T}" y2="${H - B}" stroke="var(--muted)" stroke-dasharray="2 3"/><text x="${x(today) + 4}" y="${T + 9}" class="today">сегодня</text>`
  const bw = Math.max(1, (W - L - R) / Math.max(1, days) - 2)
  for (const s of series) {
    if (s.bar) {
      s.values.forEach((v, i) => {
        if (v > 0) {
          const h = y(0) - y(v),
            r = Math.min(2, bw / 2, h)
          g += `<path d="M${(x(i) - bw / 2).toFixed(1)},${y(0).toFixed(1)}v${(-h + r).toFixed(1)}q0,${-r} ${r},${-r}h${(bw - 2 * r).toFixed(1)}q${r},0 ${r},${r}v${(h - r).toFixed(1)}z" fill="${s.color}" fill-opacity="${s.opacity || 1}"/>`
        }
      })
      continue
    }
    if (s.base) {
      // слой между base и values; разрывы (null) делят его на куски
      let run = []
      const flush = () => {
        if (run.length) {
          g += `<path d="M${run.map((i) => x(i).toFixed(1) + ',' + y(s.values[i]).toFixed(1)).join('L')}L${run
            .slice()
            .reverse()
            .map((i) => x(i).toFixed(1) + ',' + y(s.base[i] || 0).toFixed(1))
            .join(
              'L',
            )}Z" fill="${s.color}" fill-opacity="${s.opacity || 1}" stroke="var(--surface)" stroke-width="1" stroke-linejoin="round"/>`
        }
        run = []
      }
      s.values.forEach((v, i) => {
        if (v == null) flush()
        else run.push(i)
      })
      flush()
      continue
    }
    let d = '',
      pen = false,
      first = null,
      last = null
    s.values.forEach((v, i) => {
      if (v == null) {
        pen = false
        return
      }
      d += (pen ? 'L' : 'M') + x(i).toFixed(1) + ',' + y(v).toFixed(1)
      pen = true
      if (first == null) first = i
      last = i
    })
    if (s.area && first != null)
      g += `<path d="${d}L${x(last).toFixed(1)},${y(0).toFixed(1)}L${x(first).toFixed(1)},${y(0).toFixed(1)}Z" fill="${s.color}" fill-opacity=".1"/>`
    g += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2" ${s.dash ? `stroke-dasharray="${s.dash}"` : ''} stroke-linejoin="round" stroke-linecap="round"/>`
    if (last != null && !s.dash && (s.end || first === last))
      g += `<circle cx="${x(last)}" cy="${y(s.values[last])}" r="4" fill="${s.color}" stroke="var(--surface)" stroke-width="2"/>`
  }
  const named = series.some((s) => s.name)
  if (!named) return `<svg viewBox="0 0 ${W} ${H}" role="img" class="sc">${g}</svg>`
  if (CHARTS.size > 60 && typeof document !== 'undefined')
    for (const id of CHARTS.keys())
      if (!document.querySelector(`[data-chart="${id}"]`)) CHARTS.delete(id)
  const id = 'c' + ++chartSeq
  CHARTS.set(id, {
    W,
    H,
    L,
    R,
    T,
    B,
    days,
    step,
    x,
    series,
    esc,
    fmt: valueFmt,
    head: tipHead || ((i) => labels[i]),
    note: tipNote,
  })
  bindTips()
  return `<div class="chart" data-chart="${id}"><svg viewBox="0 0 ${W} ${H}" role="img" class="sc">${g}</svg><div class="xhair" hidden></div><div class="tip" hidden></div></div>`
}

export const BC = {
  seriesChart,
  hbars,
  fmt,
  pct,
  money,
  bigNum,
  chartW,
  esc,
  setCurrency: (c) => {
    CUR = c
  },
}
