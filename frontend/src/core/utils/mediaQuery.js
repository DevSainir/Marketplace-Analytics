/**
 * A reactive `matchMedia`, for the few layouts that cannot be a CSS class.
 *
 * The calendar draws one month or two, and that is a number of grids rather
 * than a style, so it has to be known in script. Starts `false` and settles on
 * mount; where `matchMedia` does not exist (the unit tier's DOM) it stays
 * `false`, which is the desktop layout.
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'

/**
 * @param {string} query A media query, e.g. `(max-width: 639px)`.
 * @returns {import('vue').Ref<boolean>} Whether it currently matches.
 */
export function useMediaQuery(query) {
  const matches = ref(false)
  let list = null
  const update = () => (matches.value = Boolean(list?.matches))

  onMounted(() => {
    if (typeof window.matchMedia !== 'function') return
    list = window.matchMedia(query)
    update()
    list.addEventListener('change', update)
  })
  onBeforeUnmount(() => list?.removeEventListener('change', update))

  return matches
}
