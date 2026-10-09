<script setup>
/**
 * The app's one modal: a centred panel over a dimmed page, a title, a ✕,
 * Escape and the backdrop to close, and the actions at the bottom right —
 * «Отмена» first, the main action last.
 *
 * There were three, all different: a glass panel with a dark scrim and no ✕
 * (finishing an A/B test), a solid one over a light scrim whose buttons were
 * filter chips (a heatmap group), and the profile's side drawer with yet
 * another scrim. What a dialog asks is its own; how it opens, closes and sits
 * over the page is this file's. (The drawer stays a drawer — it is a panel of
 * settings, not a question — but shares the scrim.)
 *
 * `busy` holds it open: closing mid-write would hide the outcome of the very
 * thing the reader asked for.
 */
import { onBeforeUnmount, onMounted, watch } from 'vue'

// Attributes (a `data-testid`) belong on the panel, not on the Teleport.
defineOptions({ inheritAttrs: false })

const props = defineProps({
  open: { type: Boolean, required: true },
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
  /** A write is in flight: the dialog cannot be closed. */
  busy: { type: Boolean, default: false },
  /** `md` (32rem) for a form, `lg` (56rem) for a choice laid out in a grid. */
  size: { type: String, default: 'md' },
})
const emit = defineEmits(['close'])

function close() {
  if (!props.busy) emit('close')
}
function onKey(event) {
  if (event.key === 'Escape' && props.open) close()
}

watch(
  () => props.open,
  (open) => (document.body.style.overflow = open ? 'hidden' : ''),
  { immediate: true },
)
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  document.body.style.overflow = ''
})
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="ui-dialog-root">
      <div class="ui-dialog-scrim" data-testid="dialog-scrim" @click="close" />

      <section
        class="ui-dialog ui-glass ui-glass--pop"
        :class="size === 'lg' ? 'max-w-4xl' : 'max-w-lg'"
        role="dialog"
        aria-modal="true"
        :aria-label="title"
        v-bind="$attrs"
      >
        <header class="flex items-start gap-md px-lg pb-md pt-lg">
          <div class="min-w-0 flex-1">
            <h2 class="text-h3 font-semibold text-primary">{{ title }}</h2>
            <p v-if="subtitle" class="mt-xs text-tiny font-medium text-muted">{{ subtitle }}</p>
          </div>
          <button
            type="button"
            class="ui-icon-btn -mr-xs -mt-xs"
            aria-label="Закрыть"
            :disabled="busy"
            @click="close"
          >
            <svg
              class="h-4 w-4"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              aria-hidden="true"
            >
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </header>

        <div class="min-h-0 flex-1 overflow-y-auto px-lg pb-md">
          <slot />
        </div>

        <footer
          v-if="$slots.footer"
          class="flex flex-wrap items-center justify-end gap-sm border-t border-border-subtle px-lg py-md"
        >
          <slot name="footer" />
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped src="./styles/UiDialog.css"></style>
