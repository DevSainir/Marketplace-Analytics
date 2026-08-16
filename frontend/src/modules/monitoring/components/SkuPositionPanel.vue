<script setup>
import { computed, ref } from 'vue'

import PinnedKeywordCards from '@/modules/monitoring/components/PinnedKeywordCards.vue'
import SearchPositionResult from '@/modules/monitoring/components/SearchPositionResult.vue'

/**
 * «Позиции в поиске» — where this SKU stands in WB's live organic search.
 *
 * Split from the advertising-cluster table it used to share a block with. They
 * answer different questions from different sources — this one a sample taken
 * seconds ago from a personalized, regional result page; that one a window of
 * paid impressions — and reading them as one section is what made an empty
 * cluster table look like a broken position check.
 *
 * Two ways to ask, in one row:
 *
 * - type a phrase and submit (the icon inside the field) for a one-off check;
 * - «Закрепить» to keep the phrase, after which the scheduled task re-checks it
 *   three times a day and the card carries the last number and its timestamp.
 *
 * «Проверить все позиции» is pushed to the row's far RIGHT, away from the two
 * controls that act on the typed phrase: it acts on everything already pinned,
 * across the whole workspace, and beside the input it read as a second submit.
 *
 * Dumb: props in, `check`/`recheck`/`pin`/`unpin`/`refresh-all` out.
 *
 * Three probe states stay distinct, because collapsing them tells a seller the
 * opposite of the truth: an error means WB did not answer and NOTHING was
 * checked; a null position means the SKU was not inside the scanned depth (which
 * is printed, since a deeper rank is still possible); a number is a real rank.
 */
const props = defineProps({
  /** Backend `SkuSearchPositionResponse`, or null before the first check. */
  position: { type: Object, default: null },
  positionLoading: { type: Boolean, default: false },
  positionError: { type: String, default: '' },
  /** Backend `PinnedKeywordItem[]` — the standing phrases and their last ranks. */
  pins: { type: Array, default: () => [] },
  pinsError: { type: String, default: '' },
  /** True once the pins request finished, so the empty state never flashes. */
  pinsLoaded: { type: Boolean, default: false },
  /** A «Проверить все позиции» run is queued or in flight. */
  refreshingAll: { type: Boolean, default: false },
  refreshMessage: { type: String, default: '' },
})

const emit = defineEmits(['check', 'recheck', 'pin', 'unpin', 'refresh-all'])

const term = ref('')

/** The phrase the spinner names. «Проверить снова» re-probes the phrase already
 *  on screen with the input empty, so the typed value alone would leave the
 *  message saying nothing about what is being checked. */
const probingTerm = computed(() => term.value.trim() || props.position?.query || '')

/** Submit guard: Enter in the input bypasses the disabled button, and an empty
 *  phrase has no ranking to ask WB for. */
function submit() {
  if (term.value.trim()) emit('check', term.value)
}

/** Pin what is typed, then clear the field — the phrase now lives on a card, and
 *  leaving it in the input invites pinning it twice. */
function pin() {
  if (!term.value.trim()) return
  emit('pin', term.value)
  term.value = ''
}
</script>

