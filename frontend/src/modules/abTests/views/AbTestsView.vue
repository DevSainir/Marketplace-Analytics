<script setup>
/**
 * A/Б-тесты — the list of photo-rotation tests.
 *
 * The page is a stack of blocks in the app's own idiom (see the `design-system`
 * skill and `MonitoringView` as its worked example): a plain heading on the
 * canvas, a glass toolbar carrying the one control that filters the page, and
 * white cards for everything with content in it. The form and the table are
 * their own components — the composition here is what this file is.
 */
import { onMounted, ref, useTemplateRef } from 'vue'
import { useRouter } from 'vue-router'

import BusyRegion from '@/core/components/BusyRegion.vue'
import DataState from '@/core/components/DataState.vue'

import { useAbTestsStore } from '@/modules/abTests'
import AbTestsTable from '@/modules/abTests/components/AbTestsTable.vue'
import NewTestForm from '@/modules/abTests/components/NewTestForm.vue'

const store = useAbTestsStore()
const router = useRouter()

const creating = ref(false)
const form = useTemplateRef('form')

function openForm() {
  creating.value = !creating.value
  if (creating.value) store.loadSkuOptions('')
}

/** The list has been asked for once — before that, «no tests» would be a guess. */
const listed = ref(false)
/** That first ask failed: an empty table under it would read as «no tests». */
const listFailed = ref(false)

onMounted(async () => {
  listFailed.value = !(await store.loadTests())
  listed.value = true
})

async function submit(payload) {
  const created = await store.create(payload)
  if (!created) return
  creating.value = false
  form.value?.reset()
  router.push({ name: 'ab-test-detail', params: { testId: created.id } })
}
</script>

<template>
  <main class="app-container py-xl phone:py-lg">
    <header class="mb-md flex flex-wrap items-center justify-between gap-md">
      <h1 class="text-h2 font-bold text-primary">A/Б-тесты</h1>
      <button type="button" class="ui-btn ui-btn--primary" data-testid="new-test" @click="openForm">
        {{ creating ? 'Свернуть' : '+ Новый тест' }}
      </button>
    </header>

    <p class="mb-lg max-w-3xl text-tiny text-muted">
      Фото меняется автоматически — либо когда вариант наберёт свои <b>рекламные показы</b>, либо
      через заданное <b>время</b>.<br />
      А/Б-тесты работают только со включённой рекламой.
    </p>

    <NewTestForm
      v-if="creating"
      ref="form"
      :options="store.skuOptions"
      :saving="store.saving"
      @search="store.loadSkuOptions"
      @submit="submit"
      @cancel="creating = false"
    />

    <div class="ui-bar ui-glass flex flex-wrap items-center gap-sm">
      <label class="relative min-w-0 flex-1">
        <span class="sr-only">Поиск по тестам</span>
        <input
          :value="store.query"
          data-testid="search"
          class="h-10 w-full rounded-input bg-surface px-md text-base text-primary shadow-soft placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-action/20"
          placeholder="Название теста, артикул продавца или WB"
          @input="store.search($event.target.value)"
        />
      </label>
      <span class="flex-none pr-xs text-micro tabular-nums text-muted">
        Тестов: {{ store.rows.length }}
      </span>
    </div>

    <DataState v-if="!listed" kind="loading" />
    <DataState v-else-if="listFailed && !store.rows.length" kind="error" :text="store.error" />
    <template v-else>
      <DataState v-if="store.error" kind="error" layout="line" :text="store.error" class="mb-md" />
      <BusyRegion :busy="store.loading">
        <AbTestsTable
          :rows="store.rows"
          :loading="store.loading"
          :saving="store.saving"
          @delete="store.remove"
        />
      </BusyRegion>
    </template>
  </main>
</template>
