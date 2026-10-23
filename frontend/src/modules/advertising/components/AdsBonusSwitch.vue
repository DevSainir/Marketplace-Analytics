<script setup>
/**
 * "Promo bonuses" — the page-wide switch for WB's bonus money.
 *
 * A switch, not a checkbox or a chip: it changes how the whole page reads
 * (cards, table columns, chart line), and a sliding track is the control that
 * says "mode", where a chip reads as one more filter. It sits in the page
 * toolbar beside the period because it governs everything below it.
 *
 * It is the workspace's setting, not this browser's: flipping it changes the page
 * for everyone in the workspace, and it stays that way.
 *
 * Always switchable when the caller may change it: a window without bonuses
 * shows zeros, which says "there were no bonuses" better than a dead switch. Disabled
 * — with the reason on hover — only for a caller who may not change the
 * workspace's settings.
 */
import { computed } from 'vue'

import UiSwitch from '@/core/components/UiSwitch.vue'

const props = defineProps({
  on: { type: Boolean, required: true },
  /** The caller may not change the workspace's settings (read-only, or a guest). */
  locked: { type: Boolean, default: false },
})

const emit = defineEmits(['update:on'])

const why = computed(() => {
  if (props.locked) return 'Only a member with write access can change this workspace setting'
  return 'Workspace setting: changes it for every member'
})
</script>

<template>
  <button
    type="button"
    role="switch"
    :aria-checked="on"
    :disabled="locked"
    :title="why"
    class="inline-flex items-center gap-sm rounded-btn px-sm py-xs text-base text-primary transition enabled:hover:bg-hover disabled:cursor-not-allowed disabled:opacity-50 phone:min-h-11"
    @click="emit('update:on', !on)"
  >
    <UiSwitch :on="on" />
    Promo bonuses
  </button>
</template>
