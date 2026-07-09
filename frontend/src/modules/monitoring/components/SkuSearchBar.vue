<script setup>
import { ref } from 'vue'

import { isoDaysAgo } from '@/core/utils/dates'

// Dumb component: it never fetches. It emits `search` and the smart view
// forwards the query to the store.
const props = defineProps({
  loading: { type: Boolean, default: false },
  initialQuery: { type: String, default: '' },
  initialDateFrom: { type: String, default: '' },
  initialDateTo: { type: String, default: '' },
})

const emit = defineEmits(['search'])

const query = ref(props.initialQuery)
// Inclusive window, mirrors the API's date_from / date_to query params.
const dateFrom = ref(props.initialDateFrom || isoDaysAgo(6))
const dateTo = ref(props.initialDateTo || isoDaysAgo(0))

function submit() {
  const sku = query.value.trim()
  if (!sku || !dateFrom.value || !dateTo.value) return
  emit('search', { sku, date_from: dateFrom.value, date_to: dateTo.value })
}
</script>

<template>
  <form
    class="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm lg:flex-row lg:items-center"
    @submit.prevent="submit"
  >
    <div class="relative flex-1">
      <svg
        class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
      >
        <circle cx="11" cy="11" r="7" />
        <path d="m20 20-3.5-3.5" />
      </svg>
      <input
        v-model="query"
        type="text"
        inputmode="numeric"
        placeholder="Поиск по SKU (nm ID) или артикулу продавца…"
        class="h-10 w-full rounded-lg border border-slate-200 bg-white pl-9 pr-3 text-sm text-slate-900 placeholder:text-slate-400 focus:border-indigo-600 focus:outline-none focus:ring-2 focus:ring-indigo-600/20"
      />
    </div>

    <fieldset class="flex items-center gap-2">
      <label class="flex items-center gap-2 text-sm text-slate-500">
        Период с
        <input
          v-model="dateFrom"
          type="date"
          required
          :max="dateTo"
          class="h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 focus:border-indigo-600 focus:outline-none focus:ring-2 focus:ring-indigo-600/20"
        />
      </label>
      <label class="flex items-center gap-2 text-sm text-slate-500">
        по
        <input
          v-model="dateTo"
          type="date"
          required
          :min="dateFrom"
          class="h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 focus:border-indigo-600 focus:outline-none focus:ring-2 focus:ring-indigo-600/20"
        />
      </label>
    </fieldset>

    <button
      type="submit"
      :disabled="loading"
      class="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-indigo-600 px-5 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-60"
    >
      <svg
        v-if="loading"
        class="h-4 w-4 animate-spin"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2.5"
        stroke-linecap="round"
      >
        <path d="M12 3a9 9 0 1 0 9 9" />
      </svg>
      {{ loading ? 'Загрузка…' : 'Анализировать' }}
    </button>
  </form>
</template>
