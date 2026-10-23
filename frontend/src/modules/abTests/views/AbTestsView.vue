<script setup>
/**
 * A/B tests — the list of photo-rotation tests.
 *
 * The page is a stack of blocks in the app's own idiom (see the `design-system`
 * skill and `MonitoringView` as its worked example): a plain heading on the
 * canvas, a glass toolbar carrying the one control that filters the page, and
 * white cards for everything with content in it. The form and the table are
 * their own components — the composition here is what this file is.
 */
import { onMounted, ref, useTemplateRef } from 'vue'
import { useRouter } from 'vue-router'

import PageHeader from '@/core/components/PageHeader.vue'
import BusyRegion from '@/core/components/BusyRegion.vue'
import DataState from '@/core/components/DataState.vue'
import SearchField from '@/core/components/SearchField.vue'

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

/** The list has been asked for once — before that, "no tests" would be a guess. */
const listed = ref(false)
/** That first ask failed: an empty table under it would read as "no tests". */
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
  <div class="app-container py-lg">
    <PageHeader title="A/B tests">
      <p class="mt-xs max-w-3xl text-base text-muted">
        The photo changes on its own — when a variant reaches its <b>ad impressions</b> or after a
        set <b>time</b>. A/B tests need advertising turned on.
      </p>
      <template #actions>
        <button
          type="button"
          class="ui-btn ui-btn--primary"
          data-testid="new-test"
          @click="openForm"
        >
          {{ creating ? 'Close' : '+ New test' }}
        </button>
      </template>
    </PageHeader>

    <NewTestForm
      v-if="creating"
      ref="form"
      :options="store.skuOptions"
      :saving="store.saving"
      @search="store.loadSkuOptions"
      @submit="submit"
      @cancel="creating = false"
    />

    <div class="mb-sm flex flex-wrap items-center gap-sm">
      <SearchField
        :model-value="store.query"
        data-testid="search"
        placeholder="Test name, vendor code or WB ID"
        aria-label="Search tests"
        class="w-72 phone:w-full"
        @update:model-value="store.search"
      />
      <span class="ml-auto text-tiny tabular-nums text-muted">
        Tests: {{ store.rows.length }}
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
  </div>
</template>
