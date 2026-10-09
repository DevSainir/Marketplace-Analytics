<script setup>
/**
 * «Добавить группу» / editing one: a name and a hand-picked set of articles.
 *
 * One form, one «Сохранить» — the group is replaced whole, name and members
 * together, so a failed save leaves nothing half-edited behind. Deleting asks
 * twice (the second click is the confirmation), because a group is shared by
 * everyone in the кабинет and is gone for all of them.
 *
 * Modal over a dimmed page, like the A/Б finish dialog: Escape and the backdrop
 * close it, except mid-save.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import SkuThumb from '@/core/components/SkuThumb.vue'
import { formatSku } from '@/core/utils/format'

const RENDER_LIMIT = 200

const props = defineProps({
  open: { type: Boolean, default: false },
  /** `null` for a new group, else `{id, name, nm_ids}`. */
  group: { type: Object, default: null },
  /** @type {Array<{nm_id: number, vendor_code: string, title: string, photo_url: string}>} */
  cards: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false },
  error: { type: String, default: '' },
})
const emit = defineEmits(['close', 'save', 'delete'])

const name = ref('')
const picked = ref(new Set())
const query = ref('')
const confirmDelete = ref(false)

watch(
  () => props.open,
  (open) => {
    document.body.style.overflow = open ? 'hidden' : ''
    if (!open) return
    name.value = props.group?.name ?? ''
    picked.value = new Set(props.group?.nm_ids ?? [])
    query.value = ''
    confirmDelete.value = false
  },
  { immediate: true },
)

const matches = computed(() => {
  const needle = query.value.trim().toLowerCase()
  if (!needle) return props.cards
  return props.cards.filter((card) =>
    [card.vendor_code, card.title, String(card.nm_id)].some((field) =>
      String(field ?? '')
        .toLowerCase()
        .includes(needle),
    ),
  )
})
const shown = computed(() => matches.value.slice(0, RENDER_LIMIT))
const canSave = computed(() => name.value.trim() && picked.value.size > 0 && !props.busy)

/** «Заказов: 12 · Костюм летний» — the orders are what the list is sorted by. */
function pickerNote(card) {
  const orders = `Заказов: ${card.orders ?? 0}`
  return card.title ? `${orders} · ${card.title}` : orders
}

function toggle(nmId) {
  const next = new Set(picked.value)
  if (next.has(nmId)) next.delete(nmId)
  else next.add(nmId)
  picked.value = next
}

function save() {
  if (!canSave.value) return
  emit('save', { id: props.group?.id, name: name.value.trim(), nm_ids: [...picked.value] })
}

function remove() {
  if (!confirmDelete.value) {
    confirmDelete.value = true
    return
  }
  emit('delete', props.group.id)
}

function close() {
  if (!props.busy) emit('close')
}

function onKey(event) {
  if (event.key === 'Escape' && props.open) close()
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  document.body.style.overflow = ''
})
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center p-md">
      <div class="absolute inset-0 bg-canvas/70" @click="close" />

      <section
        class="hm-dialog relative flex max-h-[85vh] w-full max-w-lg flex-col rounded-card bg-surface p-lg shadow-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="hm-group-title"
      >
        <h2 id="hm-group-title" class="text-h3 font-semibold text-primary">
          {{ group ? 'Группа' : 'Новая группа' }}
        </h2>

        <label class="mt-md block text-tiny font-medium text-muted" for="hm-group-name">
          Название
        </label>
        <input
          id="hm-group-name"
          v-model="name"
          type="text"
          maxlength="80"
          class="ui-input mt-xs w-full"
          placeholder="Например, спандекс_двойка"
        />

        <div class="mt-md flex items-center justify-between gap-sm">
          <span class="text-tiny font-medium text-muted">Артикулы</span>
          <span class="text-tiny text-muted">Выбрано: {{ picked.size }}</span>
        </div>
        <input
          v-model="query"
          type="search"
          class="ui-input mt-xs w-full"
          placeholder="Артикул продавца или WB, название"
          aria-label="Поиск артикула"
        />

        <ul class="mt-sm min-h-0 flex-1 overflow-y-auto">
          <li v-for="card in shown" :key="card.nm_id">
            <button
              type="button"
              class="hm-option"
              :aria-pressed="picked.has(card.nm_id)"
              @click="toggle(card.nm_id)"
            >
              <span class="hm-check" :class="{ 'is-on': picked.has(card.nm_id) }" aria-hidden="true"
                >✓</span
              >
              <SkuThumb :src="card.photo_url" :label="card.vendor_code" />
              <span class="min-w-0 flex-1">
                <span class="block truncate text-base text-primary">
                  {{ formatSku(card.vendor_code) ?? `Артикул WB ${card.nm_id}` }}
                </span>
                <span class="block truncate text-tiny text-muted">
                  {{ pickerNote(card) }}
                </span>
              </span>
            </button>
          </li>
        </ul>
        <p v-if="matches.length > shown.length" class="mt-xs text-tiny text-muted">
          Показано {{ shown.length }} из {{ matches.length }} — уточните поиск.
        </p>

        <p v-if="error" class="mt-sm text-base text-status-negative">{{ error }}</p>

        <footer class="mt-lg flex flex-wrap items-center gap-sm">
          <button v-if="group" type="button" class="ui-chip" :disabled="busy" @click="remove">
            {{ confirmDelete ? 'Точно удалить?' : 'Удалить' }}
          </button>
          <button type="button" class="ui-chip ml-auto" :disabled="busy" @click="close">
            Отмена
          </button>
          <button type="button" class="ui-chip is-on" :disabled="!canSave" @click="save">
            {{ busy ? 'Сохраняем…' : 'Сохранить' }}
          </button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>
