<script setup>
/**
 * The result table: one row per photo, metrics as columns.
 *
 * Transposed relative to WB's own A/Б screen. WB compares exactly two images,
 * so it can afford variants as columns and metrics as rows; a rotation runs up
 * to ten, so **photos are the rows** — the picture itself in the first cell —
 * and the metrics are the columns.
 *
 * Three things about the layout, all of them fixes for a table that used to
 * spill out of its card and read as a jumble:
 *
 * * The type is the `ui-table` scale (12 px data, 9 px headers), not the page's
 *   `text-base`. Nine columns of `text-base` with `px-lg` padding do not fit a
 *   1280 px viewport, and the browser resolved that by overflowing the card.
 * * The headers are SHORT, with the full wording on `title`. «Доля переходов в
 *   карточку» is 25 characters of `white-space: nowrap` for a two-digit number.
 * * The photo is BIGGER — it is the thing being compared, so it is the one cell
 *   that should not be compact.
 *
 * On a phone the same rows render as cards instead: nine columns do not fit
 * 402 px, and the photos are the whole point of the screen.
 *
 * A ratio reads «—» rather than 0 % when its denominator is empty: a photo that
 * has not been live yet has not converted nobody, it has not been measured.
 */
defineProps({
  /** The open test, as the detail endpoint returns it. */
  test: { type: Object, required: true },
  /** variant_id -> object URL for the stored original. */
  imageUrls: { type: Object, default: () => ({}) },
  /** True while a write is in flight. */
  saving: { type: Boolean, default: false },
})
defineEmits(['remove'])

/**
 * The columns, in the order WB's own result screen uses: the three chained
 * ratios first, then the raw counts they are derived from.
 *
 * Declared once because the desktop header, the desktop cells and the phone
 * card all read from it — three copies of eight Russian labels is three places
 * for them to drift. `group` marks where a hairline separates ratios from
 * counts, and `full` is the wording the short header is an abbreviation of.
 */
const METRICS = [
  { key: 'click_through', short: 'Переходы, %', full: 'Доля переходов в карточку', ratio: true },
  { key: 'add_to_cart', short: 'Корзина, %', full: 'Доля добавлений в корзину', ratio: true },
  { key: 'order_rate', short: 'Заказы, %', full: 'Доля оформлений заказов', ratio: true },
  { key: 'views', short: 'Показы', full: 'Показы карточки в выдаче', group: true },
  { key: 'clicks', short: 'Переходы', full: 'Переходы в карточку' },
  { key: 'atbs', short: 'Корзины', full: 'Добавления в корзину' },
  { key: 'orders', short: 'Заказы', full: 'Оформления заказов' },
  { key: 'days_measured', short: 'Дней', full: 'Полных дней, зачтённых фото', group: true },
]

function percent(value) {
  return value === null || value === undefined ? '—' : `${Number(value).toFixed(2)} %`
}

function count(value) {
  return Number(value ?? 0).toLocaleString('ru-RU')
}

/** One cell's text: a ratio reads «—» when it has no denominator yet. */
function cell(variant, metric) {
  return metric.ratio ? percent(variant[metric.key]) : count(variant[metric.key])
}

/**
 * What the photo is called in its row.
 *
 * The card's own photo is at position 0 and was never uploaded, so «Вариант 0»
 * would be both wrong and confusing. It reads «Главное» — the same word the
 * seller cabinet uses for the slot it occupies — and it is otherwise an
 * ordinary row: same size photo, same columns, same place in the circle. That
 * is the point. A baseline shown apart from the candidates is a baseline the
 * reader has to be told to compare against.
 */
function title(variant) {
  return variant.is_original ? 'Главное' : `Вариант ${variant.position}`
}

/** What the photo's caption says about its place in the rotation. */
function standing(variant, test) {
  if (variant.is_active) return { text: 'Сейчас на карточке', class: 'text-status-positive' }
  if (variant.variant_id === test.leader_variant_id)
    return { text: 'Лидер по CTR', class: 'font-semibold text-action' }
  if (variant.is_original) return { text: 'Фото до теста', class: 'text-muted' }
  return null
}
</script>

