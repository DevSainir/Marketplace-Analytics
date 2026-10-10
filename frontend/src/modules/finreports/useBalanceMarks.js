/**
 * The two floating overlays of the balance grid — the «Не считать» menu and the
 * full-name tooltip.
 *
 * Both a warehouse column header and a SKU row carry a ⋮ that opens the same
 * menu; the only difference is what the mark is attached to, so the menu carries
 * the target rather than the caller keeping two of them. The tooltip reveals a
 * name the grid had to shorten (WB warehouses run to «Санкт-Петербург Уткина
 * Заводь», which no numeric column can hold).
 *
 * Both overlays are positioned `fixed` and teleported, so they must close on ANY
 * scroll or they strand themselves over unrelated content.
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'

import { visibleArea } from '@/core/utils/tipFit'

/**
 * @param {object} options
 * @param {(mark: {kind: string, value: string, pinned: boolean}) => void} options.onMark
 *   Called with the chosen mark: `kind` is the API's — `sku_uncounted` or
 *   `warehouse_uncounted` — and `pinned` is the state it should end up in.
 */
export function useBalanceMarks({ onMark }) {
  // --- the ⋮ mark menu ------------------------------------------------------
  // { kind, value, label, uncounted, x, y } | null — one at a time; any outside
  // pointer-down, Esc or scroll closes it.
  const menu = ref(null)

  function openMenu(event, target) {
    if (menu.value?.kind === target.kind && menu.value?.value === target.value) {
      menu.value = null
      return
    }
    const rect = event.currentTarget.getBoundingClientRect()
    menu.value = { ...target, x: rect.left, y: rect.bottom + 4 }
  }

  /** «Не считать» / «Считать» — the same mark on either axis, so the kind is
   *  derived from what the menu was opened on rather than hard-coded.
   *
   *  Flipped here, so the caller persists the NEW state rather than re-deriving
   *  it from a row it is about to re-order out from under itself. */
  function toggleUncounted() {
    const { kind, value, uncounted } = menu.value
    menu.value = null
    onMark({ kind: `${kind}_uncounted`, value, pinned: !uncounted })
  }

  function onDocumentPointerDown(event) {
    if (menu.value && !event.target.closest('.mark-menu, .mark-menu-btn')) menu.value = null
  }
  function onDocumentKeydown(event) {
    if (event.key === 'Escape') menu.value = null
  }
  function onAnyScroll() {
    menu.value = null
    hoverTip.value = null
  }

  // --- the truncated-name tooltip -------------------------------------------
  const hoverTip = ref(null) // { name, x, y, area } | null

  function showNameTip(event, name, limit) {
    if (name.length <= limit) return // nothing truncated — nothing to reveal
    const rect = event.currentTarget.getBoundingClientRect()
    hoverTip.value = {
      name,
      x: rect.left,
      y: rect.bottom + 4,
      area: visibleArea(event.currentTarget),
    }
  }

  function hideNameTip() {
    hoverTip.value = null
  }

  onMounted(() => {
    document.addEventListener('pointerdown', onDocumentPointerDown)
    document.addEventListener('keydown', onDocumentKeydown)
    document.addEventListener('scroll', onAnyScroll, true)
  })
  onBeforeUnmount(() => {
    document.removeEventListener('pointerdown', onDocumentPointerDown)
    document.removeEventListener('keydown', onDocumentKeydown)
    document.removeEventListener('scroll', onAnyScroll, true)
  })

  return { menu, openMenu, toggleUncounted, hoverTip, showNameTip, hideNameTip }
}
