<script setup>
/**
 * The «Новый тест» panel — name, article, and the one trigger that will move it.
 *
 * Its own component rather than markup inside the list view: the view was over
 * the 250-line ceiling with it inline, and the exclusivity rule below is the
 * same one `TriggerEditor` applies to a test that already exists.
 */
import { computed, ref } from 'vue'

import SkuPicker from '@/modules/abTests/components/SkuPicker.vue'

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

function submit() {
  // Exactly one trigger travels. The backend REFUSES a body carrying the other
  // mode's setting rather than ignoring it, so sending both would 422 — and
  // that refusal is deliberate: "10 000 impressions or 2 hours, whichever
  // first" would measure the photos over different exposures.
  emit('submit', {
    name: form.value.name.trim(),
    nm_id: pickedSku.value.nm_id,
    trigger_mode: form.value.trigger_mode,
    ...(form.value.trigger_mode === 'impressions'
      ? { impression_budget: Number(form.value.impression_budget) }
      : { slot_minutes: Number(form.value.slot_minutes) }),
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
    class="mb-lg rounded-card bg-surface p-lg shadow-card phone:p-md"
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
          class="mt-xs h-11 w-full rounded-input bg-surface px-md text-base text-primary shadow-soft focus:outline-none focus:ring-2 focus:ring-action/20"
        >
          <option value="impressions">По показам</option>
          <option value="time">По времени</option>
        </select>
      </label>

      <label v-if="form.trigger_mode === 'impressions'" class="block">
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
      <label v-else class="block">
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

    <div class="mt-lg flex flex-wrap items-center gap-sm">
      <button
        type="button"
        class="inline-flex h-11 items-center justify-center rounded-btn bg-action px-lg text-base font-semibold text-white shadow-soft transition hover:bg-action-hover disabled:cursor-not-allowed disabled:opacity-50"
        :disabled="saving || !ready"
        data-testid="create-test"
        @click="submit"
      >
        Создать
      </button>
      <button
        type="button"
        class="inline-flex h-11 items-center justify-center rounded-btn bg-surface px-lg text-base font-medium text-primary shadow-soft transition hover:bg-hover"
        @click="emit('cancel')"
      >
        Отмена
      </button>
    </div>
  </section>
</template>
