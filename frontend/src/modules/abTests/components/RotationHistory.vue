<script setup>
/**
 * «История действий» — every turn the rotation has served, newest first.
 *
 * The result table answers «which photo is best». This answers «what actually
 * happened», and that is the question asked whenever the first answer looks
 * wrong. A turn that ran nine minutes instead of thirty, a lap that dealt one
 * photo twice, a photo that was up all evening and got no impressions — none of
 * those are visible in the totals and all of them are obvious here.
 *
 * «Время круга» is the length of THIS turn, not of the whole lap. That is the
 * number that explains a strange figure: a photo credited with a third of the
 * traffic of its neighbours usually stood for a third as long, because the
 * rotation wakes every five minutes and a slot that ends just after a pass
 * waits for the next one.
 *
 * The panel scrolls internally rather than growing the page. A test that has
 * been running for days has hundreds of turns, and a table that pushes the
 * results off the screen makes the page worse the longer the test is useful.
 */
import { computed } from 'vue'

import { formatNumber, formatPercent } from '@/core/utils/format'
import { formatMoscow } from '@/core/utils/moscow'

const props = defineProps({
  /** The open test, as the detail endpoint returns it. */
  test: { type: Object, required: true },
  /** variant_id -> object URL for the stored original. */
  imageUrls: { type: Object, default: () => ({}) },
  /** Which lap to show, or 0 for all of them. */
  round: { type: Number, default: 0 },
})

const rows = computed(() => {
  const history = props.test.history ?? []
  return props.round ? history.filter((row) => row.round_number === props.round) : history
})

function title(row) {
  return row.is_original ? 'Главное' : `Вариант ${row.position}`
}

/**
 * «08.09.2026, 12:05 МСК».
 *
 * Moscow, spelled out, because WB operates in Moscow time and the seller reads
 * these next to figures from the WB seller portal. A local-time rendering would put
 * this table and that one an unexplained few hours apart.
 */
function moment(iso) {
  return formatMoscow(iso, {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** A live turn has no length yet, and inventing one would age on the screen. */
function minutes(row) {
  return row.minutes === null || row.minutes === undefined ? '—' : formatNumber(row.minutes)
}
</script>

<template>
  <section
    class="rounded-card border border-border-subtle bg-surface shadow-card"
    aria-label="История действий"
  >
    <header class="flex items-baseline justify-between gap-md px-lg pb-sm pt-lg phone:px-md">
      <h2 class="text-h3 font-semibold text-primary">История действий</h2>
      <span class="text-tiny text-muted">
        {{ formatNumber(rows.length) }} {{ rows.length === 1 ? 'установка' : 'установок' }}
      </span>
    </header>

    <div class="ab-history__scroll">
      <table class="ab-history" data-testid="history">
        <thead>
          <tr>
            <th class="ta-l">Время установки ↓</th>
            <th class="ta-l">Контент</th>
            <th class="ta-l">Вариант</th>
            <th class="ta-r">Клики</th>
            <th class="ta-r">Показы</th>
            <th class="ta-r">CTR</th>
            <th class="ta-r">Круг</th>
            <th class="ta-r">Время круга (мин)</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="`${row.variant_id}-${row.activated_at}`" data-testid="turn">
            <td class="whitespace-nowrap">{{ moment(row.activated_at) }}</td>
            <td>
              <img
                v-if="imageUrls[row.variant_id]"
                :src="imageUrls[row.variant_id]"
                :alt="title(row)"
                class="ab-history__thumb"
              />
              <div v-else class="ab-history__thumb ab-history__thumb--empty"></div>
            </td>
            <td class="whitespace-nowrap">{{ title(row) }}</td>
            <td class="ta-r tabular-nums">{{ formatNumber(row.clicks) }}</td>
            <td class="ta-r tabular-nums">{{ formatNumber(row.views) }}</td>
            <td class="ta-r tabular-nums">{{ formatPercent(row.click_through) }}</td>
            <td class="ta-r tabular-nums">{{ row.round_number }}</td>
            <td class="ta-r tabular-nums">{{ minutes(row) }}</td>
          </tr>
        </tbody>
      </table>

      <p v-if="!rows.length" class="px-lg py-lg text-tiny text-muted phone:px-md">
        Пока ни одной установки. Первая появится, когда тест запустится.
      </p>
    </div>
  </section>
</template>

<style scoped src="@/modules/abTests/components/styles/RotationHistory.css"></style>
