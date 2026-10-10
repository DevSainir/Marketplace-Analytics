/**
 * The stock breakdown table's full-warehouse-name tooltip.
 *
 * A warehouse column header shows only the first 8 letters — there is no room
 * for «Санкт-Петербург Уткина Заводь» above a numeric column — so hovering a
 * truncated header pops the full name. Teleported and positioned `fixed`, which
 * is what an absolutely-positioned tip inside the scroll container cannot be
 * without being clipped by it; being `fixed`, it must close on ANY scroll, or
 * it strands itself over unrelated content.
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'

import { visibleArea } from '@/core/utils/tipFit'

export function useWarehouseNameTip() {
  const hoverTip = ref(null) // { name, x, y, area } | null

  function showNameTip(event, name) {
    if (name.length <= 8) return // nothing truncated — nothing to reveal
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

  onMounted(() => document.addEventListener('scroll', hideNameTip, true))
  onBeforeUnmount(() => document.removeEventListener('scroll', hideNameTip, true))

  return { hoverTip, showNameTip, hideNameTip }
}
