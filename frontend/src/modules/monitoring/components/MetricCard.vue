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
  neutral: 'text-slate-900',
  success: 'text-emerald-500',
  danger: 'text-rose-500',
  warning: 'text-amber-500',
}
</script>

<template>
  <article class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
    <p class="text-sm font-medium text-slate-500">{{ label }}</p>
    <p class="mt-2 text-3xl font-semibold tabular-nums tracking-tight" :class="toneClasses[tone]">
      {{ value }}
    </p>
    <p v-if="hint" class="mt-1 text-xs text-slate-400">{{ hint }}</p>
  </article>
</template>
