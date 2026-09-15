/**
 * Доступ к DOM страницы. Все запросы идут от корня вьюхи, а не от документа:
 * страница живёт внутри SPA, где её id — не единственные на документ, и
 * токены оформления объявлены на самом корне, а не на :root.
 */
let rootEl = null

export function setRoot(el) {
  rootEl = el
}

/** Элемент страницы по id — в пределах вьюхи. */
export function $(id) {
  return rootEl ? rootEl.querySelector('[id="' + id + '"]') : null
}

/** Панели вкладок — тоже только свои. */
export function panels() {
  return rootEl ? rootEl.querySelectorAll('.panel') : []
}

/** Значение токена оформления: цвета графиков берутся из CSS, а не дублируются в JS. */
export function css(name) {
  if (!rootEl) return ''
  return getComputedStyle(rootEl).getPropertyValue(name).trim()
}
