/**
 * Inline cell editing for the metrics table.
 *
 * A composable rather than a mixin or duplicated state because TWO components
 * edit cells of the same table — `MetricsTable` for the metric rows and
 * `MatrixDayBlocksRow` for the «Цены» block — and they must behave identically:
 * same commit rules, same comma handling, same no-op suppression. The editing
 * state itself is per-component (only one cell is ever open in each), so each
 * caller gets its own instance.
 *
 * A cell is addressed by a STABLE id built from its coordinates, not by object
 * identity: the matrix is patched in place on every edit, so the object under
 * the cursor is not the same object it was a moment ago.
 */
import { ref } from 'vue'

/**
 * @param {object} options
 * @param {() => boolean} options.disabled Whether editing is currently blocked
 *   (a save or refresh in flight).
 * @param {(payload: {day: string, bucket: string, metric: string, value: number}) => void}
 *   options.onCommit Called with the parsed value once an edit is accepted.
 */
export function useCellEditing({ disabled, onCommit }) {
  /** The cell currently being edited, addressed by its stable id. */
  const editingId = ref(null)
  const draft = ref('')

  function cellId(rowKey, cell) {
    return `${cell.day}:${cell.bucket}:${rowKey}`
  }

  function startEdit(row, cell) {
    if (disabled() || !cell.editable) return
    editingId.value = cellId(row.key, cell)
    draft.value = cell.raw == null ? '' : String(cell.raw)
  }

  function commitEdit(row, cell) {
    if (editingId.value !== cellId(row.key, cell)) return
    const raw = draft.value.trim().replace(',', '.')
    const value = Number(raw)
    editingId.value = null
    // Ignore empty/invalid input or a no-op (unchanged value).
    if (raw === '' || Number.isNaN(value) || value === cell.raw) return
    onCommit({ day: cell.day, bucket: cell.bucket, metric: cell.metric, value })
  }

  function cancelEdit() {
    editingId.value = null
  }

  return { editingId, draft, cellId, startEdit, commitEdit, cancelEdit }
}

/**
 * Focus (and select) the inline input the moment it appears.
 *
 * So typing lands in it and — crucially — clicking anywhere outside blurs it,
 * committing and closing. A plain `autofocus` attribute does nothing on a
 * dynamically inserted node.
 */
export const vFocus = {
  mounted(el) {
    el.focus()
    el.select()
  },
}