<template>
  <section class="overflow-hidden rounded-card bg-surface shadow-card">
    <div class="overflow-x-auto phone:hidden">
      <table class="ui-table ab-results" data-testid="results">
        <thead>
          <tr>
            <th class="ab-results__photo-col">Фото</th>
            <th
              v-for="metric in METRICS"
              :key="metric.key"
              class="ta-r"
              :class="metric.group ? 'ab-results__group' : ''"
              :title="metric.full"
            >
              {{ metric.short }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="variant in test.variants"
            :key="variant.variant_id"
            :class="variant.variant_id === test.leader_variant_id ? 'is-leader' : ''"
            data-testid="variant-row"
          >
            <td class="ab-results__photo-col">
              <div class="flex items-center gap-md">
                <img
                  v-if="imageUrls[variant.variant_id]"
                  :src="imageUrls[variant.variant_id]"
                  :alt="title(variant)"
                  class="ab-photo"
                />
                <div v-else class="ab-photo ab-photo--empty"></div>
                <div class="min-w-0">
                  <div>
                    <span v-if="variant.is_original" class="ab-badge">Главное</span>
                    <span v-else class="text-tiny font-semibold text-primary">
                      {{ title(variant) }}
                    </span>
                  </div>
                  <div
                    v-if="standing(variant, test)"
                    class="mt-px text-micro"
                    :class="standing(variant, test).class"
                  >
                    {{ standing(variant, test).text }}
                  </div>
                  <button
                    v-if="!variant.is_active && !variant.is_original"
                    type="button"
                    class="mt-xs rounded-btn px-xs py-px text-micro text-muted transition hover:bg-hover hover:text-status-negative"
                    :disabled="saving"
                    data-testid="delete-variant"
                    @click="$emit('remove', variant.variant_id)"
                  >
                    Удалить фото
                  </button>
                </div>
              </div>
            </td>
            <td
              v-for="metric in METRICS"
              :key="metric.key"
              class="ta-r tabular-nums"
              :class="metric.group ? 'ab-results__group' : ''"
              :data-testid="metric.key === 'click_through' ? 'ctr' : null"
            >
              {{ cell(variant, metric) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Phone: the same rows as cards. `hidden phone:block`, not a `v-if` on a
         window width — one source of truth, rendered twice. -->
    <div class="hidden phone:block">
      <article
        v-for="variant in test.variants"
        :key="variant.variant_id"
        class="ab-card flex gap-md p-md"
        :class="variant.variant_id === test.leader_variant_id ? 'is-leader' : ''"
      >
        <div class="flex-none">
          <img
            v-if="imageUrls[variant.variant_id]"
            :src="imageUrls[variant.variant_id]"
            :alt="title(variant)"
            class="ab-photo"
          />
          <div v-else class="ab-photo ab-photo--empty"></div>
        </div>
        <div class="min-w-0 flex-1">
          <div class="flex items-baseline justify-between gap-sm">
            <span>
              <span v-if="variant.is_original" class="ab-badge">Главное</span>
              <span v-else class="text-tiny font-semibold text-primary">{{ title(variant) }}</span>
            </span>
            <button
              v-if="!variant.is_active && !variant.is_original"
              type="button"
              class="flex-none rounded-btn px-xs py-px text-micro text-muted"
              :disabled="saving"
              @click="$emit('remove', variant.variant_id)"
            >
              Удалить
            </button>
          </div>
          <div
            v-if="standing(variant, test)"
            class="text-micro"
            :class="standing(variant, test).class"
          >
            {{ standing(variant, test).text }}
          </div>
          <div class="ab-card__figures mt-xs">
            <div v-for="metric in METRICS" :key="metric.key" class="ab-card__figure">
              <span class="truncate text-micro text-muted">{{ metric.short }}</span>
              <span class="flex-none text-micro tabular-nums text-primary">
                {{ cell(variant, metric) }}
              </span>
            </div>
          </div>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped src="@/modules/abTests/components/styles/VariantResultsTable.css"></style>
