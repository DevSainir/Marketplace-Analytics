<script setup>
/**
 * One A/Б-тест: upload the photos, then read what each of them earned.
 *
 * Three blocks on the canvas — identity, the rotation panel, the results — the
 * same stack `MonitoringView` uses, so the page reads as part of the app rather
 * than as a form someone bolted on. The result table is its own component; see
 * it for why photos are rows.
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import { MAX_VARIANTS, STATUS_LABELS, useAbTestsStore } from '@/modules/abTests'
import RotationProgress from '@/modules/abTests/components/RotationProgress.vue'
import TriggerEditor from '@/modules/abTests/components/TriggerEditor.vue'
import VariantResultsTable from '@/modules/abTests/components/VariantResultsTable.vue'

const route = useRoute()
const router = useRouter()
const store = useAbTestsStore()
const fileInput = ref(null)

const test = computed(() => store.detail)

onMounted(() => store.loadTest(route.params.testId))
watch(
  () => route.params.testId,
  (id) => id && store.loadTest(id),
)

// The photos are authenticated, so they cannot be pointed at from `<img src>`
// — the store fetches them and hands back object URLs. Re-run whenever the set
// of variants changes (an upload replaces the whole detail), and release the
// URLs on the way out so their blobs are not pinned in memory.
watch(
  () => (test.value?.variants ?? []).map((variant) => variant.variant_id).join(','),
  () => test.value && store.loadImages(test.value.id),
  { immediate: true },
)
onUnmounted(() => store.releaseImages())

// A live rotation moves on a Celery pass every five minutes, and the figures
// it moves — the live variant, its impressions — only change on a re-read. A
// page left open would otherwise go stale silently, which is the exact
// impression this screen exists to stop. One quiet minute is a cheap price and
// well inside the poll interval; `refreshDetail` never touches `loading`, so
// nothing blinks under the reader.
const REFRESH_MS = 60_000
let refreshing = null

watch(
  () => test.value?.status,
  (status) => {
    clearInterval(refreshing)
    refreshing = null
    if (status !== 'running') return
    refreshing = setInterval(() => store.refreshDetail(route.params.testId), REFRESH_MS)
  },
  { immediate: true },
)
onUnmounted(() => clearInterval(refreshing))

/** How this test rotates, in words — only the setting its mode actually uses. */
const triggerLabel = computed(() => {
  if (!test.value) return ''
  return test.value.trigger_mode === 'time'
    ? `Смена фото каждые ${count(test.value.slot_minutes)} мин`
    : `Смена фото каждые ${count(test.value.impression_budget)} показов`
})

/** Whether the trigger may still be edited — a finished test's is history. */
const canEditTrigger = computed(
  () => !!test.value && !['completed', 'cancelled'].includes(test.value.status),
)

const editing = ref(false)
const armedDelete = ref(false)

async function saveTrigger(payload) {
  const ok = await store.updateSettings(route.params.testId, payload)
  if (ok) editing.value = false
}

/** Two-click confirm, then back to the list — the test is gone from under us. */
async function removeTest() {
  if (!armedDelete.value) {
    armedDelete.value = true
    return
  }
  armedDelete.value = false
  if (await store.remove(route.params.testId)) router.push({ name: 'ab-tests' })
}

function count(value) {
  return Number(value ?? 0).toLocaleString('ru-RU')
}

async function onFiles(event) {
  const files = Array.from(event.target.files || []).slice(0, store.remainingSlots)
  for (const file of files) {
    const ok = await store.addPhoto(route.params.testId, file)
    if (!ok) break
  }
  if (fileInput.value) fileInput.value.value = ''
}
</script>

