<script setup>
/**
 * РЕКЛАМА — /labs/advertisement-source.
 *
 * The «Реклама» tab of the finmodel one-pager, re-laid in the app's own design
 * system: `ui-next` tokens, PrimeVue tables, ECharts through `BaseChart`, a
 * card list below `sm`. `/labs/finmodel` keeps the original as it came, on bare
 * DOM and its own tokens; this is the step between that and the product.
 *
 * Everything the block needs lives in this folder so it can move in pieces:
 * the arithmetic (`adsSpend.js`, `adsSkuRows.js`) is pure and covered by its
 * own specs, `api.js` is the one seam to swap for a real endpoint, and each
 * section is its own component.
 *
 * The numbers are «Демо»'s static datapack (P&L window 15.07–06.09.2026),
 * the same file the finmodel lab reads. No call to our API.
 */
import { computed, onMounted } from 'vue'

import PeriodSelector from '@/core/components/PeriodSelector.vue'
import AdsDailyChart from '@/modules/labs/advertisement-source/components/AdsDailyChart.vue'
import AdsKindTable from '@/modules/labs/advertisement-source/components/AdsKindTable.vue'
import AdsKpis from '@/modules/labs/advertisement-source/components/AdsKpis.vue'
import AdsNotes from '@/modules/labs/advertisement-source/components/AdsNotes.vue'
import AdsSkuCards from '@/modules/labs/advertisement-source/components/AdsSkuCards.vue'
import AdsSkuTable from '@/modules/labs/advertisement-source/components/AdsSkuTable.vue'
import AdsSkuToolbar from '@/modules/labs/advertisement-source/components/AdsSkuToolbar.vue'
import AdsZoneBars from '@/modules/labs/advertisement-source/components/AdsZoneBars.vue'
import { useAdsSource } from '@/modules/labs/advertisement-source/useAdsSource'

const BASES = [
  { key: 'gross', label: 'По цене реализации' },
  { key: 'card', label: 'По цене карточки' },
]

const ads = useAdsSource()
const { loading, error, available, from, to, lastDay, revBase, group, filters, currency } = ads

onMounted(ads.load)

const dateRu = (iso) => iso.split('-').reverse().join('.')
const periodLabel = computed(() => `${dateRu(from.value)} — ${dateRu(to.value)}`)
</script>

<template>
  <div class="app-container py-lg">
    <header class="mb-lg">
      <h1 class="text-h2 font-bold text-primary">Реклама</h1>
      <p class="mt-xs text-tiny text-muted">
        Кабинет «Демо» · данные финмодели, не живые: окно P&amp;L 15.07–06.09.2026
      </p>
    </header>

    <div v-if="loading" class="py-xl text-center text-base text-muted">Загружаю данные…</div>
    <div v-else-if="error" class="py-xl text-center text-base text-status-negative">
      Не удалось загрузить данные: {{ error }}
    </div>
    <p v-else-if="!available" class="border-l-2 border-status-warning pl-md text-base text-muted">
      В датапаке нет истории затрат на рекламу — сверять удержания WB не с чем.
    </p>

    <template v-else>
      <div class="mb-lg flex flex-wrap items-center gap-md">
        <PeriodSelector :from="from" :to="to" :preset-end="lastDay" @range="ads.setPeriod" />
        <div class="flex flex-wrap items-center gap-xs">
          <button
            v-for="base in BASES"
            :key="base.key"
            type="button"
            class="ui-chip phone:min-h-11"
            :class="{ 'is-on': revBase === base.key }"
            @click="revBase = base.key"
          >
            {{ base.label }}
          </button>
        </div>
      </div>

      <div class="flex flex-col gap-xl">
        <section>
          <h2 class="text-h3 font-semibold text-primary">Куда ушли деньги за период</h2>
          <p class="mb-md mt-xs max-w-prose text-tiny text-muted">
            Открутка по дате списания из истории затрат кабинета. Тип ставки — оттуда же, зона
            показов — из статистики кампаний: она знает, какая часть открутки ушла в поиск, а какая
            на рекомендательные полки и прочие места.
          </p>
          <AdsKpis
            :spend="ads.spend.value"
            :drr="ads.drr.value"
            :currency="currency"
            :period-label="periodLabel"
          />
        </section>

        <section v-if="ads.spend.value.total">
          <h2 class="text-h3 font-semibold text-primary">На что ушли</h2>
          <p class="mb-md mt-xs max-w-prose text-tiny text-muted">
            Ручная ставка работает в поиске, единая — на полках: это видно по разнесению той же
            открутки между зонами.
          </p>
          <div class="flex flex-col gap-md">
            <AdsKindTable
              :rows="ads.kinds.value"
              :spend="ads.spend.value"
              :zones="ads.zones.value"
              :currency="currency"
            />
            <AdsZoneBars
              v-if="ads.bars.value.length"
              :bars="ads.bars.value"
              :days="ads.zones.value.days"
              :currency="currency"
            />
          </div>
        </section>

        <section v-if="ads.daily.value.length > 1">
          <h2 class="text-h3 font-semibold text-primary">Открутка по дням</h2>
          <p class="mb-md mt-xs text-tiny text-muted">
            Дата списания из кабинета, за выбранный вверху период.
          </p>
          <AdsDailyChart :days="ads.daily.value" :currency="currency" />
        </section>

        <section>
          <h2 class="text-h3 font-semibold text-primary">Реклама по {{ ads.groupDef.value.by }}</h2>
          <p class="mb-md mt-xs max-w-prose text-tiny text-muted">
            За выбранный вверху период, суммы разнесены из удержаний WB по долям фактической
            открутки. Промо-бонусы — за всё окно файла кабинета: по дням они приходят без артикула.
          </p>
          <AdsSkuToolbar
            v-model:query="filters.query"
            v-model:subject="filters.subject"
            v-model:brand="filters.brand"
            v-model:group="group"
            :subjects="ads.options.value.subjects"
            :brands="ads.options.value.brands"
            :filtering="ads.isFiltering.value"
            @clear="ads.clearFilters"
          />
          <div class="hidden sm:block">
            <AdsSkuTable
              :rows="ads.rows.value"
              :totals="ads.totals.value"
              :label-header="ads.groupDef.value.col"
              :of-total="group === 'sku' ? ads.skuRows.value.length : 0"
              :currency="currency"
            />
          </div>
          <div class="sm:hidden">
            <AdsSkuCards :rows="ads.rows.value" :totals="ads.totals.value" :currency="currency" />
          </div>
        </section>

        <AdsNotes :notes="ads.notes.value" :spend="ads.spend.value" :currency="currency" />
      </div>
    </template>
  </div>
</template>
