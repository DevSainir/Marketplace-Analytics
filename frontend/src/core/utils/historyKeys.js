/**
 * Ctrl+Z / Ctrl+Shift+Z (and Ctrl+Y) for a page's own edit history — the
 * monitoring matrix, and the heatmap's hand-set norms.
 *
 * Bound on `window` rather than on the table, because the shortcut has to work
 * wherever focus happens to be after an edit — including right after a cell
 * input blurs, when nothing in the table is focused at all.
 *
 * Extracted from `MonitoringView` because it is a keyboard binding with its own
 * lifecycle, not part of what the page is about; in core since a second page
 * wanted the same shortcut.
 */
import { onBeforeUnmount, onMounted } from 'vue'

/**
 * @param {object} options
 * @param {() => void} options.undo
 * @param {() => void} options.redo
 * @param {() => boolean} options.locked Whether editing is currently blocked
 *   (a save or WB refresh in flight) — the shortcut must not race those.
 */
export function useHistoryKeys({ undo, redo, locked }) {
  function handleHistoryKey(event) {
    if (!(event.ctrlKey || event.metaKey)) return
    const key = event.key.toLowerCase()
    const isUndo = key === 'z' && !event.shiftKey
    const isRedo = (key === 'z' && event.shiftKey) || key === 'y'
    if (!isUndo && !isRedo) return

    // Inside a text field the combo means that field's own undo, not the table's.
    const tag = event.target?.tagName
    if (tag === 'INPUT' || tag === 'TEXTAREA') return
    if (locked()) return

    // Always swallow the combo while the page has it — otherwise a second
    // Ctrl+Z with an empty history falls through to the browser's own undo,
    // which moves focus into the search input.
    event.preventDefault()
    if (isRedo) redo()
    else undo()
  }

  onMounted(() => window.addEventListener('keydown', handleHistoryKey))
  onBeforeUnmount(() => window.removeEventListener('keydown', handleHistoryKey))
}
