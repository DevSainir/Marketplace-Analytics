<script setup>
/**
 * Inline editor for a test's rotation trigger.
 *
 * Its own component because the form has to send only the settings the chosen
 * mode reads — the API refuses a body carrying one it would not — and because
 * a trigger becomes editable in more than one place. Which fields those are
 * lives in `trigger.js`, alongside the create form's copy of the same question.
 */
import { ref, watch } from 'vue'

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

function save() {
  // Only what the chosen mode reads travels; sending anything else is a 422.
  emit('save', triggerPayload(draft.value))
}
</script>

<template>
  <div class="mt-md flex flex-wrap items-end gap-md rounded-card bg-surface p-md shadow-card">
    <label class="block">
      <span class="text-tiny font-medium uppercase tracking-wide text-muted">Что меняет фото</span>
      <select
        v-model="draft.trigger_mode"
        data-testid="edit-trigger-mode"
        class="mt-xs h-10 rounded-input bg-surface px-md text-base text-primary shadow-soft focus:outline-none focus:ring-2 focus:ring-action/20"
      >
        <option v-for="mode in TRIGGER_MODES" :key="mode.value" :value="mode.value">
          {{ mode.label }}
        </option>
      </select>
    </label>
    <label v-if="usesBudget(draft.trigger_mode)" class="block">
      <span class="text-tiny font-medium uppercase tracking-wide text-muted">
        Показов на вариант
      </span>
      <input
        v-model="draft.impression_budget"
        data-testid="edit-impression-budget"
        inputmode="numeric"
        class="mt-xs h-10 rounded-input bg-surface px-md text-base tabular-nums text-primary shadow-soft focus:outline-none focus:ring-2 focus:ring-action/20"
      />
    </label>
    <label v-if="usesSlot(draft.trigger_mode)" class="block">
      <span class="text-tiny font-medium uppercase tracking-wide text-muted">
        Минут на вариант
      </span>
      <input
        v-model="draft.slot_minutes"
        data-testid="edit-slot-minutes"
        inputmode="numeric"
        class="mt-xs h-10 rounded-input bg-surface px-md text-base tabular-nums text-primary shadow-soft focus:outline-none focus:ring-2 focus:ring-action/20"
      />
    </label>
    <button
      type="button"
      class="inline-flex h-10 items-center justify-center rounded-btn bg-action px-lg text-base font-semibold text-white shadow-soft transition hover:bg-action-hover disabled:opacity-50"
      :disabled="saving"
      data-testid="save-trigger"
      @click="save"
    >
      Сохранить
    </button>
    <button
      type="button"
      class="inline-flex h-10 items-center justify-center rounded-btn bg-surface px-lg text-base font-medium text-primary shadow-soft transition hover:bg-hover"
      @click="emit('cancel')"
    >
      Отмена
    </button>
    <p class="w-full text-tiny text-muted">
      Новый триггер читается ближайшим проходом. Если снизить бюджет ниже того, что текущее фото уже
      набрало за свой ход, оно сменится в течение нескольких минут; слот считается с момента
      установки фото, а не с момента правки. В режиме «показы и время» фото меняется по тому
      условию, которое наступит раньше.
    </p>
  </div>
</template>