<template>
  <section class="mt-lg" aria-label="Позиции в поиске">
    <h2 class="text-h3 font-semibold text-primary">Позиции в поиске</h2>
    <p class="mt-xs max-w-3xl text-tiny font-medium text-muted">
      Живая выдача WB: введите запрос, чтобы узнать позицию артикула прямо сейчас, или закрепите
      фразу — её позиция будет обновляться три раза в день.
    </p>
    <!-- Without this the panel gets read as broken: a seller sees their own
         advertised card at первое место on wildberries.ru and «не найден в
         первых 300» here, for the same phrase, the same minute. Both are true —
         the storefront grid interleaves paid placements, this number is the
         organic list alone — and the gap between them is the point of the
         panel, not a defect in it. -->
    <p class="mt-xs max-w-3xl text-tiny font-medium text-muted">
      Считается только органическая выдача, без рекламы. На сайте WB рекламные карточки
      подмешиваются в сетку выше органики, поэтому артикул может стоять там первым и при этом не
      входить в органические 300.
    </p>

    <div class="mt-md flex flex-wrap items-center gap-sm">
      <form class="relative w-full max-w-sm" @submit.prevent="submit">
        <label class="sr-only" for="wb-search-term">Запрос в поиске WB</label>
        <!-- pr-xl (32px) is exactly the icon button's 28px plus its right-xs
             offset: any less and a long phrase slides under the icon. The
             spacing scale stops at xl, so there is no larger token to reach for
             and an arbitrary value would break the design-system rule. -->
        <input
          id="wb-search-term"
          v-model="term"
          type="search"
          maxlength="100"
          placeholder="носки мужские"
          class="w-full rounded-btn border border-border-subtle bg-surface py-sm pl-md pr-xl text-base text-primary outline-none transition focus:border-action"
        />
        <!-- The submit lives inside the field as the search icon: the row
             carries three actions, and a third full-width button made it read
             like a form with two submits. Hover paints the whole control rather
             than the glyph — a colour shift on a 20px outline icon is nearly
             invisible on a field this size. -->
        <button
          type="submit"
          class="absolute right-xs top-1/2 -translate-y-1/2 rounded-btn p-xs text-muted transition hover:bg-action hover:text-white focus-visible:bg-action focus-visible:text-white disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-muted"
          :disabled="positionLoading || !term.trim()"
          :aria-label="positionLoading ? 'Проверяем позицию' : 'Проверить позицию'"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            class="h-5 w-5"
            :class="positionLoading && 'animate-pulse'"
            aria-hidden="true"
          >
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
        </button>
      </form>

      <button
        type="button"
        class="rounded-btn bg-action px-md py-sm text-base font-semibold text-white transition hover:bg-action-hover disabled:opacity-50"
        :disabled="!term.trim()"
        @click="pin"
      >
        Закрепить
      </button>

      <!-- Pushed to the container's right edge, away from the two controls that
           act on the typed phrase: this one acts on everything already pinned,
           across the whole workspace. Filled like the page's other secondary
           actions («Обновить все SKU») — an outline-only button next to two
           filled ones read as a label rather than a control. -->
      <button
        type="button"
        class="ml-auto inline-flex h-9 items-center justify-center rounded-btn bg-surface px-lg text-base font-medium text-primary shadow-soft transition hover:bg-hover disabled:cursor-not-allowed disabled:opacity-60"
        :disabled="refreshingAll"
        @click="emit('refresh-all')"
      >
        {{ refreshingAll ? 'Проверяем…' : 'Проверить все позиции' }}
      </button>
    </div>

    <p v-if="refreshMessage" class="mt-sm text-tiny font-medium text-muted">{{ refreshMessage }}</p>
    <p v-if="pinsError" class="mt-sm text-base text-status-negative">{{ pinsError }}</p>

    <PinnedKeywordCards
      v-if="pins.length"
      :pins="pins"
      :busy="refreshingAll"
      @unpin="emit('unpin', $event)"
    />
    <!-- Without this the section is silent for a SKU with no pins, and
         «Проверить все позиции» (which is workspace-wide) looks like it did
         nothing when it refreshed some other SKU's phrases. -->
    <p v-else-if="pinsLoaded" class="mt-md text-tiny font-medium text-muted">
      У этого артикула нет закреплённых запросов. Введите фразу и нажмите «Закрепить», чтобы её
      позиция обновлялась три раза в день.
    </p>

    <!-- A cold probe reads up to three ranked pages one after another, and a
         throttled first page waits out WB's window before its single retry — so
         this legitimately runs for tens of seconds. A greyed-out button is not
         feedback: it reads as "nothing happened". -->
    <p
      v-if="positionLoading"
      class="mt-md flex items-center gap-sm text-base text-muted"
      role="status"
      aria-live="polite"
    >
      <span
        class="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-border-subtle border-t-action"
        aria-hidden="true"
      />
      <span v-if="probingTerm">
        Проверяем позицию по «{{ probingTerm }}». WB отвечает медленно — до минуты.
      </span>
      <span v-else>Проверяем позицию. WB отвечает медленно — до минуты.</span>
    </p>

    <p v-else-if="positionError" class="mt-md text-base text-status-negative">
      {{ positionError }}
    </p>

    <SearchPositionResult
      v-else-if="position"
      :position="position"
      :busy="positionLoading"
      @recheck="emit('recheck', $event)"
    />
  </section>
</template>
