<script setup>
// Dumb period picker: an inclusive date window, edited in place and applied by
// the parent (nothing is fetched until the user hits «Применить»).
defineProps({
  from: { type: String, required: true },
  to: { type: String, required: true },
})

const emit = defineEmits(['update:from', 'update:to'])
</script>

<template>
  <div class="flex items-center gap-sm">
    <span class="text-tiny font-medium uppercase tracking-wider text-muted">Период</span>
    <input
      :value="from"
      type="date"
      required
      :max="to"
      class="h-9 rounded-input border border-border-subtle bg-surface px-sm text-base text-primary shadow-soft focus:border-action focus:outline-none focus:ring-2 focus:ring-action/20"
      @input="emit('update:from', $event.target.value)"
    />
    <span class="text-base text-muted" aria-hidden="true">—</span>
    <input
      :value="to"
      type="date"
      required
      :min="from"
      class="h-9 rounded-input border border-border-subtle bg-surface px-sm text-base text-primary shadow-soft focus:border-action focus:outline-none focus:ring-2 focus:ring-action/20"
      @input="emit('update:to', $event.target.value)"
    />
  </div>
</template>
