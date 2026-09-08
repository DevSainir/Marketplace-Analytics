<script setup>
/**
 * The test's controls: how many photos it holds, adding one, starting and
 * pausing — and the paragraph that says what «Главное» is.
 *
 * Its own component because the detail view was over the 250-line ceiling with
 * it inline, and because the count it shows is a rule rather than a number:
 * «Фото в ротации» counts everything the rotation deals, while the ten-photo
 * cap counts only what the seller uploaded. The card's own photo is captured,
 * not chosen, so charging it to the seller's allowance would silently cost them
 * a slot.
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
  /** How many photos the seller has uploaded, excluding the captured one. */
  uploadedCount: { type: Number, default: 0 },
  /** True while a write is in flight. */
  saving: { type: Boolean, default: false },
})
defineEmits(['upload', 'status'])
</script>

<template>
  <section class="mb-lg rounded-card bg-surface p-lg shadow-card phone:p-md">
    <div class="flex flex-wrap items-center gap-md">
      <span class="text-base font-semibold text-primary">
        Фото в ротации: {{ test.variants.length }} · загружено {{ uploadedCount }} из
        {{ MAX_VARIANTS }}
      </span>
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
      «Главное» — фото, которое стояло на карточке при создании теста. Оно крутится в ротации
      наравне с загруженными и первым выходит на карточку при запуске: менять его не нужно, оно и
      так на месте. Дальше вариант меняется, когда сработает выбранный триггер: данные по рекламе
      снимаются каждые несколько минут, разница между снимками и есть трафик интервала. Смена
      происходит сразу в том же проходе, поэтому интервал целиком принадлежит одному фото и ничего
      не выбрасывается.
    </p>
  </section>
</template>
