<script setup>
/**
 * Размеры одного артикула — подтаблица, которая раскрывается под его строкой.
 *
 * Артикул «в среднем прибыльный» — обычное описание сетки, где половина
 * размеров тащит остальных: ходовой 48-й выкупают вдвое лучше крайнего 42-го, а
 * логистику обратного плеча оплачивают оба. Средняя по артикулу это скрывает,
 * разрез по размерам — нет, и это единственная причина, по которой таблица
 * существует.
 *
 * Все цифры измерены: WB ставит размер на каждой строке отчёта, которую
 * выставляет, поэтому сумма размеров сходится с артикулом до копейки. Кроме
 * рекламы — её WB не даёт в разрезе размеров вовсе, поэтому её здесь нет, а
 * колонка прибыли честно называется «Маржа без рекламы».
 *
 * Простая `<table>`, а не PrimeVue: подтаблица не сортируется и не
 * пагинируется, а вложенный DataTable внутри строки DataTable тянет за собой
 * вторую прокрутку внутри первой.
 */
import { formatMoney, formatNumber, formatPercent } from '@/core/utils/format'
import { amountClass, toneClass } from '@/modules/finreports/pnlThresholds'

defineProps({
  /** @type {object|null} Ответ `/pnl/skus/{nmId}/sizes`, либо `null` пока грузится. */
  state: { type: Object, default: null },
})

/**
 * Числа приходят от бэкенда СТРОКАМИ — так pydantic сериализует `Decimal`, и
 * так и надо: на деньгах float теряет копейки. Поэтому каждое значение здесь
 * проходит через `Number`: `formatPercent` принимает только число и на строке
 * «22.42» молча отдаёт «—», то есть колонка процентов пустеет целиком.
 */
const n = (value) => (value === null || value === undefined || value === '' ? null : Number(value))
const money = (value) => (n(value) === null ? '—' : formatMoney(n(value), ''))
const pct = (value) => (n(value) === null ? '—' : formatPercent(n(value)))
const units = (value) => (n(value) === null ? '—' : formatNumber(n(value)))

/** «+8,8 п.п.» — знак ставится явно: без плюса отклонение вверх читается как норма. */
function deltaPp(value) {
  const points = n(value)
  if (points === null) return '—'
  return `${points > 0 ? '+' : ''}${formatMoney(points, '', 1)} п.п.`
}
</script>

