<script setup>
/**
 * The disambiguation strip for a vendor-code search that matched several SKUs.
 *
 * Shown instead of guessing. A fragment like "M-TRX" legitimately names a whole
 * colour family, and silently opening one of them would look like the app
 * ignored the search — so the matches are offered as chips and the user picks.
 *
 * Dumb by contract: it renders the matches and emits `select`.
 */
import { formatSku, plural } from '@/core/utils/format'

defineProps({
  /** @type {Array<{nm_id: number, vendor_code: string, title: string}>} */
  matches: { type: Array, required: true },
})

defineEmits(['select'])
</script>

<template>
  <!-- Ambiguous vendor-code deep link: let the user pick the exact SKU -->
  <section
    v-if="matches.length"
    class="mt-lg rounded-card border border-border-subtle bg-surface p-lg shadow-card phone:p-md"
  >
    <p class="text-base font-medium text-primary">
      {{ matches.length }} {{ plural(matches.length, ['SKU matches', 'SKUs match']) }} — pick one:
    </p>
    <div class="mt-sm flex flex-wrap gap-sm">
      <button
        v-for="match in matches"
        :key="match.nm_id"
        type="button"
        class="inline-flex max-w-full items-center gap-sm rounded-btn border border-border-subtle bg-surface px-sm py-xs text-base shadow-soft transition hover:border-action hover:bg-action/10"
        @click="$emit('select', match)"
      >
        <span class="font-semibold text-primary">{{ formatSku(match.vendor_code) }}</span>
        <span class="truncate text-tiny text-muted">{{ match.title }}</span>
      </button>
    </div>
  </section>
</template>
