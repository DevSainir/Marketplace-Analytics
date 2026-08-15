<script setup>
/**
 * The «Закрепить» cards: one small card per pinned phrase, with the last
 * position recorded for it and when that was taken.
 *
 * Its own component rather than more markup in `SkuClusterBlock`, which is at
 * its 250-line ceiling — and because the three states a card can be in carry
 * the whole point of the feature and deserve to be read in one place:
 *
 * - never checked (`checked_at` null) — «—», because a pin made a minute ago has
 *   no number yet and a 0 would look like a rank;
 * - checked, not found — «вне выдачи» with the depth actually scanned, so «не в
 *   топ-300» never reads as «нет в WB»;
 * - a rank — the number, with its timestamp underneath. A position without the
 *   moment it was taken is not a fact anyone can act on.
 *
 * Dumb: props in, `unpin` out.
 */
defineProps({
  /** Backend `PinnedKeywordItem[]` for the page's SKU. */
  pins: { type: Array, required: true },
  /** Disables removal while a run is rewriting these very rows. */
  busy: { type: Boolean, default: false },
})

const emit = defineEmits(['unpin'])

/** «15.08, 19:37» — short: the card is small and the year is noise on a sample
 *  that is refreshed three times a day. */
const shortStamp = (iso) =>
  new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
</script>

<template>
  <ul class="mt-md grid list-none grid-cols-2 gap-sm p-0 phone:grid-cols-1 sm:grid-cols-3">
    <li
      v-for="item in pins"
      :key="item.keyword"
      class="rounded-card border border-border-subtle bg-surface p-md shadow-card"
    >
      <div class="flex items-start justify-between gap-xs">
        <p class="text-base font-medium text-primary" :title="item.keyword">{{ item.keyword }}</p>
        <button
          type="button"
          class="shrink-0 rounded-btn px-xs text-tiny font-medium text-muted transition hover:text-primary disabled:opacity-50"
          :disabled="busy"
          :aria-label="`Открепить «${item.keyword}»`"
          @click="emit('unpin', item.keyword)"
        >
          ✕
        </button>
      </div>

      <p class="mt-xs text-base text-primary">
        Позиция:
        <span v-if="item.position" class="text-h3 font-bold">{{ item.position }}</span>
        <!-- Checked and absent is not the same as never checked, and neither is
             a zero — both render as words, never as a number. -->
        <span v-else-if="item.checked_at" class="text-tiny font-medium text-muted">
          вне первых {{ item.positions_scanned }}
        </span>
        <span v-else class="text-tiny font-medium text-muted">—</span>
      </p>

      <p class="mt-xs text-tiny font-medium text-muted">
        <template v-if="item.checked_at">
          Дата обновления: {{ shortStamp(item.checked_at) }}
        </template>
        <template v-else>Ещё не проверялся</template>
      </p>
    </li>
  </ul>
</template>
