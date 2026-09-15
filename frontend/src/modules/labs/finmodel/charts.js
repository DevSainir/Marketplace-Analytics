/**
 * Линейный график и сгруппированные столбцы. Рисуются в SVG руками — страница
 * пришла одним файлом и своей библиотеки не приносила.
 */
import { css } from '@/modules/labs/finmodel/dom'
import { dateRu, esc, kk } from '@/modules/labs/finmodel/format'

function niceMax(v) {
  if (!(v > 0)) return 1
  var p = Math.pow(10, Math.floor(Math.log10(v))),
    r = v / p
  return (r <= 1 ? 1 : r <= 2 ? 2 : r <= 2.5 ? 2.5 : r <= 5 ? 5 : 10) * p
}

/** Линейный график с перекрестием и подсказкой. Одна шкала на все ряды. */
export function lineChart(box, dates, series, fmt) {
  var W = 800,
    H = 232,
    mL = 58,
    mR = 16,
    mT = 12,
    mB = 26
  var iw = W - mL - mR,
    ih = H - mT - mB
  var max = 0,
    min = 0
  series.forEach(function (s) {
    s.values.forEach(function (v) {
      if (v > max) max = v
      if (v < min) min = v
    })
  })
  max = niceMax(max)
  min = min < 0 ? -niceMax(-min) : 0
  var span = max - min
  var n = dates.length
  var x = function (i) {
    return mL + (n < 2 ? iw / 2 : (i / (n - 1)) * iw)
  }
  var y = function (v) {
    return mT + ih - ((v - min) / span) * ih
  }

  var g = ''
  for (var t = 0; t <= 4; t++) {
    var val = min + (span * t) / 4,
      yy = y(val)
    g +=
      '<line x1="' +
      mL +
      '" y1="' +
      yy +
      '" x2="' +
      (W - mR) +
      '" y2="' +
      yy +
      '" stroke="' +
      css('--grid') +
      '" stroke-width="1"/>' +
      '<text x="' +
      (mL - 8) +
      '" y="' +
      (yy + 3.4) +
      '" text-anchor="end">' +
      kk(val) +
      '</text>'
  }
  var step = Math.max(1, Math.ceil(n / 9))
  for (var i = 0; i < n; i += step) {
    g +=
      '<text x="' +
      x(i) +
      '" y="' +
      (H - 8) +
      '" text-anchor="middle">' +
      dates[i].slice(8, 10) +
      '.' +
      dates[i].slice(5, 7) +
      '</text>'
  }
  series.forEach(function (s) {
    var d = s.values
      .map(function (v, i) {
        return (i ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(v).toFixed(1)
      })
      .join(' ')
    g +=
      '<path d="' +
      d +
      '" fill="none" stroke="' +
      s.color +
      '" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
  })
  if (min < 0) {
    g +=
      '<line x1="' +
      mL +
      '" y1="' +
      y(0) +
      '" x2="' +
      (W - mR) +
      '" y2="' +
      y(0) +
      '" stroke="' +
      css('--hairline-2') +
      '" stroke-width="1"/>'
  }
  g +=
    '<line id="ch" x1="0" y1="' +
    mT +
    '" x2="0" y2="' +
    (mT + ih) +
    '" stroke="' +
    css('--hairline-2') +
    '" stroke-width="1" opacity="0"/>'
  series.forEach(function (s, k) {
    g +=
      '<circle class="dot d' +
      k +
      '" r="4" fill="' +
      s.color +
      '" stroke="' +
      css('--surface') +
      '" stroke-width="2" opacity="0"/>'
  })
  g +=
    '<rect x="' +
    mL +
    '" y="' +
    mT +
    '" width="' +
    iw +
    '" height="' +
    ih +
    '" fill="transparent"/>'

  box.innerHTML =
    '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img">' + g + '</svg>' + '<div class="tip"></div>'
  var svg = box.querySelector('svg'),
    tip = box.querySelector('.tip')
  var ch = svg.querySelector('#ch'),
    dots = svg.querySelectorAll('.dot')

  function move(ev) {
    var r = svg.getBoundingClientRect()
    var px = ((ev.clientX - r.left) / r.width) * W
    var i = n < 2 ? 0 : Math.round(((px - mL) / iw) * (n - 1))
    i = Math.max(0, Math.min(n - 1, i))
    ch.setAttribute('x1', x(i))
    ch.setAttribute('x2', x(i))
    ch.setAttribute('opacity', '1')
    var rows = ''
    series.forEach(function (s, k) {
      dots[k].setAttribute('cx', x(i))
      dots[k].setAttribute('cy', y(s.values[i]))
      dots[k].setAttribute('opacity', '1')
      rows +=
        '<div class="tr"><span><span class="swatch" style="background:' +
        s.color +
        '"></span> ' +
        esc(s.name) +
        '</span><span class="tv">' +
        fmt(s.values[i]) +
        '</span></div>'
    })
    tip.innerHTML = '<div class="th">' + dateRu(dates[i]) + '</div>' + rows
    tip.style.opacity = '1'
    var bw = box.clientWidth,
      tx = (x(i) / W) * bw + 14
    if (tx + tip.offsetWidth > bw) tx = (x(i) / W) * bw - tip.offsetWidth - 14
    tip.style.left = Math.max(0, tx) + 'px'
    tip.style.top = '8px'
  }
  function leave() {
    tip.style.opacity = '0'
    ch.setAttribute('opacity', '0')
    dots.forEach(function (d) {
      d.setAttribute('opacity', '0')
    })
  }
  svg.addEventListener('pointermove', move)
  svg.addEventListener('pointerleave', leave)
}

/** Сгруппированные столбцы с подсказкой на столбец. */
export function barChart(box, labels, series, fmt) {
  var W = 800,
    H = 236,
    mL = 58,
    mR = 16,
    mT = 12,
    mB = 30
  var iw = W - mL - mR,
    ih = H - mT - mB
  var min = 0,
    max = 0
  series.forEach(function (s) {
    s.values.forEach(function (v) {
      if (v > max) max = v
      if (v < min) min = v
    })
  })
  max = niceMax(max)
  min = min < 0 ? -niceMax(-min) : 0
  var span = max - min
  var y = function (v) {
    return mT + ih - ((v - min) / span) * ih
  }
  var n = labels.length,
    slot = iw / n,
    k = series.length
  var bw = Math.max(3, Math.min(26, (slot - 8) / k - 2))

  var g = ''
  for (var t = 0; t <= 4; t++) {
    var val = min + (span * t) / 4,
      yy = y(val)
    g +=
      '<line x1="' +
      mL +
      '" y1="' +
      yy +
      '" x2="' +
      (W - mR) +
      '" y2="' +
      yy +
      '" stroke="' +
      css('--grid') +
      '" stroke-width="1"/>' +
      '<text x="' +
      (mL - 8) +
      '" y="' +
      (yy + 3.4) +
      '" text-anchor="end">' +
      kk(val) +
      '</text>'
  }
  var y0 = y(0)
  labels.forEach(function (lab, i) {
    var cx = mL + slot * (i + 0.5)
    var tot = bw * k + 2 * (k - 1)
    series.forEach(function (s, j) {
      var v = s.values[i],
        yv = y(v)
      var top = Math.min(yv, y0),
        h = Math.max(1.5, Math.abs(yv - y0))
      g +=
        '<rect x="' +
        (cx - tot / 2 + j * (bw + 2)).toFixed(1) +
        '" y="' +
        top.toFixed(1) +
        '" width="' +
        bw.toFixed(1) +
        '" height="' +
        h.toFixed(1) +
        '" rx="3" fill="' +
        s.color +
        '"/>'
    })
    g += '<text x="' + cx + '" y="' + (H - 9) + '" text-anchor="middle">' + esc(lab) + '</text>'
  })
  g +=
    '<line x1="' +
    mL +
    '" y1="' +
    y0 +
    '" x2="' +
    (W - mR) +
    '" y2="' +
    y0 +
    '" stroke="' +
    css('--hairline-2') +
    '" stroke-width="1"/>'
  for (var i2 = 0; i2 < n; i2++) {
    g +=
      '<rect class="hit" data-i="' +
      i2 +
      '" x="' +
      (mL + slot * i2) +
      '" y="' +
      mT +
      '" width="' +
      slot +
      '" height="' +
      ih +
      '" fill="transparent"/>'
  }
  box.innerHTML =
    '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img">' + g + '</svg>' + '<div class="tip"></div>'
  var svg = box.querySelector('svg'),
    tip = box.querySelector('.tip')
  svg.querySelectorAll('.hit').forEach(function (r) {
    r.addEventListener('pointerenter', function () {
      var i = +r.dataset.i,
        rows = ''
      series.forEach(function (s) {
        rows +=
          '<div class="tr"><span><span class="swatch sq" style="background:' +
          s.color +
          '"></span> ' +
          esc(s.name) +
          '</span><span class="tv">' +
          fmt(s.values[i]) +
          '</span></div>'
      })
      tip.innerHTML = '<div class="th">' + esc(labels[i]) + '</div>' + rows
      tip.style.opacity = '1'
      var bwpx = box.clientWidth,
        cx = ((mL + slot * (i + 0.5)) / W) * bwpx
      var tx = cx + 14
      if (tx + tip.offsetWidth > bwpx) tx = cx - tip.offsetWidth - 14
      tip.style.left = Math.max(0, tx) + 'px'
      tip.style.top = '8px'
    })
  })
  svg.addEventListener('pointerleave', function () {
    tip.style.opacity = '0'
  })
}
