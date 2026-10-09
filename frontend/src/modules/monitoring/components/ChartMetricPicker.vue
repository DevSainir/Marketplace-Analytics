<script setup>
/**
 * The metric chips above a chart, in the groups the caller hands it.
 *
 * The groups carry NO behaviour — they are where a reader looks for a metric,
 * nothing more, and the chart repeats the same split in its hover so the two
 * agree. Laid out in one row so all three are readable at a glance rather than
 * a wall to scan.
 *
 * Dumb by contract: groups in, selection out.
 */
const props = defineProps({
  /** @type {Array<{title: string, items: Array<{key: string, name: string}>}>} */
  groups: { type: Array, required: true },
  /** Selected metric keys; the chart sorts them back into catalogue order. */
  modelValue: { type: Array, default: () => [] },
})

const emit = defineEmits(['update:modelValue'])

/** Toggle one metric. */
function toggle(key) {
  emit(
    'update:modelValue',
    props.modelValue.includes(key)
      ? props.modelValue.filter((entry) => entry !== key)
      : [...props.modelValue, key],
  )
}
</script>

<template>
  <div>
    <!-- One row, three cards: `flex-1 min-w-0` lets each group shrink to share
         the width and wrap its own chips, instead of the widest group pushing
         the others onto their own lines. Below `sm` they stack.

         A card each, rather than three headings inside one: the groups are
         three separate questions — what the advertising did, what the funnel
         did, what the card itself is — and the chips only ever combine WITHIN
         a group in practice. Glass because they are chrome sitting on the
         ambient ground, which is the surface the system reserves it for. -->
    <div class="flex flex-wrap items-start gap-md">
      <div
        v-for="group in groups"
        :key="group.title"
        class="ui-glass min-w-0 flex-1 rounded-card p-md sm:basis-0"
      >
        <p class="mb-xs text-tiny font-semibold uppercase tracking-wide text-muted">
          {{ group.title }}
        </p>
        <ul class="flex flex-wrap gap-xs">
          <li v-for="item in group.items" :key="item.key">
            <button
              type="button"
              :aria-pressed="modelValue.includes(item.key)"
              class="ui-chip"
              :class="{ 'is-on': modelValue.includes(item.key) }"
              @click="toggle(item.key)"
            >
              {{ item.name }}
            </button>
          </li>
        </ul>
      </div>
    </div>

    <p v-if="!modelValue.length" class="py-xl text-center text-base text-muted">
      Выберите метрики, которые хотите сравнить на одном графике.
    </p>
  </div>
</template>