<template>
  <div class="bg-canvas px-md py-sm">
    <!-- `null` тоже значит «ещё не знаем»: строка раскрывается мгновенно, а
         запрос за ней только уходит, и «нет размеров» в этот момент — неправда. -->
    <p v-if="!state || state.loading" class="py-sm text-tiny text-muted">Считаем размеры…</p>
    <p v-else-if="state.error" class="py-sm text-tiny text-status-negative">{{ state.error }}</p>
    <p v-else-if="!state.data?.rows?.length" class="py-sm text-tiny text-muted">
      За этот период у артикула нет строк с размером.
    </p>

    <template v-else>
      <p class="mb-xs text-tiny text-muted">
        Размеров в сетке: {{ state.data.rows.length }} · деньги по строкам отчёта WB с размером,
        сумма сходится со строкой артикула. Рекламы в разрезе размеров WB не даёт.
      </p>
      <div class="overflow-x-auto">
        <table class="w-full border-collapse text-base">
          <thead>
            <tr>
              <th class="pnl-size-th text-left">Размер</th>
              <th class="pnl-size-th">Продано</th>
              <th class="pnl-size-th">Возвраты</th>
              <th
                class="pnl-size-th"
                title="Продано против плеч логистики «к клиенту» за тот же период — прямое измерение: размер есть в строках логистики, а в заказах воронки его нет"
              >
                Выкуп
              </th>
              <th
                class="pnl-size-th"
                title="Насколько выкуп этого размера отличается от среднего по артикулу"
              >
                К среднему
              </th>
              <th class="pnl-size-th">Цена</th>
              <th class="pnl-size-th">Выручка</th>
              <th class="pnl-size-th">СПП</th>
              <th class="pnl-size-th">Логистика</th>
              <th class="pnl-size-th">Доля лог.</th>
              <th class="pnl-size-th" title="Логистика на одно плечо «к клиенту»">Лог/доставку</th>
              <th class="pnl-size-th">Штрафы</th>
              <th class="pnl-size-th">Себест.</th>
              <th class="pnl-size-th">К перечислению</th>
              <th
                class="pnl-size-th"
                title="Выплата WB минус себестоимость. Не «чистая прибыль»: рекламы в разрезе размеров у WB нет, на строке артикула она учтена"
              >
                Маржа без рекламы
              </th>
              <th class="pnl-size-th">Маржа %</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="size in state.data.rows" :key="size.ts_name">
              <td class="pnl-size-td text-left font-medium text-primary">{{ size.ts_name }}</td>
              <td class="pnl-size-td">{{ units(size.sold_units) }}</td>
              <td class="pnl-size-td">
                {{ size.returned_units ? units(size.returned_units) : '—' }}
              </td>
              <td class="pnl-size-td" :class="toneClass('buyoutPct', size.buyout_pct)">
                {{ pct(size.buyout_pct) }}
              </td>
              <td
                class="pnl-size-td"
                :class="toneClass('buyoutVsArticlePp', size.buyout_vs_article_pp)"
              >
                {{ deltaPp(size.buyout_vs_article_pp) }}
              </td>
              <td class="pnl-size-td">{{ money(size.average_cheque) }}</td>
              <td class="pnl-size-td">{{ money(size.revenue_seller_price) }}</td>
              <td class="pnl-size-td">{{ pct(size.spp_pct) }}</td>
              <td class="pnl-size-td">{{ money(size.logistics_total) }}</td>
              <td class="pnl-size-td" :class="toneClass('logisticsPct', size.logistics_pct)">
                {{ pct(size.logistics_pct) }}
              </td>
              <td class="pnl-size-td">{{ money(size.logistics_per_delivery) }}</td>
              <td class="pnl-size-td">
                {{ n(size.penalties_total) ? money(size.penalties_total) : '—' }}
              </td>
              <td class="pnl-size-td">{{ money(size.cogs) }}</td>
              <td class="pnl-size-td">{{ money(size.payout_net) }}</td>
              <td class="pnl-size-td" :class="amountClass(size.margin_before_ads)">
                {{ money(size.margin_before_ads) }}
              </td>
              <td class="pnl-size-td" :class="toneClass('profitPct', size.margin_pct)">
                {{ pct(size.margin_pct) }}
              </td>
            </tr>
          </tbody>
          <tfoot>
            <tr>
              <td class="pnl-size-td pnl-size-foot text-left">Итого по размерам</td>
              <td class="pnl-size-td pnl-size-foot">{{ units(state.data.totals.sold_units) }}</td>
              <td class="pnl-size-td pnl-size-foot">
                {{
                  state.data.totals.returned_units ? units(state.data.totals.returned_units) : '—'
                }}
              </td>
              <td class="pnl-size-td pnl-size-foot">{{ pct(state.data.totals.buyout_pct) }}</td>
              <td class="pnl-size-td pnl-size-foot"></td>
              <td class="pnl-size-td pnl-size-foot">
                {{ money(state.data.totals.average_cheque) }}
              </td>
              <td class="pnl-size-td pnl-size-foot">
                {{ money(state.data.totals.revenue_seller_price) }}
              </td>
              <td class="pnl-size-td pnl-size-foot">{{ pct(state.data.totals.spp_pct) }}</td>
              <td class="pnl-size-td pnl-size-foot">
                {{ money(state.data.totals.logistics_total) }}
              </td>
              <td class="pnl-size-td pnl-size-foot">{{ pct(state.data.totals.logistics_pct) }}</td>
              <td class="pnl-size-td pnl-size-foot">
                {{ money(state.data.totals.logistics_per_delivery) }}
              </td>
              <td class="pnl-size-td pnl-size-foot">
                {{
                  n(state.data.totals.penalties_total)
                    ? money(state.data.totals.penalties_total)
                    : '—'
                }}
              </td>
              <td class="pnl-size-td pnl-size-foot">{{ money(state.data.totals.cogs) }}</td>
              <td class="pnl-size-td pnl-size-foot">{{ money(state.data.totals.payout_net) }}</td>
              <td class="pnl-size-td pnl-size-foot">
                {{ money(state.data.totals.margin_before_ads) }}
              </td>
              <td class="pnl-size-td pnl-size-foot">{{ pct(state.data.totals.margin_pct) }}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* Подтаблица живёт внутри ячейки основной таблицы, у которой уже есть свои
   отступы и `white-space: nowrap` от `.app-datatable tbody td`. Поэтому здесь
   свои классы, а не наследование скина: иначе строки размеров получают
   вертикальный ритм родителя и блок вырастает на два экрана. */
.pnl-size-th {
  @apply whitespace-nowrap border-b border-border-subtle px-sm py-xs text-right text-micro font-medium uppercase tracking-wider text-muted;
}

.pnl-size-td {
  @apply whitespace-nowrap border-b border-border-subtle px-sm py-xs text-right tabular-nums text-primary;
}

.pnl-size-foot {
  @apply border-b-0 border-t border-border-subtle font-medium;
}
</style>
