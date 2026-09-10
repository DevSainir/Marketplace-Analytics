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
import RotationHistory from '@/modules/abTests/components/RotationHistory.vue'
import RotationProgress from '@/modules/abTests/components/RotationProgress.vue'
import TestControls from '@/modules/abTests/components/TestControls.vue'
import TestSummary from '@/modules/abTests/components/TestSummary.vue'
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

/**
 * Which lap the tables show; 0 is «Все».
 *
 * A filter rather than a separate screen because the question it answers —
 * «was that photo always ahead, or only in one lap» — is asked while looking at
 * the totals, and having to navigate away to check breaks the comparison.
 */
const round = ref(0)

const roundOptions = computed(() => {
  const total = test.value?.rounds_completed ?? 0
  return Array.from({ length: total }, (_, index) => total - index)
})

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

    <!-- Only once something has been installed: before that every figure in it
         is a zero, and four zeros read as a broken panel rather than as an
         empty one. -->
    <TestSummary v-if="test && test.started_at" :test="test" />

    <TestControls
      v-if="test"
      :test="test"
      :can-upload="store.canUpload"
      :uploaded-count="store.uploadedCount"
      :saving="store.saving"
      @upload="onFiles"
      @status="store.changeStatus(test.id, $event)"
    />

    <template v-if="test && test.variants.length">
      <div class="mb-md flex flex-wrap items-center justify-between gap-md">
        <h2 class="text-h3 font-semibold text-primary">Тестирование</h2>
        <label class="flex items-center gap-sm text-tiny text-muted">
          <span>Круг</span>
          <select v-model.number="round" class="ui-select" data-testid="round-filter">
            <option :value="0">Все</option>
            <option v-for="option in roundOptions" :key="option" :value="option">
              {{ option }}
            </option>
          </select>
        </label>
      </div>

      <VariantResultsTable
        :test="test"
        :image-urls="store.imageUrls"
        :saving="store.saving"
        :round="round"
        @exclude="(id, excluded) => store.toggleExclusion(test.id, id, excluded)"
      />

      <!-- Deliberately a lot of air: the grid is what the page is for and
           the log is a separate question about it, so the gap has to read
           as «different section» rather than «next row». -->
      <div class="mt-[4rem] phone:mt-[2.5rem]">
        <RotationHistory :test="test" :image-urls="store.imageUrls" :round="round" />
      </div>
    </template>

    <p v-else-if="test" class="rounded-card bg-surface p-lg text-base text-muted shadow-card">
      Загрузите до {{ MAX_VARIANTS }} вариантов главного фото — они будут сменять друг друга по мере
      набора показов, и здесь появится их сравнение. Фото самой карточки в ротации не оказалось: WB
      не отдал его при создании теста — оно добавится при запуске, если ответит.
    </p>
  </main>
</template>
