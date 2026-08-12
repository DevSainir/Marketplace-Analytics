<script setup>
/**
 * WB token editor for one workspace (dumb component).
 *
 * Two modes, driven by `isPrimary`:
 *  - primary workspace: one password input per WB API category (13 of them),
 *    for granular per-category tokens;
 *  - any other workspace: a single "unified" token reused for all categories.
 *
 * Stored values are never shown — `configured` only lists which kinds have a
 * token. Leaving a field blank keeps the stored token; the «Очистить» toggle
 * deletes it. Emits `save` with a `{kind: value}` map where a value is a new
 * token, '' deletes, and an untouched field is omitted.
 */
import { computed, reactive, ref } from 'vue'

const props = defineProps({
  isPrimary: { type: Boolean, default: false },
  /** Kind slugs that currently have a stored token. */
  configured: { type: Array, default: () => [] },
  saving: { type: Boolean, default: false },
})

const emit = defineEmits(['save'])

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

const UNIFIED = [{ key: 'unified', label: 'Единый токен — используется для всех категорий' }]

const fields = computed(() => (props.isPrimary ? CATEGORIES : UNIFIED))

const values = reactive({})
const clearFlags = reactive({})
const saved = ref(false)

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
  <form class="flex flex-col gap-md" @submit.prevent="onSubmit">
    <div v-for="field in fields" :key="field.key" class="flex flex-col gap-xs">
      <div class="flex items-center justify-between">
        <label :for="`token-${field.key}`" class="text-tiny font-medium text-muted">
          {{ field.label }}
        </label>
        <span
          class="rounded-btn px-sm py-xs text-tiny font-semibold"
          :class="
            isConfigured(field.key)
              ? 'bg-status-positive/10 text-status-positive'
              : 'bg-status-warning/10 text-status-warning'
          "
        >
          {{ isConfigured(field.key) ? 'Задан' : 'Не задан' }}
        </span>
      </div>
      <input
        :id="`token-${field.key}`"
        v-model="values[field.key]"
        type="password"
        autocomplete="off"
        :disabled="clearFlags[field.key]"
        placeholder="Вставьте новый токен (пусто — без изменений)"
        class="w-full rounded-input border border-border-subtle bg-canvas px-md py-sm text-base text-primary placeholder:text-muted focus:border-action focus:outline-none disabled:opacity-50 phone:min-h-11"
      />
      <label
        v-if="isConfigured(field.key)"
        class="flex items-center gap-xs text-tiny font-medium text-muted"
      >
        <input v-model="clearFlags[field.key]" type="checkbox" class="accent-action" />
        Очистить сохранённый токен
      </label>
    </div>

    <div class="flex items-center gap-md phone:flex-col phone:items-stretch phone:gap-sm">
      <button
        type="submit"
        :disabled="saving"
        class="rounded-btn bg-action px-md py-sm text-base font-semibold text-white transition hover:bg-action-hover disabled:opacity-50 phone:min-h-11"
      >
        {{ saving ? 'Сохранение…' : 'Сохранить токены' }}
      </button>
      <span v-if="saved && !saving" class="text-tiny font-medium text-status-positive">
        Сохранено — значения зашифрованы в базе.
      </span>
    </div>
  </form>
</template>
