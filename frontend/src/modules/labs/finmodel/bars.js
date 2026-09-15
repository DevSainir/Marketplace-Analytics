/**
 * Полосы долей: «кто генерит» на вкладке «Сводка» и горизонтальные полосы
 * остатков. Вынесены из charts.js, чтобы оба файла остались в пределах
 * потолка репозитория.
 */
import { css } from '@/modules/labs/finmodel/dom'
import { esc, money, nf0, num, pct } from '@/modules/labs/finmodel/format'

export function paretoBars(box, rows) {
  var W = 800,
    rowH = 36,
    mL = 152,
    wNum = 56,
    mT = 22,
    barH = 10,
    gap = 3
  var H = mT + rows.length * rowH + 14
  var iw = W - mL - wNum * 2 - 18
  var max = 0,
    min = 0
  rows.forEach(function (r) {
    if (r.revShare > max) max = r.revShare
    if (r.marShare > max) max = r.marShare
    if (r.marShare < min) min = r.marShare
  })
  max = max || 1
  var span = max - min
  var zero = mL + (-min / span) * iw
  var px = function (v) {
    return (Math.abs(v) / span) * iw
  }

  var g =
    '<text x="' +
    mL +
    '" y="' +
    (mT - 8) +
    '" class="lbl">доля в итоге</text>' +
    '<text x="' +
    (mL + iw + wNum) +
    '" y="' +
    (mT - 8) +
    '" text-anchor="end" class="lbl">выручка</text>' +
    '<text x="' +
    (mL + iw + wNum * 2) +
    '" y="' +
    (mT - 8) +
    '" text-anchor="end" class="lbl">маржа</text>'
  if (min < 0) {
    g +=
      '<line x1="' +
      zero +
      '" y1="' +
      mT +
      '" x2="' +
      zero +
      '" y2="' +
      (mT + rows.length * rowH) +
      '" stroke="' +
      css('--hairline-2') +
      '" stroke-width="1"/>'
  }

  var y = mT
  rows.forEach(function (r, i) {
    var op = r.dim ? ' opacity="0.5"' : ''
    var yr = y + 5,
      ym = yr + barH + gap,
      mid = y + rowH / 2 + 4
    g +=
      '<text x="' +
      (mL - 10) +
      '" y="' +
      mid +
      '" text-anchor="end" class="lbl"' +
      op +
      '>' +
      esc(r.code) +
      '</text>'
    var rw = Math.max(1.5, px(r.revShare))
    var neg = r.marShare < 0
    var mw = Math.max(1.5, px(r.marShare))
    var mx = neg ? zero - mw : zero
    g +=
      '<rect x="' +
      zero +
      '" y="' +
      yr +
      '" width="' +
      rw.toFixed(1) +
      '" height="' +
      barH +
      '" rx="3" fill="' +
      css('--s1') +
      '"' +
      op +
      '/>' +
      '<rect x="' +
      mx.toFixed(1) +
      '" y="' +
      ym +
      '" width="' +
      mw.toFixed(1) +
      '" height="' +
      barH +
      '" rx="3" fill="' +
      (neg ? css('--crit') : css('--s3')) +
      '"' +
      op +
      '/>'
    // Прозрачные цели поверх самих полос: подсказку показывает только полоса,
    // но у коротких полос цель расширена до 12 px, иначе в неё не попасть.
    g +=
      '<rect class="hitbar" data-i="' +
      i +
      '" data-k="rev" x="' +
      zero +
      '" y="' +
      yr +
      '" width="' +
      Math.max(rw, 12).toFixed(1) +
      '" height="' +
      barH +
      '" fill="transparent"/>' +
      '<rect class="hitbar" data-i="' +
      i +
      '" data-k="mar" x="' +
      (neg ? Math.min(mx, zero - 12) : zero).toFixed(1) +
      '" y="' +
      ym +
      '" width="' +
      Math.max(mw, 12).toFixed(1) +
      '" height="' +
      barH +
      '" fill="transparent"/>'
    g +=
      '<text x="' +
      (mL + iw + wNum) +
      '" y="' +
      mid +
      '" text-anchor="end">' +
      num(r.revShare * 100, 1) +
      ' %</text>' +
      '<text x="' +
      (mL + iw + wNum * 2) +
      '" y="' +
      mid +
      '" text-anchor="end"' +
      (neg ? ' fill="' + css('--crit') + '"' : '') +
      '>' +
      num(r.marShare * 100, 1) +
      ' %</text>'
    y += rowH
  })

  box.innerHTML =
    '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img">' + g + '</svg>' + '<div class="tip"></div>'
  var svg = box.querySelector('svg'),
    tip = box.querySelector('.tip')

  function line(on, sw, name, val) {
    return (
      '<div class="tr"' +
      (on ? ' style="font-weight:600"' : '') +
      '><span><span class="swatch sq" style="background:' +
      sw +
      '"></span>' +
      name +
      '</span><span class="tv">' +
      val +
      '</span></div>'
    )
  }
  function show(ev, i, k) {
    var r = rows[i]
    var negm = r.marShare < 0
    var html =
      '<div class="th">' +
      esc(r.code) +
      (r.tail ? ' · свёрнуто' : '') +
      '</div>' +
      line(
        k === 'rev',
        css('--s1'),
        'Доля в выручке',
        num(r.revShare * 100, 1) + ' % · ' + money(r.rev),
      ) +
      line(
        k === 'mar',
        negm ? css('--crit') : css('--s3'),
        'Доля в марже',
        num(r.marShare * 100, 1) + ' % · ' + money(r.mar),
      ) +
      '<div class="tr"><span>Маржа от выручки</span><span class="tv">' +
      pct(r.mpct) +
      '</span></div>' +
      '<div class="tr"><span>Продано</span><span class="tv">' +
      nf0.format(r.units) +
      ' ед</span></div>' +
      (r.n > 1
        ? '<div class="tr"><span>Артикулов внутри</span><span class="tv">' +
          nf0.format(r.n) +
          '</span></div>'
        : '') +
      (r.tailNeg
        ? '<div class="tr"><span>Из них убыточных</span><span class="tv">' +
          r.tailNeg +
          '</span></div>'
        : '')
    tip.innerHTML = html
    tip.style.opacity = '1'
    var br = box.getBoundingClientRect()
    var tx = ev.clientX - br.left + 16
    if (tx + tip.offsetWidth > box.clientWidth) tx = ev.clientX - br.left - tip.offsetWidth - 16
    var ty = ev.clientY - br.top + 14
    if (ty + tip.offsetHeight > box.clientHeight) ty = box.clientHeight - tip.offsetHeight - 4
    tip.style.left = Math.max(0, tx) + 'px'
    tip.style.top = Math.max(0, ty) + 'px'
  }
  svg.querySelectorAll('.hitbar').forEach(function (el2) {
    el2.addEventListener('pointermove', function (ev) {
      show(ev, +el2.dataset.i, el2.dataset.k)
    })
    el2.addEventListener('pointerleave', function () {
      tip.style.opacity = '0'
    })
  })
}

