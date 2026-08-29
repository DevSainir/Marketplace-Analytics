/**
 * Drag-to-reorder for a list rendered as a strip of draggable items.
 *
 * Reports the WHOLE new order rather than a moved index, because the backend
 * rejects an order computed against a list a teammate has since changed — so
 * the caller has to send the list it actually saw.
 *
 * Extracted from `PinnedSkuRow`: the HTML5 drag dance (a source index, a hover
 * target, and resetting both on every exit path) is the same wherever it is
 * used and is not about pinned SKUs.
 */
import { ref } from 'vue'

/**
 * @param {object} options
 * @param {() => Array<object>} options.items Current list, in display order.
 * @param {(order: Array<object>) => void} options.onReorder Called with the
 *   full reordered list once a drop lands somewhere new.
 */
export function useDragReorder({ items, onReorder }) {
  // --- drag to reorder ------------------------------------------------------
  // Native HTML5 drag-and-drop: no dependency, and the browser suppresses the
  // click that ends a drag, so a reorder can't fall through to `select`.
  const dragIndex = ref(null)
  const dropIndex = ref(null)

  function handleDragStart(index, event) {
    dragIndex.value = index
    event.dataTransfer.effectAllowed = 'move'
    // Firefox refuses to start a drag unless the payload is set.
    event.dataTransfer.setData('text/plain', String(items()[index].nm_id))
  }

  function handleDragOver(index, event) {
    if (dragIndex.value === null) return
    // preventDefault is what marks this chip as a valid drop target.
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
    dropIndex.value = index
  }

  function handleDrop(index) {
    const from = dragIndex.value
    resetDrag()
    if (from === null || from === index) return
    const order = items().map((item) => item.nm_id)
    const [moved] = order.splice(from, 1)
    order.splice(index, 0, moved)
    onReorder(order)
  }

  function resetDrag() {
    dragIndex.value = null
    dropIndex.value = null
  }

  /** A pin chip shows the vendor code when the catalogue is synced, nm ID otherwise. */

  return { dragIndex, dropIndex, handleDragStart, handleDragOver, handleDrop, resetDrag }
}
