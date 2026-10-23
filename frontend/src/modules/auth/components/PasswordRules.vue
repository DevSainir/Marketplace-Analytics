<script setup>
/**
 * What makes a password acceptable here, stated where it is being typed.
 *
 * Every rule listed here is one `users/schemas._validate_password` actually
 * enforces. The two must change together: a form that promises a rule the API
 * does not apply is misleading, and a rule the API applies without saying so
 * is a rejection the person cannot act on.
 *
 * There is no digit or punctuation requirement, and none is planned — length
 * plus the server's breach check is what keeps a password out of a wordlist.
 * The breach check is NOT listed: it is a range query only the server can make,
 * and a permanent grey "we will check this later" line is noise on every
 * password that was never going to fail it. It surfaces as an error when a
 * genuinely leaked password is submitted, which is the moment it means
 * something.
 */
import { computed } from 'vue'

const props = defineProps({
  value: { type: String, default: '' },
})

const MIN_CHARS = 8
//: bcrypt truncates at 72 BYTES, so the backend refuses anything longer rather
//: than silently ignoring the tail. In Greek or Cyrillic (two bytes a letter)
//: that is 36 characters, which
//: is reachable by a real person typing a passphrase — the reason this rule is
//: shown at all instead of treated as unreachable.
const MAX_BYTES = 72

const byteLength = computed(() => new TextEncoder().encode(props.value).length)
const longEnough = computed(() => props.value.length >= MIN_CHARS)
const shortEnough = computed(() => byteLength.value <= MAX_BYTES)
// Case is tested with the same Unicode rules the backend uses, so "Ωμέγα"
// satisfies this exactly as `Password` does. Comparing a character to its own
// upper/lower form is what makes that work without an alphabet list.
const hasLower = computed(() => [...props.value].some((c) => c.toUpperCase() !== c))
const hasUpper = computed(() => [...props.value].some((c) => c.toLowerCase() !== c))
const touched = computed(() => props.value.length > 0)
</script>

<template>
  <ul class="mt-xs flex flex-col gap-xs text-tiny font-medium">
    <li :class="touched && longEnough ? 'rule-met' : 'rule-pending'">
      <span aria-hidden="true">{{ touched && longEnough ? '✓' : '•' }}</span>
      At least {{ MIN_CHARS }} characters
    </li>
    <!-- Only once it is actually a problem: a limit nobody is near is noise. -->
    <li v-if="touched && !shortEnough" class="rule-broken">
      <span aria-hidden="true">✕</span>
      Too long — {{ MAX_BYTES }} bytes max (non-Latin letters take 2)
    </li>
    <li :class="touched && hasLower ? 'rule-met' : 'rule-pending'">
      <span aria-hidden="true">{{ touched && hasLower ? '✓' : '•' }}</span>
      At least one lowercase letter
    </li>
    <li :class="touched && hasUpper ? 'rule-met' : 'rule-pending'">
      <span aria-hidden="true">{{ touched && hasUpper ? '✓' : '•' }}</span>
      At least one uppercase letter
    </li>
  </ul>
</template>

<style scoped>
/* `--ui-*` read directly: a scoped `@apply text-status-positive` resolves the
   pre-skin palette from tailwind.config, not the skinned one. */
.rule-met,
.rule-pending,
.rule-broken {
  @apply flex items-center gap-xs;
}

.rule-met {
  color: var(--ui-pos);
}

.rule-pending {
  color: var(--ui-muted);
}

.rule-broken {
  color: var(--ui-neg);
}
</style>
