<script setup>
/**
 * «Ключи активации» — issuing a key to hand to a customer who paid.
 *
 * Shown to a dev and to the owner of the primary organisation; the API refuses everyone else.
 * The defaults are what is sold most often: 14 days of service, and nothing
 * else bounded. An empty limit field means «без лимита», which is why every
 * one of them is optional and only the term is required.
 *
 * The key is shown exactly once — the server stores only its hash — so it stays
 * on screen until the next key is issued.
 */
import { computed, ref } from 'vue'

import { extractErrorMessage } from '@/core/api/axios'
import { createActivationCode } from '@/modules/profile/api'
import { formatMoscowDate } from '@/core/utils/moscow'

const DEFAULT_DAYS = 14

const subscriptionDays = ref(DEFAULT_DAYS)
const validForDays = ref(null)
const maxWorkspaces = ref(null)
const maxManagers = ref(null)
const note = ref('')
const saving = ref(false)
const error = ref('')
const issued = ref(null)
const copied = ref(false)

/** An empty or zero field is «без лимита»; v-model.number hands back '' when cleared. */
function limit(value) {
  const n = Number(value)
  return value === '' || value === null || !Number.isFinite(n) || n <= 0 ? null : Math.floor(n)
}

const canSubmit = computed(() => limit(subscriptionDays.value) !== null && !saving.value)

function describe(value, unit) {
  return value === null ? 'без лимита' : `${value} ${unit}`
}

const summary = computed(() => {
  const key = issued.value
  if (!key) return []
  return [
    ['Пользование', `${key.subscription_days} дн.`],
    ['Ключ действует', key.expires_at ? `до ${formatMoscowDate(key.expires_at)}` : 'бессрочно'],
    ['Кабинеты', describe(key.max_workspaces, 'шт.')],
    ['Менеджеры', describe(key.max_managers, 'чел.')],
  ]
})

async function submit() {
  if (!canSubmit.value) return
  saving.value = true
  error.value = ''
  copied.value = false
  try {
    issued.value = await createActivationCode({
      note: note.value.trim(),
      subscriptionDays: limit(subscriptionDays.value),
      validForDays: limit(validForDays.value),
      maxWorkspaces: limit(maxWorkspaces.value),
      maxManagers: limit(maxManagers.value),
    })
    note.value = ''
  } catch (err) {
    error.value = extractErrorMessage(err)
  } finally {
    saving.value = false
  }
}

async function copyKey() {
  try {
    await navigator.clipboard.writeText(issued.value.code)
    copied.value = true
  } catch {
    // Refused over plain HTTP and in some browsers; the key is on screen and
    // selectable either way.
  }
}
</script>

<template>
  <div class="pf-panel">
    <header class="pf-panel__head">
      <div class="min-w-0">
        <h2 class="pf-panel__title">Ключи активации</h2>
        <p class="pf-panel__note">
          Ключ одноразовый. Пустое поле — без лимита. Срок пользования считается с момента ввода
          ключа.
        </p>
      </div>
    </header>

    <form class="flex flex-col gap-md" @submit.prevent="submit">
      <div class="key-grid">
        <label class="flex flex-col gap-xs">
          <span class="pf-field__label">Пользование, дней</span>
          <input
            v-model.number="subscriptionDays"
            type="number"
            min="1"
            max="3650"
            required
            class="ui-input w-full"
          />
        </label>
        <label class="flex flex-col gap-xs">
          <span class="pf-field__label">Ключ действует, дней</span>
          <input
            v-model.number="validForDays"
            type="number"
            min="1"
            max="365"
            placeholder="Бессрочно"
            class="ui-input w-full"
          />
        </label>
        <label class="flex flex-col gap-xs">
          <span class="pf-field__label">Кабинетов</span>
          <input
            v-model.number="maxWorkspaces"
            type="number"
            min="1"
            max="1000"
            placeholder="Без лимита"
            class="ui-input w-full"
          />
        </label>
        <label class="flex flex-col gap-xs">
          <span class="pf-field__label">Менеджеров</span>
          <input
            v-model.number="maxManagers"
            type="number"
            min="1"
            max="1000"
            placeholder="Без лимита"
            class="ui-input w-full"
          />
        </label>
      </div>

      <div class="key-row">
        <label class="flex min-w-0 flex-1 flex-col gap-xs">
          <span class="pf-field__label">Заметка (необязательно)</span>
          <input
            v-model="note"
            type="text"
            maxlength="256"
            placeholder="Кому и за сколько"
            class="ui-input w-full"
          />
        </label>
        <button type="submit" class="ui-btn ui-btn--primary" :disabled="!canSubmit">
          {{ saving ? 'Создаём…' : 'Создать ключ' }}
        </button>
      </div>

      <p v-if="error" class="pf-alert">{{ error }}</p>
    </form>

    <div v-if="issued" class="key-issued">
      <p class="pf-field__label">Ключ показывается один раз — скопируйте его сейчас.</p>
      <code class="key-issued__code">{{ issued.code }}</code>
      <dl class="key-issued__facts">
        <div v-for="[label, value] in summary" :key="label">
          <dt>{{ label }}</dt>
          <dd>{{ value }}</dd>
        </div>
      </dl>
      <button type="button" class="ui-btn ui-btn--good" @click="copyKey">
        {{ copied ? 'Скопировано' : 'Скопировать ключ' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.pf-field__label {
  @apply text-tiny font-semibold uppercase tracking-wide;
  color: var(--ui-faint);
}

.key-grid {
  @apply grid grid-cols-4 gap-md;
}

.key-row {
  @apply flex items-end gap-md;
}

.key-issued {
  @apply mt-md flex flex-col items-start gap-sm rounded-card px-md py-md;
  background: var(--ui-action-soft);
}

.key-issued__code {
  @apply block w-full break-all text-base font-semibold text-primary;
}

.key-issued__facts {
  @apply flex flex-wrap gap-x-lg gap-y-xs text-tiny;
}

.key-issued__facts dt {
  @apply inline font-medium text-muted;
}

.key-issued__facts dt::after {
  content: ': ';
}

.key-issued__facts dd {
  @apply inline font-semibold text-primary;
}

@media (max-width: 1023px) {
  .key-grid {
    @apply grid-cols-2;
  }
}

@media (max-width: 430px) {
  .key-grid {
    @apply grid-cols-1;
  }

  .key-row {
    @apply flex-col items-stretch;
  }
}
</style>
