<script setup>
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'
import { computed, toRefs } from 'vue'

import { formatCurrency, formatNumber, formatPercent } from '@/core/utils/format'
import { CAMPAIGN_STATUS_BADGE, CAMPAIGN_STATUS_TEXT } from '@/modules/labs/campaignStatus'

/**
 * Cross-attribution table: one row per advertising campaign, showing the
 * orders each campaign captured for the CURRENT SKU. A campaign typically
 * promotes the whole variant group (all colours), so `orders` here is this
 * SKU's attributed slice, not the campaign's global total.
 */
const props = defineProps({
  campaigns: { type: Array, required: true },
  /** Human label of the current SKU (vendor code when known, nm ID otherwise). */
  skuLabel: { type: String, required: true },
})

const { campaigns } = toRefs(props)

const rows = computed(() =>
  campaigns.value.map((c) => ({
    ...c,
    ctr: c.metrics.ctr,
    cpc: c.metrics.cpc,
    cpm: c.metrics.cpm,
    cartConversion: c.metrics.cart_conversion,
    orderConversion: c.metrics.order_conversion,
  })),
)
</script>

<template>
  <div class="app-datatable">
    <DataTable
      :value="rows"
      :paginator="rows.length > 10"
      :rows="10"
      sort-mode="single"
      data-key="campaign_id"
    >
      <template #empty>
        <div class="px-4 py-10 text-center text-sm text-muted">
          Нет рекламной активности по этому SKU за выбранный период.
        </div>
      </template>

      <Column field="campaign_id" header="Кампания" sortable>
        <template #body="{ data }">
          <span class="font-medium text-primary">#{{ data.campaign_id }}</span>
          <span v-if="data.type_label" class="ml-2 text-xs text-muted">{{ data.type_label }}</span>
        </template>
      </Column>

      <Column field="status_label" header="Статус" sortable>
        <template #body="{ data }">
          <span
            v-if="data.status_label"
            class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset"
            :class="CAMPAIGN_STATUS_BADGE[data.status_label] ?? CAMPAIGN_STATUS_BADGE.completed"
          >
            {{ CAMPAIGN_STATUS_TEXT[data.status_label] ?? data.status_label }}
          </span>
          <span v-else class="text-xs text-muted">не синхронизирована</span>
        </template>
      </Column>

      <Column field="views" header="Показы" sortable>
        <template #body="{ data }">{{ formatNumber(data.views) }}</template>
      </Column>

      <Column field="clicks" header="Клики" sortable>
        <template #body="{ data }">{{ formatNumber(data.clicks) }}</template>
      </Column>

      <Column field="add_to_cart" header="Корзины" sortable>
        <template #body="{ data }">{{ formatNumber(data.add_to_cart) }}</template>
      </Column>

      <Column field="orders" :header="`Заказы → ${skuLabel}`" sortable>
        <template #body="{ data }">
          <span class="font-semibold text-action">{{ formatNumber(data.orders) }}</span>
        </template>
      </Column>

      <Column field="spend" header="Расходы" sortable>
        <template #body="{ data }">{{ formatCurrency(data.spend) }}</template>
      </Column>

      <Column field="cpm" header="CPM" sortable>
        <template #body="{ data }">{{ formatCurrency(data.cpm) }}</template>
      </Column>

      <Column field="ctr" header="CTR" sortable>
        <template #body="{ data }">{{ formatPercent(data.ctr) }}</template>
      </Column>

      <Column field="cpc" header="CPC" sortable>
        <template #body="{ data }">{{ formatCurrency(data.cpc) }}</template>
      </Column>

      <Column field="cartConversion" header="Клик → корзина" sortable>
        <template #body="{ data }">{{ formatPercent(data.cartConversion) }}</template>
      </Column>

      <Column field="orderConversion" header="Корзина → заказ" sortable>
        <template #body="{ data }">{{ formatPercent(data.orderConversion) }}</template>
      </Column>
    </DataTable>
  </div>
</template>