/** Горизонтальные полосы «дней до нуля» со статусной заливкой. */
export function hbars(box, rows) {
  var W = 800,
    rowH = 21,
    mL = 132,
    mR = 46,
    mT = 14
  var H = mT + rows.length * rowH + 20
  var iw = W - mL - mR,
    max = 60
  var g = ''
  ;[0, 14, 30, 45, 60].forEach(function (t) {
    var x = mL + (t / max) * iw
    g +=
      '<line x1="' +
      x +
      '" y1="' +
      mT +
      '" x2="' +
      x +
      '" y2="' +
      (mT + rows.length * rowH) +
      '" stroke="' +
      css('--grid') +
      '" stroke-width="1"/>' +
      '<text x="' +
      x +
      '" y="' +
      (H - 6) +
      '" text-anchor="middle">' +
      t +
      '</text>'
  })
  g +=
    '<text x="' +
    (mL + iw / 2) +
    '" y="' +
    (mT - 4) +
    '" text-anchor="middle" class="lbl">дней</text>'
  rows.forEach(function (r, i) {
    var y = mT + i * rowH + 3,
      h = rowH - 8
    var w = Math.max(2, (Math.min(r.d, max) / max) * iw)
    var col = r.d <= 14 ? css('--crit') : r.d <= 35 ? css('--warn') : css('--good')
    g +=
      '<text x="' +
      (mL - 9) +
      '" y="' +
      (y + h - 1) +
      '" text-anchor="end" class="lbl">' +
      esc(r.code) +
      '</text>' +
      '<rect x="' +
      mL +
      '" y="' +
      y +
      '" width="' +
      w.toFixed(1) +
      '" height="' +
      h +
      '" rx="3" fill="' +
      col +
      '"/>' +
      '<text x="' +
      (mL + w + 6) +
      '" y="' +
      (y + h - 1) +
      '">' +
      r.d +
      '</text>'
  })
  box.innerHTML = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img">' + g + '</svg>'
}
