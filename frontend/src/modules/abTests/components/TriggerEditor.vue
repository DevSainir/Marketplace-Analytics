<script setup>
/**
 * Inline editor for a test's rotation trigger.
 *
 * Its own component because the form has to send only the settings the chosen
 * mode reads — the API refuses a body carrying one it would not — and because
 * a trigger becomes editable in more than one place. Which fields those are
 * lives in `trigger.js`, alongside the create form's copy of the same question.
 */
import { computed, ref, watch } from 'vue'

import { TRIGGER_MODES, triggerPayload, usesBudget, usesSlot } from '@/modules/abTests/trigger'

const props = defineProps({
  /** The test being edited, as the detail endpoint returns it. */
  test: { type: Object, required: true },
  /** True while a save is in flight. */
  saving: { type: Boolean, default: false },
})
const emit = defineEmits(['save', 'cancel'])

const draft = ref({ trigger_mode: 'impressions', impression_budget: 10000, slot_minutes: 60 })

watch(
  () => props.test,
  (test) => {
    draft.value = {
      trigger_mode: test.trigger_mode,
      impression_budget: test.impression_budget,
      slot_minutes: test.slot_minutes,
    }
  },
  { immediate: true },
)

/** True in "Impressions or time", where the two bounds share one line. */
const bothBounds = computed(
  () => usesBudget(draft.value.trigger_mode) && usesSlot(draft.value.trigger_mode),
)

function save() {
  // Only what the chosen mode reads travels; sending anything else is a 422.
  emit('save', triggerPayload(draft.value))
}
</script>

<template>
  <div
    class="mt-md flex flex-wrap items-end gap-md rounded-card border border-border-subtle bg-surface p-lg shadow-card phone:p-md"
  >
    <label class="block">
      <span class="block text-tiny font-medium uppercase tracking-wide text-muted"
        >What changes the photo</span
      >
      <select v-model="draft.trigger_mode" data-testid="edit-trigger-mode" class="ui-select mt-xs">
        <option v-for="mode in TRIGGER_MODES" :key="mode.value" :value="mode.value">
          {{ mode.label }}
        </option>
      </select>
    </label>
    <!-- Both bounds on one line, each half the width of a single one: they are
         one setting read as "this many impressions OR this many minutes", and the row
         already carries a mode select and two buttons to fit beside them. -->
    <div class="flex items-end gap-sm">
      <label v-if="usesBudget(draft.trigger_mode)" class="block">
        <span class="block text-tiny font-medium uppercase tracking-wide text-muted">
          Impressions per variant
        </span>
        <input
          v-model="draft.impression_budget"
          data-testid="edit-impression-budget"
          inputmode="numeric"
          class="ui-input mt-xs tabular-nums"
          :class="bothBounds ? 'w-24' : 'w-44'"
        />
      </label>
      <label v-if="usesSlot(draft.trigger_mode)" class="block">
        <span class="block text-tiny font-medium uppercase tracking-wide text-muted">
          Minutes per variant
        </span>
        <input
          v-model="draft.slot_minutes"
          data-testid="edit-slot-minutes"
          inputmode="numeric"
          class="ui-input mt-xs tabular-nums"
          :class="bothBounds ? 'w-24' : 'w-44'"
        />
      </label>
    </div>
    <button type="button" class="ui-btn" @click="emit('cancel')">Cancel</button>
    <button
      type="button"
      class="ui-btn ui-btn--primary"
      :disabled="saving"
      data-testid="save-trigger"
      @click="save"
    >
      {{ saving ? 'Saving…' : 'Save' }}
    </button>
    <p class="w-full text-tiny text-muted">
      The next pass picks up the new trigger (within 5 min).
    </p>
  </div>
</template>
