<script setup>
/**
 * The «Не включать в общий счёт» mark — the last column of the per-article
 * report.
 *
 * The column has no caption (a header would eat width the table does not
 * have), so a hover tooltip explains what the checkbox means. It opens to the
 * LEFT: the column is the rightmost one, and a tooltip popping out to the right
 * spills past the edge of the scroll area.
 */
defineProps({
  checked: { type: Boolean, default: false },
})

defineEmits(['change'])
</script>

<template>
  <label class="group relative flex items-center justify-center" title="Не включать в общий счёт">
    <input
      type="checkbox"
      :checked="checked"
      aria-label="Не включать в общий счёт"
      class="h-4 w-4 cursor-pointer accent-action"
      @change="$emit('change', $event.target.checked)"
    />
    <span
      class="pointer-events-none absolute right-full top-1/2 z-20 mr-sm hidden -translate-y-1/2 whitespace-nowrap rounded-input border border-border-subtle bg-surface px-sm py-xs text-tiny text-primary shadow-card group-hover:block"
    >
      Не включать в общий счёт
    </span>
  </label>
</template>
