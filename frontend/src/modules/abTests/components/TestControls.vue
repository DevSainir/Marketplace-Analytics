<script setup>
/**
 * The test's controls: how many photos it holds, adding one, starting and
 * pausing — and the paragraph that says what «Главное» is.
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
 * Presentational: it owns no state and performs no writes, so the view stays
 * the one place that knows about the store.
 */
import { MAX_VARIANTS } from '@/modules/abTests'

defineProps({
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
defineEmits(['upload', 'upload-main', 'status'])
</script>

<template>
  <section class="mb-lg rounded-card bg-surface p-lg shadow-card phone:p-md">
    <div class="flex flex-wrap items-center gap-md">
      <span class="text-base font-semibold text-primary">
        Фото в ротации: {{ uploadedCount }} из {{ MAX_VARIANTS }}
      </span>
      <!-- Tinted and first, because it is the one photo the whole table is
           read against: a rotation of candidates with no baseline answers
           «какое из них лучше» and not «стоит ли вообще менять». -->
      <label
        class="inline-flex h-10 items-center justify-center rounded-btn bg-action px-lg text-base font-semibold text-white shadow-soft transition"
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
        class="inline-flex h-10 items-center justify-center rounded-btn bg-action px-lg text-base font-semibold text-white shadow-soft transition hover:bg-action-hover disabled:cursor-not-allowed disabled:opacity-50"
        :disabled="saving || !test.variants.length"
        data-testid="start"
        @click="$emit('status', 'running')"
      >
        Запустить
      </button>
      <button
        v-if="test.status === 'running'"
        type="button"
        class="inline-flex h-10 items-center justify-center rounded-btn bg-surface px-lg text-base font-medium text-primary shadow-soft transition hover:bg-hover disabled:opacity-50"
        :disabled="saving"
        data-testid="pause"
        @click="$emit('status', 'paused')"
      >
        Пауза
      </button>
    </div>
    <p class="mt-md text-tiny text-muted">
      «Главное» — эталон, с которым сравниваются остальные: загрузите то фото, которое сейчас стоит
      на карточке. Мы больше не забираем его из WB — оттуда приходит пересжатая копия, и ротация
      вернула бы эту копию на карточку. Оно крутится наравне с остальными и первым выходит на
      карточку при запуске. Дальше вариант меняется, когда сработает выбранный триггер: данные по
      рекламе снимаются каждые несколько минут, разница между снимками и есть трафик интервала.
      Смена происходит сразу в том же проходе, поэтому интервал целиком принадлежит одному фото и
      ничего не выбрасывается.
    </p>
  </section>
</template>
