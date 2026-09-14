<script setup>
/**
 * Changing the password, in the form the backend actually supports.
 *
 * The old button mailed a reset code and then had nowhere to type it — the
 * flow could not be completed at all. It was built on the *forgotten*-password
 * endpoint, which is a different thing: a code proves a mailbox, which is all
 * that flow has to go on. Here the current password proves the caller, which is
 * the control OWASP names for a change made from inside a session, and there is
 * no code to wait for.
 *
 * Three fields rather than two. The repeat is not a security control — it
 * catches a typo in a value that is masked, before that typo becomes a password
 * nobody knows.
 *
 * The eye sits in every field and toggles all three at once. One checkbox under
 * the row was a control in a different place from the thing it controls; three
 * independent eyes would be three states to reason about for a value that is
 * the same in all three fields.
 *
 * The rules mirror `UserRegisterRequest`: at least 8 characters, one lower and
 * one upper. Stated here as well as enforced there, so the form does not let
 * somebody submit a password it could have told them about.
 */
import { computed, ref } from 'vue'

const props = defineProps({
  saving: { type: Boolean, default: false },
  /** Server-side refusal, rendered verbatim. */
  error: { type: String, default: '' },
})

const emit = defineEmits(['submit', 'clear-error'])

const current = ref('')
const next = ref('')
const repeat = ref('')
const reveal = ref(false)

/** One eye, three fields: the value is the same in all of them. */
const eyeLabel = computed(() => (reveal.value ? 'Скрыть пароли' : 'Показать пароли'))

const RULES = [
  { key: 'length', label: 'не короче 8 символов', test: (v) => v.length >= 8 },
  {
    key: 'lower',
    label: 'есть строчная буква',
    test: (v) => [...v].some((c) => c.toLowerCase() === c && c.toUpperCase() !== c),
  },
  {
    key: 'upper',
    label: 'есть заглавная буква',
    test: (v) => [...v].some((c) => c.toUpperCase() === c && c.toLowerCase() !== c),
  },
]

const failing = computed(() => RULES.filter((rule) => !rule.test(next.value)))
const mismatch = computed(() => repeat.value.length > 0 && repeat.value !== next.value)
const sameAsCurrent = computed(() => next.value.length > 0 && next.value === current.value)

const canSubmit = computed(
  () =>
    !props.saving &&
    current.value.length > 0 &&
    failing.value.length === 0 &&
    !mismatch.value &&
    !sameAsCurrent.value &&
    repeat.value === next.value,
)

function onSubmit() {
  if (!canSubmit.value) return
  emit('submit', { currentPassword: current.value, newPassword: next.value })
}

/** Called by the parent once the server accepted the change. */
function reset() {
  current.value = ''
  next.value = ''
  repeat.value = ''
}

defineExpose({ reset })
</script>

<template>
  <form class="pf-pw" @submit.prevent="onSubmit">
    <div class="pf-pw__fields">
      <label class="pf-pw__field">
        <span class="pf-field__label">Текущий пароль</span>
        <span class="pf-pw__wrap">
          <input
            v-model="current"
            :type="reveal ? 'text' : 'password'"
            autocomplete="current-password"
            class="pf-input"
            @input="emit('clear-error')"
          />
          <button type="button" class="pf-pw__eye" :aria-label="eyeLabel" @click="reveal = !reveal">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7Z" />
              <circle cx="12" cy="12" r="3" />
              <path v-if="reveal" d="m4 20 16-16" stroke-linecap="round" />
            </svg>
          </button>
        </span>
      </label>

      <label class="pf-pw__field">
        <span class="pf-field__label">Новый пароль</span>
        <span class="pf-pw__wrap">
          <input
            v-model="next"
            :type="reveal ? 'text' : 'password'"
            autocomplete="new-password"
            class="pf-input"
            @input="emit('clear-error')"
          />
          <button type="button" class="pf-pw__eye" :aria-label="eyeLabel" @click="reveal = !reveal">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7Z" />
              <circle cx="12" cy="12" r="3" />
              <path v-if="reveal" d="m4 20 16-16" stroke-linecap="round" />
            </svg>
          </button>
        </span>
      </label>

      <label class="pf-pw__field">
        <span class="pf-field__label">Новый пароль ещё раз</span>
        <span class="pf-pw__wrap">
          <input
            v-model="repeat"
            :type="reveal ? 'text' : 'password'"
            autocomplete="new-password"
            class="pf-input"
            :class="mismatch ? 'is-wrong' : ''"
          />
          <button type="button" class="pf-pw__eye" :aria-label="eyeLabel" @click="reveal = !reveal">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7Z" />
              <circle cx="12" cy="12" r="3" />
              <path v-if="reveal" d="m4 20 16-16" stroke-linecap="round" />
            </svg>
          </button>
        </span>
      </label>
    </div>

    <ul class="pf-pw__rules">
      <li v-for="rule in RULES" :key="rule.key" :class="rule.test(next) ? 'is-met' : ''">
        {{ rule.label }}
      </li>
    </ul>

    <p v-if="sameAsCurrent" class="pf-pw__warn">Новый пароль совпадает с текущим.</p>
    <p v-else-if="mismatch" class="pf-pw__warn">Пароли не совпадают.</p>
    <p v-else-if="error" class="pf-pw__warn">{{ error }}</p>

    <div>
      <button type="submit" class="pf-btn pf-btn--primary" :disabled="!canSubmit">
        {{ saving ? 'Меняем…' : 'Сменить пароль' }}
      </button>
    </div>
  </form>
</template>

<style scoped>
.pf-pw {
  @apply flex flex-col gap-md;
}

.pf-pw__fields {
  @apply grid gap-md;
  grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
}

.pf-pw__field {
  @apply flex flex-col gap-xs;
}

.pf-field__label {
  @apply text-tiny font-semibold uppercase tracking-wide;
  color: var(--ui-faint);
}

.pf-input.is-wrong {
  border-color: var(--ui-neg);
}

.pf-pw__wrap {
  @apply relative block;
}

.pf-pw__wrap .pf-input {
  padding-right: 40px;
}

.pf-pw__eye {
  @apply absolute right-0 top-0 grid h-full w-10 place-items-center transition;
  color: var(--ui-faint);
}

.pf-pw__eye:hover {
  color: var(--ui-muted);
}

.pf-pw__eye svg {
  @apply h-4 w-4;
}

.pf-pw__rules {
  @apply flex flex-wrap gap-x-md gap-y-xs text-tiny font-medium;
  color: var(--ui-faint);
}

.pf-pw__rules li::before {
  content: '○ ';
}

.pf-pw__rules li.is-met {
  color: var(--ui-pos);
}

.pf-pw__rules li.is-met::before {
  content: '● ';
}

.pf-pw__warn {
  @apply text-tiny font-semibold;
  color: var(--ui-neg);
}
</style>
