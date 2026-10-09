<script setup>
/**
 * The «Новый тест» panel — name, article, and the trigger that will move it.
 *
 * Its own component rather than markup inside the list view: the view was over
 * the 250-line ceiling with it inline. Which settings a mode sends is
 * `trigger.js`'s answer, the same one `TriggerEditor` applies to a test that
 * already exists.
 */
import { computed, ref } from 'vue'

import SkuPicker from '@/modules/abTests/components/SkuPicker.vue'
import { TRIGGER_MODES, triggerPayload, usesBudget, usesSlot } from '@/modules/abTests/trigger'

defineProps({
  /** Catalogue options for the article picker, as the store loaded them. */
  options: { type: Array, default: () => [] },
  /** True while the create request is in flight. */
  saving: { type: Boolean, default: false },
})
const emit = defineEmits(['submit', 'cancel', 'search'])

const EMPTY = { name: '', trigger_mode: 'impressions', impression_budget: 10000, slot_minutes: 60 }

const form = ref({ ...EMPTY })
const pickedSku = ref(null)

const ready = computed(() => !!form.value.name.trim() && !!pickedSku.value)

/** True in «показы и время», where the two bounds share one row of the grid. */
const bothBounds = computed(
  () => usesBudget(form.value.trigger_mode) && usesSlot(form.value.trigger_mode),
)

function submit() {
  // Only the settings the chosen mode reads travel. The backend REFUSES a body
  // carrying one it would not, rather than ignoring it — a dropped field would
  // leave the seller believing they configured something they did not.
  emit('submit', {
    name: form.value.name.trim(),
    nm_id: pickedSku.value.nm_id,
    ...triggerPayload(form.value),
  })
}

/** Called by the parent once the test was actually created. */
function reset() {
  form.value = { ...EMPTY }
  pickedSku.value = null
}

defineExpose({ reset })
</script>

<template>
  <section
    class="mb-lg rounded-card border border-border-subtle bg-surface p-lg shadow-card phone:p-md"
    aria-label="Новый A/Б-тест"
  >
    <h2 class="text-h3 font-semibold text-primary">Новый тест</h2>

    <div class="mt-md grid gap-md sm:grid-cols-2">
      <label class="block">
        <span class="text-tiny font-medium uppercase tracking-wide text-muted">Название</span>
        <input
          v-model="form.name"
          data-testid="test-name"
          class="mt-xs h-11 w-full rounded-input bg-surface px-md text-base text-primary shadow-soft placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-action/20"
          placeholder="Тест главного фото"
        />
      </label>

      <SkuPicker v-model="pickedSku" :options="options" @search="emit('search', $event)" />

      <label class="block">
        <span class="text-tiny font-medium uppercase tracking-wide text-muted">
          Что меняет фото
        </span>
        <select
          v-model="form.trigger_mode"
          data-testid="trigger-mode"
          class="ui-select-arrow mt-xs h-11 w-full rounded-input bg-surface pl-md pr-11 text-base text-primary shadow-soft focus:outline-none focus:ring-2 focus:ring-action/20"
        >
          <option v-for="mode in TRIGGER_MODES" :key="mode.value" :value="mode.value">
            {{ mode.label }}
          </option>
        </select>
      </label>

      <!-- Both bounds live in ONE cell of the grid, side by side when the mode
           reads both. They are one setting — «столько показов или столько
           минут» — and on two rows they read as two, while a 5-item grid of
           2 columns leaves the second one alone on a row of its own. -->
      <div class="grid gap-sm" :class="bothBounds ? 'grid-cols-2' : 'grid-cols-1'">
        <label v-if="usesBudget(form.trigger_mode)" class="block">
          <span class="text-tiny font-medium uppercase tracking-wide text-muted">
            Показов на вариант
          </span>
          <input
            v-model="form.impression_budget"
            data-testid="impression-budget"
            inputmode="numeric"
            class="mt-xs h-11 w-full rounded-input bg-surface px-md text-base tabular-nums text-primary shadow-soft focus:outline-none focus:ring-2 focus:ring-action/20"
          />
        </label>
        <label v-if="usesSlot(form.trigger_mode)" class="block">
          <span class="text-tiny font-medium uppercase tracking-wide text-muted">
            Минут на вариант
          </span>
          <input
            v-model="form.slot_minutes"
            data-testid="slot-minutes"
            inputmode="numeric"
            class="mt-xs h-11 w-full rounded-input bg-surface px-md text-base tabular-nums text-primary shadow-soft focus:outline-none focus:ring-2 focus:ring-action/20"
          />
        </label>
      </div>
    </div>

    <div class="mt-lg flex flex-wrap items-center gap-sm">
      <button
        type="button"
        class="ui-btn ui-btn--primary"
        :disabled="saving || !ready"
        data-testid="create-test"
        @click="submit"
      >
        {{ saving ? 'Создаём…' : 'Создать' }}
      </button>
      <button type="button" class="ui-btn" @click="emit('cancel')">Отмена</button>
    </div>
  </section>
</template>