<template>
  <main class="app-container py-xl phone:py-lg">
    <header class="mb-lg">
      <RouterLink
        :to="{ name: 'ab-tests' }"
        class="text-tiny font-medium text-action hover:underline"
      >
        ← Ко всем A/Б-тестам
      </RouterLink>

      <div v-if="test" class="mt-sm flex flex-wrap items-center gap-x-md gap-y-xs">
        <h1 class="text-h2 font-bold text-primary">{{ test.name }}</h1>
        <span class="text-tiny font-semibold text-action">WB {{ test.nm_id }}</span>
        <span v-if="test.vendor_code" class="text-tiny text-muted">{{ test.vendor_code }}</span>
        <button
          type="button"
          class="ml-auto rounded-btn px-sm py-xs text-micro font-semibold transition"
          :class="
            armedDelete
              ? 'bg-status-negative/10 text-status-negative'
              : 'text-muted hover:bg-hover hover:text-status-negative'
          "
          :disabled="store.saving"
          data-testid="delete-test"
          @click="removeTest"
        >
          {{ armedDelete ? 'Точно удалить тест?' : 'Удалить тест' }}
        </button>
      </div>

      <p v-if="test" class="mt-xs flex flex-wrap items-center gap-x-sm text-tiny text-muted">
        <span>{{ STATUS_LABELS[test.status] || test.status }}</span>
        <span>·</span>
        <span>{{ triggerLabel }}</span>
        <button
          v-if="canEditTrigger"
          type="button"
          class="rounded-btn px-xs py-px text-micro font-semibold text-action transition hover:bg-action/10"
          data-testid="edit-trigger"
          @click="editing = true"
        >
          изменить
        </button>
      </p>

      <TriggerEditor
        v-if="editing"
        :test="test"
        :saving="store.saving"
        @save="saveTrigger"
        @cancel="editing = false"
      />
    </header>

    <p v-if="store.error" class="mb-md text-base text-status-negative">{{ store.error }}</p>

    <RotationProgress v-if="test" :test="test" :image-urls="store.imageUrls" />

    <section v-if="test" class="mb-lg rounded-card bg-surface p-lg shadow-card phone:p-md">
      <div class="flex flex-wrap items-center gap-md">
        <span class="text-base font-semibold text-primary">
          Фото в ротации: {{ test.variants.length }} · загружено {{ store.uploadedCount }} из
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
            !store.canUpload || store.saving
              ? 'cursor-not-allowed opacity-50'
              : 'cursor-pointer hover:bg-hover'
          "
        >
          Добавить фото
          <input
            ref="fileInput"
            type="file"
            accept="image/*"
            multiple
            data-testid="upload"
            :disabled="!store.canUpload || store.saving"
            class="sr-only"
            @change="onFiles"
          />
        </label>
        <span class="min-w-0 flex-1"></span>
        <button
          v-if="test.status === 'draft' || test.status === 'paused'"
          type="button"
          class="inline-flex h-10 items-center justify-center rounded-btn bg-action px-lg text-base font-semibold text-white shadow-soft transition hover:bg-action-hover disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="store.saving || !test.variants.length"
          data-testid="start"
          @click="store.changeStatus(test.id, 'running')"
        >
          Запустить
        </button>
        <button
          v-if="test.status === 'running'"
          type="button"
          class="inline-flex h-10 items-center justify-center rounded-btn bg-surface px-lg text-base font-medium text-primary shadow-soft transition hover:bg-hover disabled:opacity-50"
          :disabled="store.saving"
          data-testid="pause"
          @click="store.changeStatus(test.id, 'paused')"
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

    <VariantResultsTable
      v-if="test && test.variants.length"
      :test="test"
      :image-urls="store.imageUrls"
      :saving="store.saving"
      @remove="store.removePhoto(test.id, $event)"
    />

    <p v-else-if="test" class="rounded-card bg-surface p-lg text-base text-muted shadow-card">
      Загрузите до {{ MAX_VARIANTS }} вариантов главного фото — они будут сменять друг друга по мере
      набора показов, и здесь появится их сравнение. Фото самой карточки в ротации не оказалось: WB
      не отдал его при создании теста — оно добавится при запуске, если ответит.
    </p>
  </main>
</template>
