<script setup>
import { ref } from 'vue'

import { formatMoney, formatNumber, formatPercent } from '@/core/utils/format'

/**
 * «Поиск по кластерам» — the last block of a SKU's monitoring page.
 *
 * Two answers about the SAME SKU, deliberately not merged into one table:
 *
 * - the cluster table, always shown: the search phrases this SKU's ADS served
 *   in over the page's window, with the paid metrics per phrase. A phrase with
 *   no row means the campaign never bid on it — a gap in the campaign, not in
 *   demand;
 * - the search bar, which does one thing: check where this SKU stands in WB's
 *   live organic search for a phrase you type. That is a sample taken now, for
 *   one delivery region, and it cannot be recomputed for a past day — which is
 *   why it is a search box and not another column.
 *
 * Dumb: props in, `check`/`recheck` out.
 *
 * Three probe states stay distinct, because collapsing them tells a seller the
 * opposite of the truth: an error means WB did not answer and NOTHING was
 * checked; a null position means the SKU was not inside the scanned depth (which
 * is printed, since a deeper rank is still possible); a number is a real rank.
 */
defineProps({
  /** Backend `SkuClusterItem[]` for the page's SKU and window. */
  clusters: { type: Array, required: true },
  clustersLoading: { type: Boolean, default: false },
  clustersError: { type: String, default: '' },
  loaded: { type: Boolean, default: false },
  /** Backend `SkuSearchPositionResponse`, or null before the first check. */
  position: { type: Object, default: null },
  positionLoading: { type: Boolean, default: false },
  positionError: { type: String, default: '' },
})

const emit = defineEmits(['check', 'recheck'])

const term = ref('')

/** Submit guard: Enter in the input bypasses the disabled button, and an empty
 *  phrase has no ranking to ask WB for. */
function submit() {
  if (term.value.trim()) emit('check', term.value)
}

/** «14.08.2026, 15:42» — the probe is a sample, so its timestamp is part of it. */
const checkedAt = (iso) =>
  new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
</script>

<template>
  <section class="mt-lg" aria-label="Поиск по кластерам">
    <h2 class="text-h3 font-semibold text-primary">Поиск по кластерам</h2>
    <p class="mt-xs max-w-3xl text-tiny font-medium text-muted">
      Кластеры, по которым показывалась реклама этого артикула за выбранный период. Ниже — проверка
      живой выдачи WB: введите запрос, чтобы узнать позицию этого SKU прямо сейчас.
    </p>

    <!-- The live half: one input, one job. -->
    <form class="mt-md flex flex-wrap items-end gap-sm" @submit.prevent="submit">
      <label class="min-w-[14rem] flex-1">
        <span class="block text-tiny font-medium text-muted">Запрос в поиске WB</span>
        <input
          v-model="term"
          type="search"
          maxlength="100"
          placeholder="носки мужские"
          class="mt-xs w-full rounded-btn border border-border-subtle bg-surface px-md py-sm text-base text-primary outline-none transition focus:border-action"
        />
      </label>
      <button
        type="submit"
        class="rounded-btn bg-action px-lg py-sm text-base font-semibold text-white transition hover:bg-action-hover disabled:opacity-50"
        :disabled="positionLoading || !term.trim()"
      >
        {{ positionLoading ? 'Проверяем…' : 'Проверить позицию' }}
      </button>
    </form>

    <p v-if="positionError" class="mt-sm text-base text-status-negative">{{ positionError }}</p>

    <div
      v-else-if="position"
      class="mt-sm rounded-card border border-border-subtle bg-surface p-lg shadow-card"
    >
      <div class="flex flex-wrap items-baseline justify-between gap-sm">
        <p class="text-base text-primary">
          <template v-if="position.position">
            Позиция в выдаче по «{{ position.query }}»:
            <span class="text-h3 font-bold">{{ position.position }}</span>
            <span class="text-tiny font-medium text-muted">
              (стр. {{ position.page }}, {{ position.position_on_page }})
            </span>
          </template>
          <template v-else>
            Артикул не найден в первых {{ formatNumber(position.positions_scanned) }} позициях по
            «{{ position.query }}».
            <span v-if="position.truncated" class="text-muted">
              Глубже проверка не заходит — WB ограничивает выдачу.
            </span>
          </template>
        </p>
        <button
          type="button"
          class="rounded-btn border border-border-subtle px-md py-xs text-tiny font-medium text-primary transition hover:bg-canvas disabled:opacity-50"
          :disabled="positionLoading"
          @click="emit('recheck', position.query)"
        >
          Проверить заново
        </button>
      </div>
      <p class="mt-xs text-tiny font-medium text-muted">
        Проверено {{ checkedAt(position.checked_at) }} · всего по запросу
        {{ formatNumber(position.total_found) }} товаров
        <span v-if="position.normalized_query">
          · запрос WB: «{{ position.normalized_query }}»</span
        >
      </p>
      <p v-if="position.other_skus.length" class="mt-sm text-tiny text-muted">
        Другие ваши артикулы в этой выдаче:
        <span v-for="(other, index) in position.other_skus" :key="other.nm_id">
          <span v-if="index">, </span>{{ other.vendor_code || other.nm_id }} — {{ other.position }}
        </span>
      </p>
    </div>

    <!-- The stored half: always here, no keyword involved. -->
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
              <td class="text-right">{{ formatMoney(item.spend) }}</td>
              <td class="text-right">{{ formatMoney(item.cpc) }}</td>
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
    <p v-else-if="loaded" class="mt-md text-base text-muted">
      За выбранный период реклама этого артикула не показывалась в поиске. Данные по кластерам
      собираются с каждым обновлением WB и накапливаются вперёд — за прошлые месяцы их нет.
    </p>
  </section>
</template>
