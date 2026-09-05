<script setup>
/**
 * Inline editor for a test's rotation trigger.
 *
 * Its own component because the two triggers are mutually exclusive and the
 * form has to send only the one in force — the API refuses a body carrying the
 * other mode's setting rather than dropping it. Keeping that in one place stops
 * the rule from being re-derived wherever a trigger becomes editable.
 */
import { ref, watch } from 'vue'

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
  // Only the chosen mode's setting travels; sending both is a 422.
  emit('save', {
    trigger_mode: draft.value.trigger_mode,
    ...(draft.value.trigger_mode === 'impressions'
      ? { impression_budget: Number(draft.value.impression_budget) }
      : { slot_minutes: Number(draft.value.slot_minutes) }),
  })
}
</script>

<template>
  <div
    class="mt-md flex flex-wrap items-end gap-md rounded-card border border-border-subtle bg-surface p-md shadow-card"
  >
    <label class="block">
      <span class="text-tiny font-medium uppercase tracking-wide text-muted">Что меняет фото</span>
      <select
        v-model="draft.trigger_mode"
        data-testid="edit-trigger-mode"
        class="mt-xs rounded-control border border-border-subtle px-sm py-xs text-base"
      >
        <option value="impressions">По показам</option>
        <option value="time">По времени</option>
      </select>
    </label>
    <label v-if="draft.trigger_mode === 'impressions'" class="block">
      <span class="text-tiny font-medium uppercase tracking-wide text-muted">
        Показов на вариант
      </span>
      <input
        v-model="draft.impression_budget"
        data-testid="edit-impression-budget"
        inputmode="numeric"
        class="mt-xs rounded-control border border-border-subtle px-sm py-xs text-base tabular-nums"
      />
    </label>
    <label v-else class="block">
      <span class="text-tiny font-medium uppercase tracking-wide text-muted">
        Минут на вариант
      </span>
      <input
        v-model="draft.slot_minutes"
        data-testid="edit-slot-minutes"
        inputmode="numeric"
        class="mt-xs rounded-control border border-border-subtle px-sm py-xs text-base tabular-nums"
      />
    </label>
    <button
      type="button"
      class="rounded-control bg-action px-md py-sm text-base font-medium text-white hover:opacity-90 disabled:opacity-50"
      :disabled="saving"
      data-testid="save-trigger"
      @click="save"
    >
      Сохранить
    </button>
    <button
      type="button"
      class="rounded-control border border-border-subtle px-md py-sm text-base text-primary hover:bg-zebra"
      @click="emit('cancel')"
    >
      Отмена
    </button>
    <p class="w-full text-base text-muted">
      Новый триггер читается ближайшим проходом. Если снизить бюджет ниже того, что текущее фото уже
      набрало, оно сменится в течение нескольких минут; в режиме «по времени» слот считается с
      момента установки фото, а не с момента правки.
    </p>
  </div>
</template>
