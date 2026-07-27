/**
 * The pinned-chip paint mode: pick a chip, then pick a colour.
 *
 * The palette being open IS the mode. Painting is two steps in this order:
 * first click a chip to pick WHICH pin to paint, then click a swatch to colour
 * it. The target stays selected after a swatch click, so its colour can be
 * tweaked, and any other chip can be picked next without leaving the mode.
 *
 * Extracted from `PinnedSkuRow` because it is a self-contained interaction
 * mode — an open/closed flag, a target, an anchor position, and the dismissal
 * listeners that go with any popover — sitting in a component whose real
 * subject is the chip row itself.
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'

/** Palette width in px; must match the `w-64` on the palette element. */
const PALETTE_WIDTH_PX = 256

/**
 * @param {object} options
 * @param {import('vue').Ref<HTMLElement|null>} options.root The row element the
 *   palette is positioned within and whose bounds dismiss it.
 * @param {() => Array<{nm_id: number, color: string|null}>} options.items The
 *   current pinned chips, used to resolve the target's stored colour.
 * @param {(nmId: number, color: string|null) => void} options.onRecolor
 *   Called when a swatch is picked for the current target.
 */
export function usePinPalette({ root, items, onRecolor }) {
  const paletteOpen = ref(false)
  const targetId = ref(null)

  // Left offset of the palette within `root` (px), clamped so it never spills
  // past the row's edges.
  const paletteLeft = ref(0)

  const targetItem = computed(() =>
    targetId.value === null ? null : (items().find((it) => it.nm_id === targetId.value) ?? null),
  )
  const targetColor = computed(() => targetItem.value?.color ?? null)

  function togglePalette() {
    paletteOpen.value = !paletteOpen.value
  }

  /** Line the palette up under the chip, then pull it back inside the row. */
  function anchorPaletteToChip(chipEl) {
    if (!root.value || !chipEl) return
    const rootRect = root.value.getBoundingClientRect()
    const chipRect = chipEl.getBoundingClientRect()
    const maxLeft = Math.max(0, root.value.clientWidth - PALETTE_WIDTH_PX)
    paletteLeft.value = Math.min(Math.max(0, chipRect.left - rootRect.left), maxLeft)
  }

  /**
   * Take a chip click while the mode is open.
   *
   * @returns {boolean} `true` when the click was consumed as a paint-target
   *   pick, `false` when the caller should handle it normally (analyze the SKU).
   */
  function claimChipClick(item, event) {
    if (!paletteOpen.value) return false
    targetId.value = item.nm_id
    anchorPaletteToChip(event.currentTarget)
    return true
  }

  /** Colour the chip picked for painting (color = null clears its tint). */
  function applyColor(color) {
    if (targetId.value === null) return
    onRecolor(targetId.value, color)
  }

  // Close on a click anywhere outside the row — but NOT on a chip click, which
  // is the whole point of the mode, and which lands inside this root.
  function handleOutsidePointer(event) {
    if (!root.value?.contains(event.target)) paletteOpen.value = false
  }

  function handleEscape(event) {
    if (event.key === 'Escape') paletteOpen.value = false
  }

  watch(paletteOpen, (open) => {
    // Leaving the mode forgets which chip was being painted.
    if (!open) targetId.value = null
    const method = open ? 'addEventListener' : 'removeEventListener'
    document[method]('pointerdown', handleOutsidePointer)
    document[method]('keydown', handleEscape)
  })

  onBeforeUnmount(() => {
    document.removeEventListener('pointerdown', handleOutsidePointer)
    document.removeEventListener('keydown', handleEscape)
  })

  return {
    paletteOpen,
    targetId,
    targetItem,
    targetColor,
    paletteLeft,
    togglePalette,
    claimChipClick,
    applyColor,
  }
}
