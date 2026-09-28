<script setup>
/**
 * The result grid on a narrow screen: one photo at a time, metrics as a list.
 *
 * A grid of photos × metrics has no «record» to fold into a card, so the
 * phone-layout skill's answer for a matrix applies — **page the repeating
 * axis**. The photos are that axis: pick one, read its six figures down the
 * screen, step to the next with the pager. The alternative was tried on the
 * metrics matrix and is wrong twice over: sized to fit, ten columns land around
 * 30px and the numbers print on top of one another; sized to their content, the
 * reader swipes sideways and loses the row they were on.
 *
 * It renders the SAME projection the table does — see `variantColumns.js` — so
 * there is one grid with two renderings and never two sources of truth.
 *
 * The «Результат» figure keeps comparing against the whole set rather than
 * against the photo shown next to it. Paging changes what is on screen, not
 * what the number means.
 *
 * Gated at `sm:` rather than `phone:`, because swapping one component for
 * another is a capability threshold: at 431–639px the table's ten columns are
 * still unreadable, and a `phone:` gate would leave that band rendering it.
 */
import { computed, ref, watch } from 'vue'

import { METRICS, cellFor, leaderOf, variantTitle } from '@/modules/abTests/variantColumns'

const props = defineProps({
  /** Photos with their figures, already projected for the chosen lap. */
  columns: { type: Array, required: true },
  /** variant_id -> object URL for the stored original. */
  imageUrls: { type: Object, default: () => ({}) },
  /** True while a write is in flight. */
  saving: { type: Boolean, default: false },
})
defineEmits(['exclude'])

const index = ref(0)

// A photo excluded or added while the pager is open can shorten the list under
// the reader; without this the pager lands past the end and renders nothing.
watch(
  () => props.columns.length,
  (length) => {
    if (index.value >= length) index.value = Math.max(0, length - 1)
  },
)

const current = computed(() => props.columns[index.value] ?? null)
const leaderId = computed(() => leaderOf(props.columns))

function step(delta) {
  const length = props.columns.length
  if (!length) return
  index.value = (index.value + delta + length) % length
}

function cell(metric) {
  return cellFor(current.value, metric, { leaderId: leaderId.value })
}

/** This sheet's own colour modifier — see the table for why not a utility. */
function tone(metric) {
  const name = cell(metric).tone
  return name ? `ab-pager__value--${name}` : ''
}
</script>

<template>
  <section
    v-if="current"
    class="overflow-hidden rounded-card bg-surface shadow-card"
    data-testid="variant-pager"
  >
    <header class="flex items-center gap-md border-b border-border-subtle p-md">
      <button type="button" class="ab-pager__step" aria-label="Предыдущее фото" @click="step(-1)">
        ‹
      </button>

      <div class="relative flex-none">
        <img
          v-if="imageUrls[current.variant_id]"
          :src="imageUrls[current.variant_id]"
          :alt="variantTitle(current)"
          class="ab-pager__photo"
          :class="current.is_excluded ? 'is-excluded' : ''"
        />
        <div v-else class="ab-pager__photo ab-pager__photo--empty"></div>
      </div>

      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-sm">
          <span v-if="current.is_original" class="ab-badge">Главное</span>
          <span v-else class="text-base font-semibold text-primary">
            {{ variantTitle(current) }}
          </span>
        </div>
        <div class="mt-px text-micro text-muted">Фото {{ index + 1 }} из {{ columns.length }}</div>
        <div v-if="current.is_active" class="text-micro font-semibold text-status-positive">
          Сейчас на карточке
        </div>

        <button
          type="button"
          class="mt-xs rounded-btn px-xs py-px text-micro font-semibold transition"
          :class="
            current.is_excluded
              ? 'text-action hover:bg-action/10'
              : 'text-muted hover:bg-hover hover:text-status-negative'
          "
          :disabled="saving"
          data-testid="toggle-exclusion"
          @click="$emit('exclude', current.variant_id, !current.is_excluded)"
        >
          {{ current.is_excluded ? 'Вернуть в ротацию' : 'Убрать из ротации' }}
        </button>
      </div>

      <button type="button" class="ab-pager__step" aria-label="Следующее фото" @click="step(1)">
        ›
      </button>
    </header>

    <dl class="ab-pager__figures">
      <div v-for="metric in METRICS" :key="metric.key" class="ab-pager__figure">
        <dt>{{ metric.label }}</dt>
        <dd class="tabular-nums" :class="tone(metric)">{{ cell(metric).text }}</dd>
      </div>
    </dl>
  </section>
</template>

<style scoped src="@/modules/abTests/components/styles/VariantMetricsPager.css"></style>
