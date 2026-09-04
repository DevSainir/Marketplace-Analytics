<script setup>
/**
 * A/Б-тесты — the list of photo-rotation tests.
 *
 * One row per test, mirroring the seller cabinet's own list, with two
 * deliberate differences. There are no «А» and «Б» columns: a rotation runs up
 * to ten photos, so the thumbnails are a strip rather than two fixed slots. And
 * there are no filters — the search box already matches the name, both articles
 * and the status, so a filter panel would be a second way to do the same thing.
 */
import { onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import { STATUS_LABELS, useAbTestsStore } from '@/modules/abTests'

const store = useAbTestsStore()
const router = useRouter()

const creating = ref(false)
const form = ref({
  name: '',
  nm_id: '',
  vendor_code: '',
  trigger_mode: 'impressions',
  impression_budget: 10000,
  slot_minutes: 60,
})

onMounted(() => store.loadTests())

/** Chip colour per status — running is the only one worth highlighting. */
const STATUS_CLASS = {
  draft: 'bg-zebra text-muted',
  running: 'bg-status-positive/10 text-status-positive',
  paused: 'bg-status-warning/10 text-status-warning',
  completed: 'bg-status-positive/10 text-status-positive',
  cancelled: 'bg-zebra text-muted',
}

function formatDate(value) {
  return value ? new Date(value).toLocaleDateString('ru-RU') : '—'
}

async function submit() {
  // Exactly one trigger travels. The backend REFUSES a body carrying the other
  // mode's setting rather than ignoring it, so sending both would 422 — and
  // that refusal is deliberate: "10 000 impressions or 2 hours, whichever
  // first" would measure the photos over different exposures.
  const created = await store.create({
    name: form.value.name.trim(),
    nm_id: Number(form.value.nm_id),
    vendor_code: form.value.vendor_code.trim(),
    trigger_mode: form.value.trigger_mode,
    ...(form.value.trigger_mode === 'impressions'
      ? { impression_budget: Number(form.value.impression_budget) }
      : { slot_minutes: Number(form.value.slot_minutes) }),
  })
  if (created) {
    creating.value = false
    form.value = {
      name: '',
      nm_id: '',
      vendor_code: '',
      trigger_mode: 'impressions',
      impression_budget: 10000,
      slot_minutes: 60,
    }
    router.push({ name: 'ab-test-detail', params: { testId: created.id } })
  }
}
</script>

<template>
  <main class="app-container py-xl phone:py-lg">
    <header class="mb-lg flex flex-wrap items-center gap-md">
      <h1 class="text-h2 font-bold text-primary">A/Б-тесты</h1>
      <button
        type="button"
        class="rounded-control bg-action px-md py-sm text-base font-medium text-white hover:opacity-90"
        data-testid="new-test"
        @click="creating = !creating"
      >
        + Тест
      </button>
      <p class="text-base text-muted">
        Фото меняется автоматически — либо когда вариант наберёт свои
        <b>рекламные показы</b>, либо через заданное <b>время</b>. Одно из двух, не оба сразу.
        Данные снимаются каждые несколько минут, поэтому смена может происходить по нескольку раз в
        день. Органических показов WB через API не отдаёт, так что режим «по показам» идёт, пока по
        карточке крутится реклама.
      </p>
    </header>

    <section
      v-if="creating"
      class="mb-lg rounded-card border border-border-subtle bg-surface p-lg shadow-card phone:p-md"
    >
      <div class="grid gap-md sm:grid-cols-2">
        <label class="block">
          <span class="text-tiny font-medium uppercase tracking-wide text-muted">Название</span>
          <input
            v-model="form.name"
            data-testid="test-name"
            class="mt-xs w-full rounded-control border border-border-subtle px-sm py-xs text-base"
            placeholder="Тест главного фото"
          />
        </label>
        <label class="block">
          <span class="text-tiny font-medium uppercase tracking-wide text-muted">Артикул WB</span>
          <input
            v-model="form.nm_id"
            data-testid="test-nm-id"
            inputmode="numeric"
            class="mt-xs w-full rounded-control border border-border-subtle px-sm py-xs text-base tabular-nums"
            placeholder="995716075"
          />
        </label>
        <label class="block">
          <span class="text-tiny font-medium uppercase tracking-wide text-muted">
            Артикул продавца
          </span>
          <input
            v-model="form.vendor_code"
            class="mt-xs w-full rounded-control border border-border-subtle px-sm py-xs text-base"
            placeholder="ДЕТ_ПЛАТЬЕ_ЦВЕТОЧЕК"
          />
        </label>
        <label class="block">
          <span class="text-tiny font-medium uppercase tracking-wide text-muted">
            Что меняет фото
          </span>
          <select
            v-model="form.trigger_mode"
            data-testid="trigger-mode"
            class="mt-xs w-full rounded-control border border-border-subtle px-sm py-xs text-base"
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
            class="mt-xs w-full rounded-control border border-border-subtle px-sm py-xs text-base tabular-nums"
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
            class="mt-xs w-full rounded-control border border-border-subtle px-sm py-xs text-base tabular-nums"
          />
        </label>
      </div>
      <button
        type="button"
        class="mt-md rounded-control bg-action px-md py-sm text-base font-medium text-white hover:opacity-90 disabled:opacity-50"
        :disabled="store.saving || !form.name.trim() || !form.nm_id"
        data-testid="create-test"
        @click="submit"
      >
        Создать
      </button>
    </section>

    <div class="mb-md">
      <input
        :value="store.query"
        data-testid="search"
        class="w-full max-w-lg rounded-control border border-border-subtle bg-surface px-md py-sm text-base"
        placeholder="Название теста, артикул продавца или WB"
        @input="store.search($event.target.value)"
      />
    </div>

    <p v-if="store.error" class="mb-md text-base text-status-negative">{{ store.error }}</p>

    <section class="rounded-card border border-border-subtle bg-surface shadow-card">
      <table class="app-datatable w-full">
        <thead>
          <tr class="text-left text-tiny font-medium uppercase tracking-wide text-muted">
            <th class="px-lg py-md">Тест</th>
            <th class="px-lg py-md">Фото</th>
            <th class="px-lg py-md">Статус</th>
            <th class="px-lg py-md">Дата запуска</th>
            <th class="px-lg py-md">Дата окончания</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="test in store.rows" :key="test.id" class="border-t border-border-subtle">
            <td class="px-lg py-md">
              <RouterLink
                :to="{ name: 'ab-test-detail', params: { testId: test.id } }"
                class="text-base font-medium text-action hover:underline"
                data-testid="test-link"
              >
                {{ test.nm_id }} {{ test.name }}
              </RouterLink>
              <div class="mt-xs text-tiny text-muted">WB артикул: {{ test.nm_id }}</div>
              <div v-if="test.vendor_code" class="text-tiny text-muted">
                Артикул продавца: {{ test.vendor_code }}
              </div>
              <div class="text-tiny text-muted">
                Дата создания: {{ formatDate(test.created_at) }}
              </div>
            </td>
            <td class="px-lg py-md text-base tabular-nums text-muted">
              {{ test.variant_count }} шт
            </td>
            <td class="px-lg py-md">
              <span
                class="rounded-control px-sm py-xs text-tiny font-medium"
                :class="STATUS_CLASS[test.status]"
              >
                {{ STATUS_LABELS[test.status] || test.status }}
              </span>
            </td>
            <td class="px-lg py-md text-base tabular-nums">{{ formatDate(test.started_at) }}</td>
            <td class="px-lg py-md text-base tabular-nums">{{ formatDate(test.finished_at) }}</td>
          </tr>
          <tr v-if="!store.loading && !store.rows.length">
            <td colspan="5" class="px-lg py-xl text-center text-base text-muted">
              Тестов пока нет. Создайте первый — загрузите до 10 вариантов главного фото, и они
              будут сменять друг друга по мере набора показов.
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  </main>
</template>
