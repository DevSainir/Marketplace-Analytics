<script setup>
import BusyRegion from '@/core/components/BusyRegion.vue'
import DataState from '@/core/components/DataState.vue'
import { formatMoney, formatNumber, formatPercent } from '@/core/utils/format'

/**
 * Rendered only for workspaces whose `search_clusters_enabled` is set — one workspace since
 * 2026-09-26; hidden for everyone else since 2026-09-09. See the note in
 * `MonitoringView.vue`.
 *
 * "Search clusters" — the search phrases this SKU's ADS served in.
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
   * "Spend" or CPC at all (the backend sends null → "—").
   */
  currency: { type: [String, Array], default: '' },
})
</script>

<template>
  <section class="mt-xl" aria-label="Search clusters">
    <h2 class="text-h3 font-semibold text-primary">Search clusters</h2>
    <p class="mt-xs max-w-3xl text-tiny font-medium text-muted">
      Search phrases this SKU's ads were shown for in the selected period. Collected from campaign
      stats from the day collection began — there is no earlier history.
    </p>

    <DataState
      v-if="clustersError"
      kind="error"
      :layout="clusters.length ? 'line' : 'card'"
      :text="clustersError"
      class="mt-md"
    />
    <BusyRegion v-if="clusters.length" :busy="clustersLoading" class="app-datatable mt-md">
      <!-- Wide table on a narrow screen: the card scrolls, the page never does. -->
      <div class="overflow-x-auto">
        <table class="min-w-[44rem]">
          <thead>
            <tr>
              <th>Cluster</th>
              <th class="text-right">Impressions</th>
              <th class="text-right">Clicks</th>
              <th class="text-right">CTR</th>
              <th class="text-right">Orders</th>
              <th class="text-right">Spend</th>
              <th class="text-right">CPC</th>
              <th class="text-right">Avg. position</th>
              <th class="text-right">Days</th>
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
              <!-- Null = WB reported no position at all, which is not "first
                   place" — an em dash is the only honest rendering. -->
              <td class="text-right">
                {{ item.avg_position === null ? '—' : item.avg_position }}
              </td>
              <td class="text-right text-muted">{{ item.days_count }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </BusyRegion>

    <DataState v-else-if="clustersLoading" kind="loading" class="mt-md" />
    <!-- The section's own description already explains why history is missing,
         so the empty state says only what is true of THIS window. -->
    <DataState
      v-else-if="loaded && !clustersError"
      kind="empty"
      text="This SKU's ads weren't shown in search in the selected period"
      class="mt-md"
    />
  </section>
</template>
