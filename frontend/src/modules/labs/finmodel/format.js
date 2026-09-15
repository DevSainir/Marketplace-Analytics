/**
 * Числа, проценты и даты в том виде, в каком их читают в отчётах WB.
 */
/* ── форматирование ─────────────────────────────────────────────── */
export var nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
export var nf1 = new Intl.NumberFormat('ru-RU', {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
})
export var nf2 = new Intl.NumberFormat('ru-RU', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

export function money(v) {
  return v == null || !isFinite(v) ? '—' : nf0.format(Math.round(v))
}
export function num(v, d) {
  if (v == null || !isFinite(v)) return '—'
  return d === 1 ? nf1.format(v) : d === 2 ? nf2.format(v) : nf0.format(v)
}
export function pct(v, d) {
  return v == null || !isFinite(v) ? '—' : num(v * 100, d == null ? 1 : d) + ' %'
}
export function kk(v) {
  if (v == null || !isFinite(v)) return '—'
  var a = Math.abs(v)
  if (a >= 1e6) return nf1.format(v / 1e6) + ' млн'
  if (a >= 1e4) return nf0.format(v / 1e3) + ' тыс'
  return nf0.format(v)
}
export function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]
  })
}
/** Склонение существительного при числительном: 1 артикул, 2 артикула, 5 артикулов. */
export function plural(n, one, few, many) {
  var a = Math.abs(n) % 100,
    b = a % 10
  if (a > 10 && a < 20) return many
  if (b > 1 && b < 5) return few
  if (b === 1) return one
  return many
}

export function dateRu(iso) {
  if (!iso) return '—'
  var p = iso.split('-')
  return p[2] + '.' + p[1] + '.' + p[0]
}
export function addDays(iso, n) {
  var d = new Date(iso + 'T00:00:00Z')
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}
export function daysBetween(a, b) {
  return Math.round((Date.parse(b + 'T00:00:00Z') - Date.parse(a + 'T00:00:00Z')) / 86400000) + 1
}
