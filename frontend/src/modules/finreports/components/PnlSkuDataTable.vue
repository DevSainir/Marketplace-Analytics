<script setup>
/**
 * The per-SKU P&L as a table — the desktop projection of `PnlSkuTable`.
 *
 * One row per SKU with the money columns of the reference workbook plus WB's
 * catalogue identity (the card photo / Артикул WB / Тип предмета / Бренд) and the efficiency
 * ratios (Выкуп, Средний чек, ROI). «Продажи» is shown NET of returns at the
 * page's price base (`priceBase.js`); the percentages are shares of it.
 *
 * «Штрафы» carry their categories inline — what tells a seller whether a fine
 * is disputable. The last column is the «Не включать» mark, emitted upward.
 * Rows cut by subject, brand or group (`isGroup`) are sums: no WB id, no mark.
 *
 * Three things beyond plain columns:
 *
 * * **Цвет только за рамкой.** Доли и коэффициенты подкрашены, когда вышли за
 *   границы из `pnlThresholds` — границы взяты по фактическому распределению,
 *   чтобы в обычном отчёте горели несколько строк, а не половина таблицы.
 * * **Раскрытие артикула.** Треугольник у артикула открывает подтаблицу
 *   размеров, которая грузится по клику (`@load-sizes`).
 * * **Строка «Итого».** Закреплена внизу области прокрутки, считается по всему
 *   текущему фильтру, а не по странице пагинации.
 *
 * PrimeVue for the sorting and the frozen first column. Figure columns carry
 * `col-num` and read from the right. The money is the backend's; the shares
 * are re-divided by `toRow` at the chosen price base, and this only formats.
 */
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'
import { ref, toRefs } from 'vue'

import InfoHint from '@/core/components/InfoHint.vue'
import { formatNumber } from '@/core/utils/format'
import PnlExclusionToggle from '@/modules/finreports/components/PnlExclusionToggle.vue'
import PnlSkuRowIdentity from '@/modules/finreports/components/PnlSkuRowIdentity.vue'
import PnlSkuSizeTable from '@/modules/finreports/components/PnlSkuSizeTable.vue'
import { amountClass, toneClass } from '@/modules/finreports/pnlThresholds'
import { pct, usePnlMoney } from '@/modules/finreports/pnlFormat'
import { useExpandedSkus, useFooterCells } from '@/modules/finreports/usePnlSkuTable'

const props = defineProps({
  /** @type {Array<object>} Flattened rows from `usePnlSkuRows`, already filtered. */
  rows: { type: Array, default: () => [] },
  /** @type {object|null} The «Итого» row from `sumRows` — the whole filter, not the page. */
  totals: { type: Object, default: null },
  /** @type {object} `nm_id -> {loading, error, data}` for the opened size tables. */
  sizes: { type: Object, default: () => ({}) },
  rowsPerPage: { type: Number, default: 50 },
  /** «Артикул», or «Предмет» / «Бренд» / «Группа» when the rows are sums. */
  firstHeader: { type: String, default: 'Артикул' },
})

const emit = defineEmits(['toggle-exclusion', 'load-sizes'])

/** Reset to the first page on a size change — keeping a stale offset can strand
 *  the view past the last page of the new layout. */
const first = ref(0)

defineExpose({ first })

/** Dim the excluded rows so the seller sees what the «общий счёт» drops. */
const rowClass = (data) => (data.isExcluded ? 'opacity-50' : '')

const { expanded, toggle } = useExpandedSkus(
  (nmId) => emit('load-sizes', nmId),
  () => props.sizes,
)
const foot = useFooterCells(toRefs(props).totals)
const { money } = usePnlMoney()
</script>

