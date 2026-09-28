<script setup>
/**
 * The hover card over a campaign link in the matrix header: the campaign's id,
 * selectable with one click and copyable with a button — the way to find the
 * campaign by hand if WB ever changes the link's URL shape (see
 * `campaignLinks.js`). Stays open while the pointer is on it.
 */
import { ref, watch } from 'vue'

const props = defineProps({
  /** @type {{id: number, x: number, y: number}|null} */
  tip: { type: Object, default: null },
})

defineEmits(['keep', 'leave'])

const idEl = ref(null)
/** '' | 'copied' | 'selected' — what the button last managed. */
const outcome = ref('')

watch(
  () => props.tip?.id,
  () => {
    outcome.value = ''
  },
)

/** Select the id on the page, so ⌘C works whatever the clipboard API allows. */
function selectId() {
  const range = document.createRange()
  range.selectNodeContents(idEl.value)
  const selection = window.getSelection()
  selection.removeAllRanges()
  selection.addRange(range)
}

async function copy() {
  try {
    await navigator.clipboard.writeText(String(props.tip.id))
    outcome.value = 'copied'
    return
  } catch {
    // The async clipboard is refused in some contexts (an embedded browser, a
    // denied permission). The old selection-based copy often still works there.
  }
  selectId()
  outcome.value = document.execCommand?.('copy') ? 'copied' : 'selected'
}

const LABEL = { '': 'Копировать', copied: 'Скопировано', selected: 'Выделено — ⌘C' }
</script>

<template>
  <Teleport to="body">
    <div
      v-if="tip"
      class="fixed z-50 flex items-center gap-sm rounded-card border border-border-subtle bg-surface px-sm py-xs text-tiny text-primary shadow-card"
      :style="{ left: `${tip.x}px`, top: `${tip.y}px` }"
      @mouseenter="$emit('keep')"
      @mouseleave="$emit('leave')"
    >
      <span class="text-muted">ID РК</span>
      <span ref="idEl" class="select-all font-semibold tabular-nums">{{ tip.id }}</span>
      <button
        type="button"
        class="rounded-btn px-xs font-medium text-action transition hover:bg-action/10"
        @click="copy"
      >
        {{ LABEL[outcome] }}
      </button>
    </div>
  </Teleport>
</template>
