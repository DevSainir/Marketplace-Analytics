<script setup>
/**
 * One A/Б-тест: upload the photos, then read what each of them earned.
 *
 * Four blocks on the canvas — identity, the timeline, the totals, the results —
 * the same stack `MonitoringView` uses, so the page reads as part of the app
 * rather than as a form someone bolted on. Each is its own component.
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { MAX_VARIANTS, useAbTestsStore } from '@/modules/abTests'
import { roundsIn } from '@/modules/abTests/timeline'
import BlockFilters from '@/modules/abTests/components/BlockFilters.vue'
import FinishTestDialog from '@/modules/abTests/components/FinishTestDialog.vue'
import RotationHistory from '@/modules/abTests/components/RotationHistory.vue'
import RotationTimeline from '@/modules/abTests/components/RotationTimeline.vue'
import TestControls from '@/modules/abTests/components/TestControls.vue'
import TestPageHeader from '@/modules/abTests/components/TestPageHeader.vue'
import TestSummary from '@/modules/abTests/components/TestSummary.vue'
import TriggerEditor from '@/modules/abTests/components/TriggerEditor.vue'
import VariantResultsTable from '@/modules/abTests/components/VariantResultsTable.vue'

const route = useRoute()
const router = useRouter()
const store = useAbTestsStore()

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

/**
 * Which lap the tables show; 0 is «Все».
 *
 * A filter rather than a separate screen because the question it answers —
 * «was that photo always ahead, or only in one lap» — is asked while looking at
 * the totals, and having to navigate away to check breaks the comparison.
 */
const round = ref(0)

/**
 * Which campaign the comparison is read through; 0 is «Все».
 *
 * «История действий» below deliberately ignores it: the log is the record of
 * what the rotation did, and the rotation did it once whoever was paying for
 * the traffic. Splitting it would produce two rows per install that differ only
 * in their counts.
 */
const campaign = ref(0)

const campaigns = computed(() => test.value?.campaigns ?? [])

const roundOptions = computed(() => roundsIn(test.value?.history, campaign.value))

// A campaign that ran for four of the test's ten laps offers four; if the lap
// on screen is not one of them, the filter falls back to «Все» rather than
// showing an empty table.
watch(roundOptions, (available) => {
  if (round.value && !available.includes(round.value)) round.value = 0
})

const editing = ref(false)

async function saveTrigger(payload) {
  const ok = await store.updateSettings(route.params.testId, payload)
  if (ok) editing.value = false
}

const finishing = ref(false)

/** Close the dialog only once the test has finished; a failure stays in it. */
async function finishTest(keepVariantId) {
  if (await store.finish(route.params.testId, keepVariantId)) finishing.value = false
}

/** The header has already confirmed it; there is nothing left on this screen. */
async function removeTest() {
  if (await store.remove(route.params.testId)) router.push({ name: 'ab-tests' })
}

async function onFiles(event) {
  const files = Array.from(event.target.files || []).slice(0, store.remainingSlots)
  for (const file of files) {
    const ok = await store.addPhoto(route.params.testId, file)
    if (!ok) break
  }
  event.target.value = ''
}

/**
 * Upload the baseline. Single-file, unlike `onFiles`: a test has exactly one
 * «Главное», and a second would come back as a conflict nobody asked for.
 *
 * @param {Event} event The file input's change event.
 * @returns {Promise<void>}
 */
async function onMainFile(event) {
  const [file] = Array.from(event.target.files || [])
  if (file) await store.addPhoto(route.params.testId, file, { main: true })
  event.target.value = ''
}
</script>

<template>
  <main class="app-container py-xl phone:py-lg">
    <TestPageHeader
      :test="test"
      :saving="store.saving"
      @delete="removeTest"
      @edit-trigger="editing = true"
    >
      <TriggerEditor
        v-if="editing"
        :test="test"
        :saving="store.saving"
        @save="saveTrigger"
        @cancel="editing = false"
      />
    </TestPageHeader>

    <p v-if="store.error" class="mb-md text-base text-status-negative">{{ store.error }}</p>

    <RotationTimeline v-if="test && test.started_at" :test="test" :image-urls="store.imageUrls" />

    <!-- Only once something has been installed: before that every figure in it
         is a zero, and four zeros read as a broken panel rather than as an
         empty one. -->
    <TestSummary v-if="test && test.started_at" :test="test" :image-urls="store.imageUrls" />

    <TestControls
      v-if="test"
      :test="test"
      :can-upload="store.canUpload"
      :has-main-photo="store.hasMainPhoto"
      :uploaded-count="store.uploadedCount"
      :saving="store.saving"
      @upload="onFiles"
      @upload-main="onMainFile"
      @status="store.changeStatus(test.id, $event)"
      @finish="finishing = true"
    />

    <FinishTestDialog
      v-if="test"
      :open="finishing"
      :test="test"
      :image-urls="store.imageUrls"
      :saving="store.saving"
      :error="store.error"
      @close="finishing = false"
      @confirm="finishTest"
    />

    <template v-if="test && test.variants.length">
      <BlockFilters
        v-model:campaign="campaign"
        v-model:round="round"
        title="Тестирование"
        title-class="text-h3 font-semibold text-primary"
        :campaigns="campaigns"
        :rounds="roundOptions"
        campaign-testid="results-campaign"
      />

      <VariantResultsTable
        :test="test"
        :image-urls="store.imageUrls"
        :saving="store.saving"
        :round="round"
        :campaign="campaign"
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
      набора показов, и здесь появится их сравнение. Начните с «Главного»: это то фото, которое
      сейчас стоит на карточке, и именно с ним сравниваются остальные.
    </p>
  </main>
</template>
