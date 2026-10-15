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
import { RouterLink } from 'vue-router'

import { statusLabel, statusTone } from '@/modules/abTests/store'
import { formatSku } from '@/core/utils/format'
import { confirmLabel, useConfirmClick } from '@/core/utils/confirmClick'
import { formatMoscowDate } from '@/core/utils/moscow'

defineProps({
  /** Tests as the store holds them. */
  rows: { type: Array, default: () => [] },
  /** True while the list is being (re)fetched. */
  loading: { type: Boolean, default: false },
  /** True while any write is in flight. */
  saving: { type: Boolean, default: false },
})
const emit = defineEmits(['delete'])

// Which row is asking «Точно удалить?» (`confirmClick`): one at a time, so a
// stray click cannot land on the wrong one.
const removal = useConfirmClick()
const onDelete = (id) => removal.press(id, () => emit('delete', id))

function formatDate(value) {
  return formatMoscowDate(value)
}
</script>

<template>
  <!-- The section is the table's card (`.app-datatable`); on the <table> itself
       the skin drew a second card inside the first. -->
  <section class="app-datatable">
    <div class="overflow-x-auto phone:hidden">
      <table class="w-full" data-testid="tests-table">
        <thead>
          <tr>
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
                <span class="tabular-nums">Артикул WB {{ test.nm_id }}</span>
                <span v-if="test.vendor_code">{{ formatSku(test.vendor_code) }}</span>
                <span class="tabular-nums">создан {{ formatDate(test.created_at) }}</span>
              </div>
            </td>
            <td class="px-md py-sm text-tiny tabular-nums text-muted">
              {{ test.variant_count }}
            </td>
            <td class="px-md py-sm">
              <span class="ui-badge" :class="statusTone(test)">
                {{ statusLabel(test) }}
              </span>
            </td>
            <td class="px-md py-sm text-tiny tabular-nums">{{ formatDate(test.started_at) }}</td>
            <td class="px-md py-sm text-tiny tabular-nums">{{ formatDate(test.finished_at) }}</td>
            <td class="px-md py-sm text-right">
              <button
                type="button"
                class="ui-btn ui-btn--danger ui-btn--sm"
                :class="{ 'is-armed': removal.isArmed(test.id) }"
                :disabled="saving"
                data-testid="delete-test"
                @click="onDelete(test.id)"
              >
                {{ removal.isArmed(test.id) ? confirmLabel('Удалить') : 'Удалить' }}
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
          <span class="ui-badge flex-none" :class="statusTone(test)">
            {{ statusLabel(test) }}
          </span>
        </div>
        <div class="mt-px flex items-baseline gap-sm">
          <span class="min-w-0 flex-1 truncate text-micro text-muted">
            Артикул WB {{ test.nm_id }} · {{ test.variant_count }} фото · создан
            {{ formatDate(test.created_at) }}
          </span>
          <button
            type="button"
            class="ui-btn ui-btn--danger ui-btn--sm flex-none"
            :class="{ 'is-armed': removal.isArmed(test.id) }"
            :disabled="saving"
            data-testid="delete-test-phone"
            @click="onDelete(test.id)"
          >
            {{ removal.isArmed(test.id) ? confirmLabel('Удалить') : 'Удалить' }}
          </button>
        </div>
      </li>
      <li v-if="!loading && !rows.length" class="px-md py-lg text-center text-base text-muted">
        Тестов пока нет. Создайте первый — загрузите до 10 вариантов главного фото, и они будут
        сменять друг друга по мере набора показов.
      </li>
    </ul>
  </section>
</template>
