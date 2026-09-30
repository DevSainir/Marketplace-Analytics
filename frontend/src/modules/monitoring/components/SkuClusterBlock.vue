<script setup>
import { formatMoney, formatNumber, formatPercent } from '@/core/utils/format'

/**
 * Rendered only for кабинеты whose `search_clusters_enabled` is set — NEVA since
 * 2026-09-26; hidden for everyone else since 2026-09-09. See the note in
 * `MonitoringView.vue`.
 *
 * «Рекламные кластеры» — the search phrases this SKU's ADS served in.
 *
 * A window of PAID impressions per search cluster, never an organic rank — the
 * live position probe that used to sit beside this block was removed on
 * 2026-08-27 (see `docs/monitoring/LIVE_POSITION.md`). `avg_position` below is
 * the average AD position inside the cluster, which is a different number.
 *
 * A phrase with no row means the campaign never bid on it: a gap in the
 * campaign, not in demand. Rows appear only for days a harvest has covered,
 * because WB serves no cluster history to backfill from.
 *
 * Dumb: props in, nothing out.
 */
defineProps({
  /** Backend `SkuClusterItem[]` for the page's SKU and window. */
  clusters: { type: Array, required: true },
  clustersLoading: { type: Boolean, default: false },
  clustersError: { type: String, default: '' },
  loaded: { type: Boolean, default: false },
  /**
   * The SKU's ad currencies (`ad_currencies`) — a fallback only: each cluster
   * names its own campaigns' (`currencies`), and one billed in two has no
   * «Расход» or CPC at all (the backend sends null → «—»).
   */
  currency: { type: [String, Array], default: '' },
})
</script>

<template>
  <section class="mt-xl" aria-label="Рекламные кластеры">
    <h2 class="text-h3 font-semibold text-primary">Рекламные кластеры</h2>
    <p class="mt-xs max-w-3xl text-tiny font-medium text-muted">
      Поисковые кластеры, по которым показывалась реклама этого артикула за выбранный период. Данные
      приходят из статистики кампаний и копятся вперёд — за прошлые месяцы их нет.
    </p>

    <div v-if="clusters.length" class="app-datatable mt-md">
      <!-- Wide table on a narrow screen: the card scrolls, the page never does. -->
      <div class="overflow-x-auto">
        <table class="min-w-[44rem]">
          <thead>
            <tr>
              <th>Кластер</th>
              <th class="text-right">Показы</th>
              <th class="text-right">Клики</th>
              <th class="text-right">CTR</th>
              <th class="text-right">Заказы</th>
              <th class="text-right">Расход</th>
              <th class="text-right">CPC</th>
              <th class="text-right">Ср. позиция</th>
              <th class="text-right">Дней</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in clusters" :key="item.cluster">
              <td class="font-medium">{{ item.cluster }}</td>
              <td class="text-right">{{ formatNumber(item.views) }}</td>
              <td class="text-right">{{ formatNumber(item.clicks) }}</td>
              <td class="text-right">{{ formatPercent(item.ctr) }}</td>
              <td class="text-right">{{ formatNumber(item.orders) }}</td>
              <td class="text-right">{{ formatMoney(item.spend, item.currencies ?? currency) }}</td>
              <td class="text-right">{{ formatMoney(item.cpc, item.currencies ?? currency) }}</td>
              <!-- Null = WB reported no position at all, which is not «первое
                   место» — an em dash is the only honest rendering. -->
              <td class="text-right">
                {{ item.avg_position === null ? '—' : item.avg_position }}
              </td>
              <td class="text-right text-muted">{{ item.days_count }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <p v-else-if="clustersError" class="mt-md text-base text-status-negative">
      {{ clustersError }}
    </p>
    <p v-else-if="clustersLoading" class="mt-md text-base text-muted">Загружаем кластеры…</p>
    <!-- The section's own description already explains why history is missing,
         so the empty state says only what is true of THIS window. -->
    <p v-else-if="loaded" class="mt-md text-base text-muted">
      За выбранный период реклама этого артикула не показывалась в поиске.
    </p>
  </section>
</template>
