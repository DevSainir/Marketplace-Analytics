<script setup>
/**
 * «Какое изображение оставить на карточке?» — the question a finish asks.
 *
 * A test ends with whatever the rotation dealt last on the live card, which is
 * rarely the photo the seller wants to keep: the table above has just told them
 * which one earned the clicks. So finishing is a choice, made here, with every
 * photo of the test on offer — «Главное» and excluded ones included — each with
 * its picture, its name and its CTR.
 *
 * The photo with the best CTR is picked when the dialog opens, because that is
 * the answer the test was run to find; the one on the card now is marked, so
 * «leave it as it is» is one click away too.
 *
 * Modal over a dimmed page, like the profile drawer: the page behind is locked,
 * Escape and the backdrop close it — except mid-write, when closing would hide
 * the outcome of an upload to the live card.
 */
import { computed, ref, watch } from 'vue'

import UiDialog from '@/core/components/UiDialog.vue'

import { leaderOf, percent, variantTitle } from '@/modules/abTests/variantColumns'

const props = defineProps({
  open: { type: Boolean, default: false },
  /** The open test, as the detail endpoint returns it. */
  test: { type: Object, required: true },
  /** variant_id -> object URL for the stored original. */
  imageUrls: { type: Object, default: () => ({}) },
  /** True while the finish is in flight. */
  saving: { type: Boolean, default: false },
  /** Why the last attempt failed, if it did. */
  error: { type: String, default: '' },
})
const emit = defineEmits(['close', 'confirm'])

const variants = computed(() => props.test.variants ?? [])
const leaderId = computed(() => leaderOf(variants.value))
const chosen = ref(null)
// The store's error line is shared by every write on the page; only one this
// dialog caused belongs in it, not whatever an earlier upload left there.
const tried = ref(false)

watch(
  () => props.open,
  (open) => {
    if (open) {
      tried.value = false
      const live = variants.value.find((v) => v.is_active)
      chosen.value = leaderId.value ?? live?.variant_id ?? variants.value[0]?.variant_id ?? null
    }
  },
  { immediate: true },
)

function confirm() {
  tried.value = true
  emit('confirm', chosen.value)
}

function close() {
  if (!props.saving) emit('close')
}
</script>

<template>
  <UiDialog
    :open="open"
    title="Какое изображение оставить на карточке?"
    subtitle="Выбранное фото встанет главным на карточку WB, и тест завершится."
    :busy="saving"
    size="lg"
    data-testid="finish-dialog"
    @close="close"
  >
    <div
      class="ab-finish__body"
      role="radiogroup"
      aria-label="Изображение, которое останется на карточке"
    >
      <button
        v-for="variant in variants"
        :key="variant.variant_id"
        type="button"
        role="radio"
        :aria-checked="chosen === variant.variant_id"
        class="ab-finish__option"
        :class="{ 'is-chosen': chosen === variant.variant_id }"
        :disabled="saving"
        data-testid="finish-option"
        @click="chosen = variant.variant_id"
      >
        <img
          v-if="imageUrls[variant.variant_id]"
          :src="imageUrls[variant.variant_id]"
          :alt="variantTitle(variant)"
          class="ab-finish__photo"
        />
        <span v-else class="ab-finish__photo ab-finish__photo--empty" />
        <span class="mt-sm block text-base font-semibold text-primary">
          {{ variantTitle(variant) }}
        </span>
        <span class="block text-tiny text-muted tabular-nums">
          CTR {{ percent(variant.click_through) }}
        </span>
        <span class="mt-xs flex flex-wrap justify-center gap-xs">
          <span v-if="variant.variant_id === leaderId" class="ab-finish__tag is-best">
            Лучший CTR
          </span>
          <span v-if="variant.is_active" class="ab-finish__tag">На карточке</span>
          <span v-if="variant.is_excluded" class="ab-finish__tag">Убрано</span>
        </span>
      </button>
    </div>

    <template #footer>
      <p v-if="tried && error" class="mr-auto text-tiny text-status-negative">{{ error }}</p>
      <button type="button" class="ui-btn" :disabled="saving" @click="close">Отмена</button>
      <button
        type="button"
        class="ui-btn ui-btn--primary"
        :disabled="saving || !chosen"
        data-testid="finish-confirm"
        @click="confirm"
      >
        {{ saving ? 'Завершаем…' : 'Завершить тест' }}
      </button>
    </template>
  </UiDialog>
</template>

<style scoped>
.ab-finish__body {
  @apply grid grid-cols-2 gap-md sm:grid-cols-3 md:grid-cols-4;
}

.ab-finish__option {
  @apply rounded-card p-sm text-center transition disabled:cursor-not-allowed;
  background: var(--ui-sunk);
  outline: 2px solid transparent;
}

.ab-finish__option:hover:not(:disabled) {
  outline-color: rgb(var(--ui-action-rgb) / 35%);
}

.ab-finish__option.is-chosen {
  outline-color: var(--ui-action);
  background: rgb(var(--ui-action-rgb) / 8%);
}

.ab-finish__photo {
  @apply block w-full object-cover;
  /* The result table's 96 × 128 frame, scaled to the column. */
  aspect-ratio: 3 / 4;
  border-radius: var(--ui-r-md);
  box-shadow: var(--ui-sh-sm);
}

.ab-finish__photo--empty {
  background: var(--ui-hairline);
}

.ab-finish__tag {
  @apply rounded-btn px-xs py-px text-micro font-semibold;
  background: var(--ui-hairline);
  color: var(--ui-muted);
}

.ab-finish__tag.is-best {
  background: rgb(var(--ui-action-rgb) / 12%);
  color: var(--ui-action);
}
</style>
