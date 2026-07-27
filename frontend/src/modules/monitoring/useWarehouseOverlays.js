/**
 * The two floating overlays of the stock breakdown table.
 *
 * A warehouse column header carries two of them: a right-click MENU that marks
 * the warehouse «на отгрузку», and a hover TOOLTIP showing the full name (the
 * header shows a shortened one — there is no room for «Санкт-Петербург
 * Уткина Заводь» above a numeric column).
 *
 * Extracted from the table because both are pure overlay bookkeeping —
 * coordinates, and the dismissal listeners any fixed-position popup needs —
 * while the table's own subject is the size x warehouse grid. Both are
 * positioned `fixed` and so must close on ANY scroll, or they strand
 * themselves over unrelated content.
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'

/**
 * @param {object} options
 * @param {(name: string) => void} options.onToggleMark Called when the menu's
 *   mark/unmark action is chosen.
 */
export function useWarehouseOverlays({ onToggleMark }) {
  // --- warehouse mark menu --------------------------------------------------
  // The ⋮ popup: rendered via Teleport with FIXED coordinates so the scroll
  // container can't clip it. Only one menu at a time; any outside pointer-down,
  // Esc, or any scroll closes it (scrolling would strand the fixed popup).
  const menu = ref(null) // { name: string, x: number, y: number } | null

  function openMenu(event, name) {
    if (menu.value?.name === name) {
      menu.value = null
      return
    }
    const rect = event.currentTarget.getBoundingClientRect()
    menu.value = { name, x: rect.left, y: rect.bottom + 4 }
  }

  function toggleMark() {
    onToggleMark(menu.value.name)
    menu.value = null
  }

  function onDocumentPointerDown(event) {
    if (menu.value && !event.target.closest('.wh-menu, .wh-menu-btn')) menu.value = null
  }
  function onDocumentKeydown(event) {
    if (event.key === 'Escape') menu.value = null
  }
  function onAnyScroll() {
    menu.value = null
    hoverTip.value = null
  }

  // --- warehouse name tooltip -------------------------------------------------
  // Headers show only the first 8 letters; hovering a truncated header pops the
  // full name. Teleported with FIXED coordinates (like the ⋮ menu) — an
  // absolutely-positioned tip would be clipped by the scroll container.
  const hoverTip = ref(null) // { name: string, x: number, y: number } | null

  function showNameTip(event, name) {
    if (name.length <= 8) return // nothing truncated — nothing to reveal
    const rect = event.currentTarget.getBoundingClientRect()
    hoverTip.value = { name, x: rect.left, y: rect.bottom + 4 }
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

  /** One row per size: label + per-warehouse quantities + the row total. */

  return { menu, openMenu, toggleMark, hoverTip, showNameTip, hideNameTip }
}
