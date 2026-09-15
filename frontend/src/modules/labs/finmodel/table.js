/**
 * Универсальная таблица: сортировка, закреплённые строки, раскрытие подстрок
 * и сворачивание хвоста.
 */
import { esc, nf0 } from '@/modules/labs/finmodel/format'
import { render } from '@/modules/labs/finmodel/render'

/* ── таблицы ────────────────────────────────────────────────────── */
export var sortState = {}
export function table(host, id, cols, rows, foot, expand, cap) {
  var st =
    sortState[id] ||
    (sortState[id] = {
      key: cols.find(function (c) {
        return c.sort
      }).key,
      dir: -1,
    })
  var sorted = rows.slice().sort(function (a, b) {
    if (a.pin !== b.pin) return (b.pin || 0) - (a.pin || 0) // закреплённые наверху
    var x = a[st.key],
      y = b[st.key]
    if (x == null) return 1
    if (y == null) return -1
    if (typeof x === 'string') return st.dir * x.localeCompare(y, 'ru')
    return st.dir * (x - y)
  })
  var hidden = 0
  if (cap && !cap.isOpen() && sorted.length > cap.n) {
    hidden = sorted.length - cap.n
    sorted = sorted.slice(0, cap.n)
  }
  var h = '<div class="tscroll"><table><thead><tr>'
  cols.forEach(function (c) {
    var cl =
      (c.l ? 'l ' : '') +
      (c.sortable === false ? '' : 'sortable ') +
      (st.key === c.key ? (st.dir === 1 ? 'up' : 'down') : '')
    h +=
      '<th class="' +
      cl.trim() +
      '" data-k="' +
      c.key +
      '"' +
      (c.title ? ' title="' + esc(c.title) + '"' : '') +
      '>' +
      esc(c.name) +
      '</th>'
  })
  h += '</tr></thead><tbody>'
  sorted.forEach(function (r) {
    h += '<tr>'
    cols.forEach(function (c) {
      h += '<td class="' + (c.l ? 'l ' : '') + (c.cls ? c.cls(r) : '') + '">' + c.get(r) + '</td>'
    })
    h += '</tr>'
    if (!expand) return
    var body = expand.render(r)
    if (!body) return
    h +=
      '<tr class="subrow" data-sub="' +
      esc(expand.id(r)) +
      '"' +
      (expand.isOpen(r) ? '' : ' hidden') +
      '><td colspan="' +
      cols.length +
      '">' +
      body +
      '</td></tr>'
  })
  if (cap && (hidden || (cap.isOpen() && sorted.length > cap.n))) {
    h +=
      '<tr class="morerow"><td colspan="' +
      cols.length +
      '">' +
      '<button class="btn" data-more="1" type="button">' +
      (hidden ? 'Показать ещё ' + nf0.format(hidden) : 'Свернуть до ' + cap.n) +
      '</button></td></tr>'
  }
  h += '</tbody>'
  if (foot) {
    h += '<tfoot><tr>'
    cols.forEach(function (c) {
      h += '<td class="' + (c.l ? 'l' : '') + '">' + (foot[c.key] || '') + '</td>'
    })
    h += '</tr></tfoot>'
  }
  h += '</table></div>'
  host.innerHTML = h
  host.querySelectorAll('th.sortable').forEach(function (th) {
    th.addEventListener('click', function () {
      var k = th.dataset.k
      if (st.key === k) st.dir = -st.dir
      else {
        st.key = k
        st.dir = -1
      }
      render()
    })
  })
  var more = host.querySelector('button[data-more]')
  if (more)
    more.addEventListener('click', function () {
      cap.toggle()
      render()
    })
  if (!expand) return
  // раскрытие переключаем в самом DOM: полный ререндер сбросил бы прокрутку
  host.querySelectorAll('button[data-exp]').forEach(function (b) {
    b.addEventListener('click', function () {
      var key = b.dataset.exp
      var tr = host.querySelector('tr[data-sub="' + cssEsc(key) + '"]')
      if (!tr) return
      var open = tr.hidden
      tr.hidden = !open
      expand.setOpen(key, open)
      b.setAttribute('aria-expanded', open ? 'true' : 'false')
      b.title = open ? 'Свернуть размеры' : 'Показать размеры'
    })
  })
}

/** Экранирование для селектора по data-атрибуту: в артикулах бывают дефисы и точки. */
function cssEsc(v) {
  return String(v).replace(/["\\]/g, '\\$&')
}

export function riskBadge(d) {
  if (d == null) return '<span class="badge b-mute">нет расхода</span>'
  if (d <= 0) return '<span class="badge b-crit">ноль</span>'
  if (d <= 14) return '<span class="badge b-crit">' + d + ' дн</span>'
  if (d <= 35) return '<span class="badge b-warn">' + d + ' дн</span>'
  if (d <= 120) return '<span class="badge b-good">' + d + ' дн</span>'
  return '<span class="badge b-mute">' + d + ' дн</span>'
}
