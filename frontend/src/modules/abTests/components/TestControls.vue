<script setup>
/**
 * The test's controls: how many photos it holds, adding one, starting,
 * pausing and finishing — and the paragraph that says what «Главное» is.
 *
 * Its own component because the detail view was over the 250-line ceiling with
 * it inline.
 *
 * There are two upload buttons, and the tinted one is the baseline. «Главное»
 * used to arrive on its own: creating a test downloaded the card's live main
 * image from WB's CDN. What that fetched was a *rendition* — WB never serves
 * the seller's own file back — so every comparison was against a re-transcoded
 * copy, and each time the baseline came round again the rotation installed that
 * copy on the live card. It is an upload now, which is why it needs a control
 * of its own: nothing else in the rotation is allowed to be it, and there may
 * be only one.
 *
 * «Завершить» is offered from a pause as well as from a running test: a seller
 * who paused to look at the table and liked what they saw had no way to close
 * it short of starting it again first. It only asks for the finish; the view
 * opens the dialog that decides which photo the card keeps.
 *
 * «Запустить» asks twice when the rotation itself paused the test for want of
 * advertising: the campaign was dry on the last pass, and a start now is paused
 * again within five minutes. It stays possible — the seller may have just topped
 * the budget up — but it is no longer a click that silently undoes itself.
 *
 * Presentational: it performs no writes, so the view stays the one place that
 * knows about the store. The only state it holds is that confirmation.
 */
import { ref, watch } from 'vue'

import { MAX_VARIANTS } from '@/modules/abTests'

const props = defineProps({
  /** The open test, as the detail endpoint returns it. */
  test: { type: Object, required: true },
  /** Whether the test still has room for another upload. */
  canUpload: { type: Boolean, default: false },
  /** How many photos the test holds, «Главное» included. */
  uploadedCount: { type: Number, default: 0 },
  /** Whether a «Главное» photo has already been uploaded — at most one. */
  hasMainPhoto: { type: Boolean, default: false },
  /** True while a write is in flight. */
  saving: { type: Boolean, default: false },
})
const emit = defineEmits(['upload', 'upload-main', 'status', 'finish'])

const armed = ref(false)

// A confirmation belongs to the state it was asked in.
watch(
  () => [props.test.status, props.test.paused_by_ads],
  () => {
    armed.value = false
  },
)

/** Start — after a second press if nothing is advertising the card. */
function start() {
  if (props.test.paused_by_ads && !armed.value) {
    armed.value = true
    return
  }
  armed.value = false
  emit('status', 'running')
}
</script>

<template>
  <section
    class="mb-lg rounded-card border border-border-subtle bg-surface p-lg shadow-card phone:p-md"
  >
    <div class="flex flex-wrap items-center gap-md">
      <span class="text-h3 font-semibold text-primary">
        Фото в ротации: {{ uploadedCount }} из {{ MAX_VARIANTS }}
      </span>
      <!-- Tinted and first, because it is the one photo the whole table is
           read against: a rotation of candidates with no baseline answers
           «какое из них лучше» and not «стоит ли вообще менять». -->
      <label
        class="ui-btn ui-btn--primary cursor-pointer"
        :class="
          !canUpload || hasMainPhoto || saving
            ? 'cursor-not-allowed opacity-50'
            : 'cursor-pointer hover:bg-action-hover'
        "
        :title="hasMainPhoto ? 'Главное фото уже загружено — удалите его, чтобы заменить' : ''"
      >
        Добавить главное фото
        <input
          type="file"
          accept="image/*"
          data-testid="upload-main"
          :disabled="!canUpload || hasMainPhoto || saving"
          class="sr-only"
          @change="$emit('upload-main', $event)"
        />
      </label>
      <!-- The native control renders «Choose Files / No file chosen» in the
           browser's own language and cannot be restyled past the button; the
           input is hidden behind a real one instead. It stays in the DOM —
           `sr-only`, not `v-if` — because that is what the file dialog and
           the browser tier both drive. -->
      <label
        class="inline-flex h-10 items-center justify-center rounded-btn bg-surface px-lg text-base font-medium text-primary shadow-soft transition"
        :class="
          !canUpload || saving ? 'cursor-not-allowed opacity-50' : 'cursor-pointer hover:bg-hover'
        "
      >
        Добавить фото
        <input
          ref="fileInput"
          type="file"
          accept="image/*"
          multiple
          data-testid="upload"
          :disabled="!canUpload || saving"
          class="sr-only"
          @change="$emit('upload', $event)"
        />
      </label>
      <span class="min-w-0 flex-1"></span>
      <button
        v-if="test.status === 'draft' || test.status === 'paused'"
        type="button"
        class="ui-btn ui-btn--primary"
        :disabled="saving || !test.variants.length"
        data-testid="start"
        @click="start"
      >
        {{ armed ? 'Реклама не идёт — всё равно запустить?' : 'Запустить' }}
      </button>
      <button
        v-if="test.status === 'running'"
        type="button"
        class="ui-btn"
        :disabled="saving"
        data-testid="pause"
        @click="$emit('status', 'paused')"
      >
        Пауза
      </button>
      <button
        v-if="test.status === 'running' || test.status === 'paused'"
        type="button"
        class="ui-btn"
        :disabled="saving"
        data-testid="finish"
        @click="$emit('finish')"
      >
        Завершить
      </button>
    </div>
    <p class="mt-md text-tiny text-muted">
      «Главное» — эталон, с которым сравниваются остальные: загрузите то фото, которое сейчас стоит
      на карточке.
    </p>
  </section>
</template>
