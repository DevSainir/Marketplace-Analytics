/**
 * Everything the daily metrics table needs to be editable: the rows it renders,
 * whether editing is currently locked, the three commits it can make, and the
 * undo/redo keys.
 *
 * Extracted from `MonitoringView` because none of it is about the page — it is
 * one surface (the workbook table) and its whole conversation with the store.
 * The view had grown to the 250-line component limit with this wiring taking a
 * fifth of it, and what was left buried the part that IS the page: the search,
 * the identity header, and the sections under it.
 *
 * A thin layer on purpose. Every value here is the store's and every commit
 * goes straight back to it: the backend owns the arithmetic (a cell edit
 * back-solves and recomputes dependents server-side), so there is nothing to
 * calculate on the way through.
 */
import { computed } from 'vue'

import { useHistoryKeys } from '@/core/utils/historyKeys'

/**
 * @param {object} store The monitoring store.
 * @returns {{
 *   matrix: import('vue').ComputedRef<object>,
 *   editingLocked: import('vue').ComputedRef<boolean>,
 *   onCellEdit: (edit: object) => void,
 *   onCommentEdit: (payload: {day: string, patch: object}) => void,
 *   onActionEdit: (payload: {day: string, patch: object}) => void,
 * }}
 */
export function useMatrixEditing(store) {
  // Metric rows × day columns (the workbook replica). The store owns this
  // reactive structure and patches cells in place on edit/undo/redo, so the
  // table re-renders a handful of nodes rather than thousands.
  const matrix = computed(() => store.matrixView)

  /** Editing is locked while a save or a WB refresh is in flight. */
  const editingLocked = computed(() => store.matrixSaving || store.matrixRefreshing)

  /** A cell edit: hand the raw value over; the backend recomputes dependents. */
  function onCellEdit(edit) {
    store.applyCellEdit(edit)
  }

  // Day notes live per DAY inside the table's collapsible "Comments" row, so
  // this only forwards the commit. The patch carries just the edited field —
  // header and comment save independently.
  function onCommentEdit({ day, patch }) {
    store.saveDayComment(day, patch)
  }

  // The per-day ad campaign/price answers have their own row; each partial change is
  // forwarded and the store merges then saves.
  function onActionEdit({ day, patch }) {
    store.saveDayAction(day, patch)
  }

  // Ctrl/Cmd+Z undoes, Ctrl/Cmd+Shift+Z (or Ctrl/Cmd+Y) redoes. Ignored while
  // typing in an input and while a save or refresh is running.
  useHistoryKeys({
    undo: () => store.canUndoMatrix && store.undoMatrixEdit(),
    redo: () => store.canRedoMatrix && store.redoMatrixEdit(),
    locked: () => editingLocked.value,
  })

  return { matrix, editingLocked, onCellEdit, onCommentEdit, onActionEdit }
}
