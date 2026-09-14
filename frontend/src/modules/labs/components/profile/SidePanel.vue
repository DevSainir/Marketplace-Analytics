<script setup>
/**
 * Right-hand drawer — where the settings this page used to inline now live.
 *
 * The old profile page rendered every editor in place: four access controls
 * under each manager, thirteen password fields inside a list row. That made
 * the page's height a function of how many people and workspaces you have,
 * which is the one thing a control surface must not be. The lists stay lists;
 * editing one row opens here.
 *
 * Glass is allowed on this surface by the rule in the design-system skill —
 * chrome floating over scrolling content, nothing positioned inside it. It
 * takes the DENSE tier (0.97), not the transparent one: it carries forms.
 */
import { onBeforeUnmount, onMounted, watch } from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
})

const emit = defineEmits(['close'])

function onKey(event) {
  if (event.key === 'Escape' && props.open) emit('close')
}

/**
 * Lock the page behind the drawer. Without this the wheel scrolls the list
 * underneath, and closing the drawer leaves you somewhere you did not choose
 * to be.
 */
watch(
  () => props.open,
  (open) => {
    document.body.style.overflow = open ? 'hidden' : ''
  },
)

onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  document.body.style.overflow = ''
})
</script>

<template>
  <Teleport to="body">
    <Transition name="lp-drawer">
      <div v-if="open" class="lp-drawer-root">
        <div class="lp-drawer-scrim" @click="emit('close')" />

        <aside class="lp-drawer ui-glass ui-glass--pop" role="dialog" aria-modal="true">
          <header class="lp-drawer__head">
            <div class="min-w-0">
              <h2 class="truncate text-h3 font-semibold text-primary">{{ title }}</h2>
              <p v-if="subtitle" class="mt-xs truncate text-tiny font-medium text-muted">
                {{ subtitle }}
              </p>
            </div>
            <button
              type="button"
              class="lp-drawer__close"
              aria-label="Закрыть"
              @click="emit('close')"
            >
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
              >
                <path d="m6 6 12 12M18 6 6 18" />
              </svg>
            </button>
          </header>

          <div class="lp-drawer__body">
            <slot />
          </div>

          <footer v-if="$slots.footer" class="lp-drawer__foot">
            <slot name="footer" />
          </footer>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.lp-drawer-root {
  @apply fixed inset-0 z-50 flex justify-end;
}

.lp-drawer-scrim {
  @apply absolute inset-0;
  background: rgba(18, 18, 26, 0.28);
}

.lp-drawer {
  @apply relative flex h-full w-full max-w-[30rem] flex-col;
  border-left: 1px solid var(--ui-hairline);
  box-shadow: var(--ui-sh-lift);
}

.lp-drawer__head {
  @apply flex items-start justify-between gap-md px-lg py-md;
  border-bottom: 1px solid var(--ui-hairline);
}

.lp-drawer__close {
  @apply grid h-8 w-8 shrink-0 place-items-center rounded-btn transition;
  color: var(--ui-muted);
}

.lp-drawer__close:hover {
  background: var(--ui-sunk);
  color: var(--ui-ink);
}

.lp-drawer__close svg {
  @apply h-4 w-4;
}

.lp-drawer__body {
  @apply flex-1 overflow-y-auto px-lg py-lg;
}

.lp-drawer__foot {
  @apply px-lg py-md;
  border-top: 1px solid var(--ui-hairline);
}

.lp-drawer-enter-active,
.lp-drawer-leave-active {
  transition: opacity var(--ui-base) var(--ui-ease);
}

.lp-drawer-enter-active .lp-drawer,
.lp-drawer-leave-active .lp-drawer {
  transition: transform var(--ui-base) var(--ui-ease);
}

.lp-drawer-enter-from,
.lp-drawer-leave-to {
  opacity: 0;
}

.lp-drawer-enter-from .lp-drawer,
.lp-drawer-leave-to .lp-drawer {
  transform: translateX(100%);
}
</style>
