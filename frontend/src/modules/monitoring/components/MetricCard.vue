<script setup>
// Dumb presentational card: props in, nothing out.
defineProps({
  label: { type: String, required: true },
  value: { type: String, required: true },
  hint: { type: String, default: '' },
  tone: {
    type: String,
    default: 'neutral',
    validator: (v) => ['neutral', 'success', 'danger', 'warning'].includes(v),
  },
})

const toneClasses = {
  neutral: 'text-primary',
  success: 'text-status-positive',
  danger: 'text-status-negative',
  warning: 'text-status-warning',
}
</script>

<template>
  <article class="rounded-xl border border-border-subtle bg-white p-6 shadow-sm">
    <p class="text-sm font-medium text-muted">{{ label }}</p>
    <p class="mt-2 text-3xl font-semibold tabular-nums tracking-tight" :class="toneClasses[tone]">
      {{ value }}
    </p>
    <p v-if="hint" class="mt-1 text-xs text-muted">{{ hint }}</p>
  </article>
</template>