<template>
  <DataTable
    v-model:first="first"
    v-model:expanded-rows="expanded"
    :value="rows"
    :paginator="rows.length > rowsPerPage"
    :rows="rowsPerPage"
    :row-class="rowClass"
    sort-mode="single"
    data-key="nmId"
    scrollable
    scroll-height="min(40rem, 70vh)"
  >
    <template #empty>
      <div class="px-md py-xl text-center text-base text-muted">Нет продаж за период</div>
    </template>

    <!-- Фото и треугольник размеров живут в этой же закреплённой ячейке —
         почему именно так, написано в `PnlSkuRowIdentity`. -->
    <Column field="saName" :header="firstHeader" sortable frozen :footer="foot.saName">
      <template #body="{ data }">
        <PnlSkuRowIdentity :row="data" :open="!!expanded[data.nmId]" @toggle="toggle(data.nmId)" />
      </template>
    </Column>
    <Column field="nmId" header="Артикул WB" sortable>
      <template #body="{ data }">
        <span class="tabular-nums text-muted">{{ data.isSku ? data.nmId : '—' }}</span>
      </template>
    </Column>
    <Column field="subject" header="Предмет" sortable>
      <template #body="{ data }">{{ data.subject || '—' }}</template>
    </Column>
    <Column field="brand" header="Бренд" sortable>
      <template #body="{ data }">{{ data.brand || '—' }}</template>
    </Column>
    <Column field="orders" class="col-num" header="Заказы, шт" sortable :footer="foot.orders">
      <template #body="{ data }">
        {{ data.orders === null ? '—' : formatNumber(data.orders) }}
      </template>
    </Column>
    <Column field="sold" class="col-num" header="Продажи, шт" sortable :footer="foot.sold">
      <template #body="{ data }">{{ formatNumber(data.sold) }}</template>
    </Column>
    <!-- «Процент выкупа» WB из воронки; у размеров своя мера — см. PNL.md. -->
    <Column field="buyoutPct" class="col-num" sortable :footer="foot.buyoutPct">
      <template #header>
        Выкуп, %<InfoHint
          text="Как «Процент выкупа» в кабинете WB: выкупы ÷ (выкупы + отказы) по заказам, сделанным за период. Последние ~3 недели ещё дозревают."
        />
      </template>
      <template #body="{ data }">
        <span :class="toneClass('buyoutPct', data.buyoutPct)">{{ pct(data.buyoutPct) }}</span>
      </template>
    </Column>
    <Column field="returnPct" class="col-num" sortable :footer="foot.returnPct">
      <template #header>
        Возвраты, %<InfoHint
          text="Выкупленные товары, которые покупатель затем вернул (не отмены заказов): доля от выкупленных штук."
        />
      </template>
      <template #body="{ data }">
        <span :class="toneClass('returnPct', data.returnPct)">{{ pct(data.returnPct) }}</span>
      </template>
    </Column>
    <Column field="sales" class="col-num" header="Продажи" sortable :footer="foot.sales">
      <template #body="{ data }">{{ money(data.sales) }}</template>
    </Column>
    <Column
      field="averageCheque"
      class="col-num"
      header="Средний чек"
      sortable
      :footer="foot.averageCheque"
    >
      <template #body="{ data }">{{ money(data.averageCheque) }}</template>
    </Column>
    <Column field="sppPct" class="col-num" header="СПП, %" sortable :footer="foot.sppPct">
      <template #body="{ data }">{{ pct(data.sppPct) }}</template>
    </Column>
    <Column field="logistics" class="col-num" header="Логистика" sortable :footer="foot.logistics">
      <template #body="{ data }">
        {{ money(data.logistics) }}
        <span
          v-if="data.logisticsPct !== null"
          class="text-tiny"
          :class="toneClass('logisticsPct', data.logisticsPct, data.priceBase) || 'text-muted'"
        >
          ({{ pct(data.logisticsPct) }})
        </span>
      </template>
    </Column>
    <Column field="penalties" class="col-num" header="Штрафы" sortable :footer="foot.penalties">
      <template #body="{ data }">
        {{ money(data.penalties) }}
        <template v-if="data.penalties">
          <div
            v-for="p in data.penaltyReasons"
            :key="p.reason"
            class="text-micro leading-tight text-muted"
          >
            {{ p.reason }}: {{ money(p.amount) }}
          </div>
        </template>
      </template>
    </Column>
    <Column field="cogs" class="col-num" header="Себестоимость" sortable :footer="foot.cogs">
      <template #body="{ data }">{{ money(data.cogs) }}</template>
    </Column>
    <Column
      field="advertising"
      class="col-num"
      header="Реклама"
      sortable
      :footer="foot.advertising"
    >
      <template #body="{ data }">{{ money(data.advertising) }}</template>
    </Column>
    <Column field="advertisingPct" class="col-num" sortable :footer="foot.advertisingPct">
      <template #header>ДРР от продаж<InfoHint text="Реклама ÷ продажи" /></template>
      <template #body="{ data }">
        <span :class="toneClass('advertisingPct', data.advertisingPct, data.priceBase)">
          {{ pct(data.advertisingPct) }}
        </span>
      </template>
    </Column>
    <Column field="adBonus" class="col-num" header="Промо-бонусы" sortable :footer="foot.adBonus">
      <template #body="{ data }">
        <span v-if="data.adBonus" class="text-status-positive"> -{{ money(data.adBonus) }} </span>
        <template v-else>{{ money(data.adBonus) }}</template>
      </template>
    </Column>
    <Column field="roi" class="col-num" header="ROI" sortable :footer="foot.roi">
      <template #body="{ data }">
        <span :class="toneClass('roi', data.roi)">{{ pct(data.roi) }}</span>
      </template>
    </Column>
    <Column field="payout" class="col-num" header="К перечислению" sortable :footer="foot.payout">
      <template #body="{ data }">{{ money(data.payout) }}</template>
    </Column>
    <Column field="profit" class="col-num" header="Чистая прибыль" sortable>
      <template #body="{ data }">
        <template v-if="data.profit !== null">
          <span :class="amountClass(data.profit) || 'text-primary'">
            {{ money(data.profit) }}
          </span>
          <span
            class="text-tiny"
            :class="toneClass('profitPct', data.profitPct, data.priceBase) || 'text-muted'"
          >
            ({{ pct(data.profitPct) }})</span
          >
        </template>
        <template v-else>—</template>
      </template>
      <template #footer>
        <span v-if="totals" :class="amountClass(totals.profit)">
          {{ money(totals.profit) }}
          <span class="text-tiny text-muted">({{ pct(totals.profitPct) }})</span>
        </span>
      </template>
    </Column>
    <Column field="isExcluded" header="" :sortable="false">
      <template #body="{ data }">
        <PnlExclusionToggle
          v-if="data.isSku"
          :checked="data.isExcluded"
          @change="emit('toggle-exclusion', { nmId: data.nmId, excluded: $event })"
        />
      </template>
    </Column>

    <template #expansion="{ data }">
      <PnlSkuSizeTable :state="sizes[data.nmId] ?? null" />
    </template>
  </DataTable>
</template>
