<script setup>
/**
 * «Промо-бонусы» — the page-wide switch for WB's bonus money.
 *
 * A switch, not a checkbox or a chip: it changes how the whole page reads
 * (cards, table columns, chart line), and a sliding track is the control that
 * says «режим», where a chip reads as one more filter. It sits in the page
 * toolbar beside the period because it governs everything below it.
 *
 * It is the кабинет's setting, not this browser's: flipping it changes the page
 * for everyone in the кабинет, and it stays that way.
 *
 * Disabled — with the reason on hover — when the window holds no bonus at
 * all (switching a zero on and off would be a control that does nothing), and
 * for a caller who may not change the кабинет's settings.
 */
import { computed } from 'vue'

const props = defineProps({
  on: { type: Boolean, required: true },
  /** Whether the window carries any WB-funded spend. */
  available: { type: Boolean, default: true },
  /** The caller may not change the кабинет's settings (read-only, or a guest). */
  locked: { type: Boolean, default: false },
})

const emit = defineEmits(['update:on'])

const why = computed(() => {
  if (!props.available) return 'В этом периоде WB не оплачивал рекламу бонусами'
  if (props.locked) return 'Настройку кабинета меняет участник с правом записи'
  return 'Настройка кабинета: меняется для всех его участников'
})
</script>

<template>
  <button
    type="button"
    role="switch"
    :aria-checked="on && available"
    :disabled="!available || locked"
    :title="why"
    class="inline-flex items-center gap-sm rounded-btn px-sm py-xs text-base text-primary transition enabled:hover:bg-hover disabled:cursor-not-allowed disabled:opacity-50 phone:min-h-11"
    @click="emit('update:on', !on)"
  >
    <span
      class="relative inline-flex h-5 w-9 flex-none items-center rounded-full transition"
      :class="on && available ? 'bg-action' : 'bg-border-strong/30'"
    >
      <span
        class="absolute left-0.5 h-4 w-4 rounded-full bg-white shadow-soft transition-transform"
        :class="on && available ? 'translate-x-4' : 'translate-x-0'"
      />
    </span>
    Промо-бонусы
  </button>
</template>
