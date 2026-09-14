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
 * The rules mirror `UserRegisterRequest`: at least 8 characters, one lower and
 * one upper. Stated here as well as enforced there, so the form does not let
 * somebody submit a password it could have told them about.
 */
import { computed, ref } from 'vue'

const props = defineProps({
  saving: { type: Boolean, default: false },
  /** Server-side refusal, rendered verbatim. */
  error: { type: String, default: '' },
  /** How many other sessions the last successful change ended, or null. */
  endedSessions: { type: [Number, null], default: null },
})

const emit = defineEmits(['submit', 'clear-error'])

const current = ref('')
const next = ref('')
const repeat = ref('')
const reveal = ref(false)

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
  <form class="lp-pw" @submit.prevent="onSubmit">
    <div class="lp-pw__fields">
      <label class="lp-pw__field">
        <span class="lp-field__label">Текущий пароль</span>
        <input
          v-model="current"
          :type="reveal ? 'text' : 'password'"
          autocomplete="current-password"
          class="lp-input"
          @input="emit('clear-error')"
        />
      </label>

      <label class="lp-pw__field">
        <span class="lp-field__label">Новый пароль</span>
        <input
          v-model="next"
          :type="reveal ? 'text' : 'password'"
          autocomplete="new-password"
          class="lp-input"
          @input="emit('clear-error')"
        />
      </label>

      <label class="lp-pw__field">
        <span class="lp-field__label">Новый пароль ещё раз</span>
        <input
          v-model="repeat"
          :type="reveal ? 'text' : 'password'"
          autocomplete="new-password"
          class="lp-input"
          :class="mismatch ? 'is-wrong' : ''"
        />
      </label>
    </div>

    <label class="lp-pw__reveal">
      <input v-model="reveal" type="checkbox" class="accent-[var(--ui-action)]" />
      Показать пароли
    </label>

    <ul class="lp-pw__rules">
      <li v-for="rule in RULES" :key="rule.key" :class="rule.test(next) ? 'is-met' : ''">
        {{ rule.label }}
      </li>
    </ul>

    <p v-if="sameAsCurrent" class="lp-pw__warn">Новый пароль совпадает с текущим.</p>
    <p v-else-if="mismatch" class="lp-pw__warn">Пароли не совпадают.</p>
    <p v-else-if="error" class="lp-pw__warn">{{ error }}</p>
    <p v-else-if="endedSessions !== null" class="lp-pw__ok">
      Пароль изменён.
      <template v-if="endedSessions > 0">
        Другие устройства вышли из аккаунта — {{ endedSessions }}.
      </template>
      <template v-else> Других активных входов не было. </template>
    </p>
    <p v-else class="lp-pw__note">
      После смены пароля все остальные устройства выйдут из аккаунта. Это устройство останется.
    </p>

    <div>
      <button type="submit" class="lp-btn lp-btn--primary" :disabled="!canSubmit">
        {{ saving ? 'Меняем…' : 'Сменить пароль' }}
      </button>
    </div>
  </form>
</template>

<style scoped>
.lp-pw {
  @apply flex flex-col gap-md;
}

.lp-pw__fields {
  @apply grid gap-md;
  grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
}

.lp-pw__field {
  @apply flex flex-col gap-xs;
}

.lp-field__label {
  @apply text-tiny font-semibold uppercase tracking-wide;
  color: var(--ui-faint);
}

.lp-input.is-wrong {
  border-color: var(--ui-neg);
}

.lp-pw__reveal {
  @apply flex w-fit cursor-pointer items-center gap-xs text-tiny font-medium;
  color: var(--ui-muted);
}

.lp-pw__rules {
  @apply flex flex-wrap gap-x-md gap-y-xs text-tiny font-medium;
  color: var(--ui-faint);
}

.lp-pw__rules li::before {
  content: '○ ';
}

.lp-pw__rules li.is-met {
  color: var(--ui-pos);
}

.lp-pw__rules li.is-met::before {
  content: '● ';
}

.lp-pw__note {
  @apply text-tiny font-medium;
  color: var(--ui-muted);
}

.lp-pw__warn {
  @apply text-tiny font-semibold;
  color: var(--ui-neg);
}

.lp-pw__ok {
  @apply text-tiny font-semibold;
  color: var(--ui-pos);
}
</style>
