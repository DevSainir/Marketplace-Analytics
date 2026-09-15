/**
 * Иконки в разметке таблиц. Треугольник не перерисовывается при раскрытии —
 * его поворачивает CSS.
 */
/* ── иконки ─────────────────────────────────────────────────────── */
// Треугольник не перерисовывается при раскрытии — его поворачивает CSS,
// поэтому переключение остаётся плавным и не дёргает разметку.
export var ICO_TRI =
  '<svg viewBox="0 0 12 12" aria-hidden="true" focusable="false">' +
  '<path d="M4.2 2.4 8.4 6 4.2 9.6z" fill="currentColor"/></svg>'
export var ICO_PIN_OFF =
  '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">' +
  '<path d="M14 4v5.2c0 .9.25 1.75.7 2.5H9.3c.45-.75.7-1.6.7-2.5V4h4m3-2H7a1 1 0 0 0 0 2h1v5.2' +
  'c0 1.55-1.2 2.8-2.7 2.8H5v2h6v6l1 1 1-1v-6h6v-2h-.3c-1.5 0-2.7-1.25-2.7-2.8V4h1a1 1 0 0 0 0-2z" ' +
  'fill="currentColor"/></svg>'
export var ICO_PIN_ON =
  '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">' +
  '<path d="M16 9.2V4h1a1 1 0 0 0 0-2H7a1 1 0 0 0 0 2h1v5.2c0 1.55-1.2 2.8-2.7 2.8H5v2h6v6l1 1 1-1v-6' +
  'h6v-2h-.3c-1.5 0-2.7-1.25-2.7-2.8z" fill="currentColor"/></svg>'
