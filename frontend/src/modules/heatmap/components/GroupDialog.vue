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
import { computed, ref, watch } from 'vue'

import SearchField from '@/core/components/SearchField.vue'
import SkuThumb from '@/core/components/SkuThumb.vue'
import UiDialog from '@/core/components/UiDialog.vue'
import { confirmLabel, useConfirmClick } from '@/core/utils/confirmClick'
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
const removal = useConfirmClick()

watch(
  () => props.open,
  (open) => {
    if (!open) return
    name.value = props.group?.name ?? ''
    picked.value = new Set(props.group?.nm_ids ?? [])
    query.value = ''
    removal.disarm()
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
  removal.press('group', () => emit('delete', props.group.id))
}

function close() {
  if (!props.busy) emit('close')
}
</script>

<template>
  <UiDialog :open="open" :title="group ? 'Группа' : 'Новая группа'" :busy="busy" @close="close">
    <label class="block text-tiny font-medium text-muted" for="group-name"> Название </label>
    <input
      id="group-name"
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
    <SearchField
      v-model="query"
      class="mt-xs"
      placeholder="Артикул продавца или WB, название"
      aria-label="Поиск артикула"
    />

    <ul class="mt-sm min-h-0 flex-1 overflow-y-auto">
      <li v-for="card in shown" :key="card.nm_id">
        <button
          type="button"
          class="ui-option"
          :aria-pressed="picked.has(card.nm_id)"
          @click="toggle(card.nm_id)"
        >
          <span class="ui-check" :class="{ 'is-on': picked.has(card.nm_id) }" aria-hidden="true"
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

    <template #footer>
      <button
        v-if="group"
        type="button"
        class="ui-btn ui-btn--danger mr-auto"
        :class="{ 'is-armed': removal.isArmed('group') }"
        :disabled="busy"
        @click="remove"
      >
        {{ removal.isArmed('group') ? confirmLabel('Удалить') : 'Удалить' }}
      </button>
      <button type="button" class="ui-btn" :disabled="busy" @click="close">Отмена</button>
      <button type="button" class="ui-btn ui-btn--primary" :disabled="!canSave" @click="save">
        {{ busy ? 'Сохраняем…' : 'Сохранить' }}
      </button>
    </template>
  </UiDialog>
</template>
