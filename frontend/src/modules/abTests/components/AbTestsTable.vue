<script setup>
/**
 * The list of tests, one row each.
 *
 * Mirrors the seller cabinet's own list with two deliberate differences. There
 * are no «А» and «Б» columns: a rotation runs up to ten photos, so the count is
 * a number rather than two fixed slots. And there are no filters — the search
 * box already matches the name, both articles and the status, so a filter panel
 * would be a second way to do the same thing.
 *
 * Deleting is a two-click confirm rather than a `window.confirm`, matching the
 * workspaces panel: the row itself asks, so there is no modal to mis-aim at the
 * wrong test. It is destructive — the photos go with the test — and it was
 * simply missing before, which is why a test could be created and never removed.
 */
import { ref } from 'vue'
import { RouterLink } from 'vue-router'

import { statusLabel } from '@/modules/abTests/store'
import { formatSku } from '@/core/utils/format'

defineProps({
  /** Tests as the store holds them. */
  rows: { type: Array, default: () => [] },
  /** True while the list is being (re)fetched. */
  loading: { type: Boolean, default: false },
  /** True while any write is in flight. */
  saving: { type: Boolean, default: false },
})
const emit = defineEmits(['delete'])

/**
 * Chip colour per status — running is the only one worth highlighting.
 *
 * The neutral statuses sit on `bg-surface` rather than on the hover fill: the
 * row's own hover tint IS that fill, so a «Черновик» chip disappeared into the
 * row the moment the cursor touched it.
 */
const STATUS_CLASS = {
  draft: 'bg-surface text-muted shadow-soft',
  running: 'bg-status-positive/10 text-status-positive',
  paused: 'bg-status-warning/10 text-status-warning',
  completed: 'bg-action/10 text-action',
  cancelled: 'bg-surface text-muted shadow-soft',
}

// Which row is currently asking «Точно удалить?». One at a time: arming a
// second row disarms the first, so a stray click cannot land on the wrong one.
const armed = ref(null)

function onDelete(id) {
  if (armed.value !== id) {
    armed.value = id
    return
  }
  armed.value = null
  emit('delete', id)
}

function formatDate(value) {
  return value ? new Date(value).toLocaleDateString('ru-RU') : '—'
}
</script>

<template>
  <section class="overflow-hidden rounded-card bg-surface shadow-card">
    <div class="overflow-x-auto phone:hidden">
      <table class="app-datatable w-full" data-testid="tests-table">
        <thead>
          <tr class="text-left text-micro font-semibold uppercase tracking-wide text-muted">
            <th class="px-md py-sm">Тест</th>
            <th class="px-md py-sm">Фото</th>
            <th class="px-md py-sm">Статус</th>
            <th class="px-md py-sm">Запущен</th>
            <th class="px-md py-sm">Завершён</th>
            <th class="px-md py-sm"><span class="sr-only">Действия</span></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="test in rows" :key="test.id" class="border-t border-border-subtle">
            <td class="px-md py-sm">
              <RouterLink
                :to="{ name: 'ab-test-detail', params: { testId: test.id } }"
                class="text-base font-semibold text-action hover:underline"
                data-testid="test-link"
              >
                {{ test.name }}
              </RouterLink>
              <div class="mt-px flex flex-wrap items-center gap-x-sm text-micro text-muted">
                <span class="tabular-nums">WB {{ test.nm_id }}</span>
                <span v-if="test.vendor_code">{{ formatSku(test.vendor_code) }}</span>
                <span class="tabular-nums">создан {{ formatDate(test.created_at) }}</span>
              </div>
            </td>
            <td class="px-md py-sm text-tiny tabular-nums text-muted">
              {{ test.variant_count }}
            </td>
            <td class="px-md py-sm">
              <span
                class="inline-block rounded-full px-sm py-px text-micro font-semibold"
                :class="STATUS_CLASS[test.status]"
              >
                {{ statusLabel(test) }}
              </span>
            </td>
            <td class="px-md py-sm text-tiny tabular-nums">{{ formatDate(test.started_at) }}</td>
            <td class="px-md py-sm text-tiny tabular-nums">{{ formatDate(test.finished_at) }}</td>
            <td class="px-md py-sm text-right">
              <button
                type="button"
                class="rounded-btn px-sm py-xs text-micro font-semibold transition"
                :class="
                  armed === test.id
                    ? 'bg-status-negative/10 text-status-negative'
                    : 'text-muted hover:bg-hover hover:text-status-negative'
                "
                :disabled="saving"
                data-testid="delete-test"
                @click="onDelete(test.id)"
              >
                {{ armed === test.id ? 'Точно удалить?' : 'Удалить' }}
              </button>
            </td>
          </tr>
          <tr v-if="!loading && !rows.length">
            <td colspan="6" class="px-md py-xl text-center text-base text-muted">
              Тестов пока нет. Создайте первый — загрузите до 10 вариантов главного фото, и они
              будут сменять друг друга по мере набора показов.
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Phone: the same rows, two lines each. `hidden phone:block`, not a
         `v-if` on a window width — one source of truth, rendered twice. Six
         columns do not fit 402px, and the «Удалить» button was the one that
         fell off the right edge. -->
    <ul class="hidden divide-y divide-border-subtle phone:block">
      <li v-for="test in rows" :key="test.id" class="px-md py-sm">
        <div class="flex items-baseline gap-sm">
          <RouterLink
            :to="{ name: 'ab-test-detail', params: { testId: test.id } }"
            class="min-w-0 flex-1 truncate text-base font-semibold text-action"
          >
            {{ test.name }}
          </RouterLink>
          <span
            class="flex-none rounded-full px-sm py-px text-micro font-semibold"
            :class="STATUS_CLASS[test.status]"
          >
            {{ statusLabel(test) }}
          </span>
        </div>
        <div class="mt-px flex items-baseline gap-sm">
          <span class="min-w-0 flex-1 truncate text-micro text-muted">
            WB {{ test.nm_id }} · {{ test.variant_count }} фото · создан
            {{ formatDate(test.created_at) }}
          </span>
          <button
            type="button"
            class="flex-none rounded-btn px-sm py-xs text-micro font-semibold"
            :class="armed === test.id ? 'text-status-negative' : 'text-muted'"
            :disabled="saving"
            data-testid="delete-test-phone"
            @click="onDelete(test.id)"
          >
            {{ armed === test.id ? 'Точно?' : 'Удалить' }}
          </button>
        </div>
      </li>
      <li v-if="!loading && !rows.length" class="px-md py-lg text-center text-base text-muted">
        Тестов пока нет. Создайте первый — загрузите до 10 вариантов главного фото.
      </li>
    </ul>
  </section>
</template>
