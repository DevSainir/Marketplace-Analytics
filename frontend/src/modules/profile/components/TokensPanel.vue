<script setup>
/**
 * WB token editor for one workspace — the drawer's contents.
 *
 * Same behaviour as the profile module's form (blank keeps the stored token,
 * «Очистить» deletes it, values are never read back), with one change that
 * only the new layout makes possible: the primary workspace's thirteen
 * categories are grouped and each row states its own status, instead of
 * thirteen identical password inputs inside a list item.
 */
import { computed, reactive, ref } from 'vue'

// The 13 real WB API categories, in seller-portal order (slug must match the
// backend TokenKind). Rendered only for the primary workspace.
const CATEGORIES = [
  { key: 'content', label: 'Контент' },
  { key: 'analytics', label: 'Аналитика' },
  { key: 'prices', label: 'Цены и скидки' },
  { key: 'marketplace', label: 'Маркетплейс' },
  { key: 'statistics', label: 'Статистика' },
  { key: 'promotion', label: 'Продвижение' },
  { key: 'feedback', label: 'Вопросы и отзывы' },
  { key: 'chat', label: 'Чат с покупателем' },
  { key: 'supplies', label: 'Поставки' },
  { key: 'returns', label: 'Возвраты' },
  { key: 'documents', label: 'Документы' },
  { key: 'finance', label: 'Финансы' },
  { key: 'users', label: 'Пользователи' },
]

const UNIFIED = [{ key: 'unified', label: 'Единый токен — для всех категорий' }]

const props = defineProps({
  isPrimary: { type: Boolean, default: false },
  configured: { type: Array, default: () => [] },
  saving: { type: Boolean, default: false },
})

const emit = defineEmits(['save'])

const fields = computed(() => (props.isPrimary ? CATEGORIES : UNIFIED))
const values = reactive({})
const clearFlags = reactive({})
const saved = ref(false)

const setCount = computed(() => fields.value.filter((f) => isConfigured(f.key)).length)

function isConfigured(key) {
  return props.configured.includes(key)
}

function onSubmit() {
  const tokens = {}
  for (const { key } of fields.value) {
    if (clearFlags[key]) {
      tokens[key] = ''
    } else if ((values[key] ?? '').trim()) {
      tokens[key] = values[key].trim()
    }
    // untouched (blank, not cleared) → omit so the stored token is kept
  }
  emit('save', tokens)
  saved.value = true
  for (const { key } of fields.value) {
    values[key] = ''
    clearFlags[key] = false
  }
}
</script>

<template>
  <form id="pf-tokens-form" class="flex flex-col gap-md" @submit.prevent="onSubmit">
    <p class="pf-tokens__count">
      Задано {{ setCount }} из {{ fields.length }}. Пустое поле — токен остаётся прежним.
    </p>

    <div v-for="field in fields" :key="field.key" class="pf-token">
      <div class="pf-token__head">
        <label :for="`pf-token-${field.key}`" class="pf-token__label">{{ field.label }}</label>
        <span class="pf-pill" :class="isConfigured(field.key) ? 'is-ok' : 'is-warn'">
          {{ isConfigured(field.key) ? 'Задан' : 'Не задан' }}
        </span>
      </div>
      <input
        :id="`pf-token-${field.key}`"
        v-model="values[field.key]"
        type="password"
        autocomplete="off"
        :disabled="clearFlags[field.key]"
        placeholder="Вставьте новый токен"
        class="ui-input w-full"
      />
      <label v-if="isConfigured(field.key)" class="pf-token__clear">
        <input v-model="clearFlags[field.key]" type="checkbox" class="accent-[var(--ui-neg)]" />
        Очистить сохранённый токен
      </label>
    </div>

    <p v-if="saved && !saving" class="pf-ok">Сохранено — значения зашифрованы в базе.</p>
  </form>
</template>

<style scoped>
.pf-tokens__count {
  @apply text-tiny font-medium;
  color: var(--ui-muted);
}

.pf-token {
  @apply flex flex-col gap-xs rounded-input px-md py-sm;
  background: var(--ui-sunk);
}

.pf-token__head {
  @apply flex items-center justify-between gap-sm;
}

.pf-token__label {
  @apply text-base font-medium text-primary;
}

.pf-token__clear {
  @apply flex items-center gap-xs text-tiny font-medium;
  color: var(--ui-muted);
}

.pf-ok {
  @apply text-tiny font-semibold;
  color: var(--ui-pos);
}
</style>
