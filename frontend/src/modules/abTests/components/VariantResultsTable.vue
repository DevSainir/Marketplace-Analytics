<script setup>
/**
 * The result table: one column per photo, metrics as rows.
 *
 * **This is the opposite orientation to the one this component used to have**,
 * and the reversal is deliberate. Photos-as-rows was chosen because a rotation
 * runs up to ten of them and ten rows fit a page where ten columns do not. What
 * that missed is what the table is *for*: every row here is a comparison across
 * photos, and a comparison reads along a line. «Показов» as a row puts ten
 * numbers side by side; as a column it puts them ten rows apart with seven
 * other figures in between. The width is paid for with one horizontal scroll,
 * which is the cheaper of the two costs.
 *
 * Four of the rows are derived rather than counted, and each is there because
 * the others mislead alone:
 *
 * * **Результат** — click-through relative to the leader. «-51 %» means «half
 *   as many clicks», which is a sentence to act on.
 * * **Отклонение от лучшего** — the same gap in percentage points, which is
 *   what the numbers literally differ by.
 * * **Побед в раундах** — laps this photo led. A photo that was up during one
 *   good hour carries the totals of the whole test on the strength of it; laps
 *   make that one vote instead of a multiplier.
 * * **Кругов** — how many laps it actually played, so «0 побед» from a photo
 *   that has run once is not read as «0 побед» from one that has run fifteen.
 *
 * Excluding a photo happens here because here is where the seller is looking
 * when they decide to. The cross sits on the picture, and an excluded column
 * greys out in place rather than disappearing: it keeps everything it earned,
 * and that record is the reason it was excluded.
 */
import { computed, ref } from 'vue'

import MetricHint from '@/modules/abTests/components/MetricHint.vue'
import VariantMetricsPager from '@/modules/abTests/components/VariantMetricsPager.vue'
import {
  METRICS,
  bestWinsOf,
  buildColumns,
  cellFor,
  leaderOf,
  variantTitle,
} from '@/modules/abTests/variantColumns'

const props = defineProps({
  /** The open test, as the detail endpoint returns it. */
  test: { type: Object, required: true },
  /** variant_id -> object URL for the stored original. */
  imageUrls: { type: Object, default: () => ({}) },
  /** True while a write is in flight. */
  saving: { type: Boolean, default: false },
  /** Which lap to show, or 0 for the whole test. */
  round: { type: Number, default: 0 },
})
const emit = defineEmits(['exclude'])

const columns = computed(() => buildColumns(props.test, props.round))
const leaderId = computed(() => leaderOf(columns.value))
const bestWins = computed(() => bestWinsOf(columns.value))

const hovered = ref(null)

/** One cell, read against the whole set rather than against its neighbour. */
function cell(variant, metric) {
  return cellFor(variant, metric, { leaderId: leaderId.value, bestWins: bestWins.value })
}

/**
 * The class that colours one figure.
 *
 * Through this sheet's own modifier, never a `text-status-*` utility: the
 * scoped `.ab-grid__value` sets a colour and outranks the utility, so a bare
 * one silently does nothing. See `cellFor`.
 */
function tone(variant, metric) {
  const name = cell(variant, metric).tone
  return name ? `ab-grid__value--${name}` : ''
}
</script>

<template>
  <section>
    <VariantMetricsPager
      class="sm:hidden"
      :columns="columns"
      :image-urls="imageUrls"
      :saving="saving"
      @exclude="(id, excluded) => emit('exclude', id, excluded)"
    />

    <div
      class="ab-grid__scroll hidden overflow-hidden rounded-card bg-surface shadow-card sm:block"
    >
      <table class="ab-grid" data-testid="results">
        <thead>
          <tr>
            <th class="ab-grid__label-col"></th>
            <th
              v-for="variant in columns"
              :key="variant.variant_id"
              class="ab-grid__photo-cell"
              :class="variant.is_excluded ? 'is-excluded' : ''"
              data-testid="variant-column"
              @mouseenter="hovered = variant.variant_id"
              @mouseleave="hovered = null"
            >
              <div class="ab-grid__photo-wrap">
                <img
                  v-if="imageUrls[variant.variant_id]"
                  :src="imageUrls[variant.variant_id]"
                  :alt="variantTitle(variant)"
                  class="ab-grid__photo"
                />
                <div v-else class="ab-grid__photo ab-grid__photo--empty"></div>

                <!-- The cross appears on hover, and stays put on an excluded
                     column so bringing a photo back is not a hidden gesture. -->
                <button
                  v-show="hovered === variant.variant_id || variant.is_excluded"
                  type="button"
                  class="ab-grid__cross"
                  :class="variant.is_excluded ? 'is-restore' : ''"
                  :disabled="saving"
                  :title="variant.is_excluded ? 'Вернуть в ротацию' : 'Убрать из ротации'"
                  :aria-label="variant.is_excluded ? 'Вернуть в ротацию' : 'Убрать из ротации'"
                  data-testid="toggle-exclusion"
                  @click="$emit('exclude', variant.variant_id, !variant.is_excluded)"
                >
                  {{ variant.is_excluded ? '↺' : '✕' }}
                </button>
              </div>

              <div class="ab-grid__caption">
                <span v-if="variant.is_original" class="ab-badge">Главное</span>
                <span v-else>{{ variantTitle(variant) }}</span>
              </div>
              <div v-if="variant.is_active" class="ab-grid__standing is-live">На карточке</div>
              <div v-else-if="variant.is_excluded" class="ab-grid__standing">Убрано</div>
            </th>
          </tr>
        </thead>

        <tbody>
          <tr v-for="metric in METRICS" :key="metric.key">
            <th class="ab-grid__label-col" scope="row">
              <span>{{ metric.label }}</span>
              <MetricHint v-if="metric.hint" :text="metric.hint" />
            </th>
            <td
              v-for="variant in columns"
              :key="variant.variant_id"
              class="ab-grid__value tabular-nums"
              :class="[variant.is_excluded ? 'is-excluded' : '', tone(variant, metric)]"
              :data-testid="metric.key === 'click_through' ? 'ctr' : null"
            >
              {{ cell(variant, metric).text }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped src="@/modules/abTests/components/styles/VariantResultsTable.css"></style>
