<script setup>
/**
 * Excel round-trip for cost prices — the bulk alternative to typing each SKU.
 *
 * Presentational only: it emits `export` (download the grid) and `import` (a
 * chosen File), and renders the backend's import summary. The view owns the
 * store calls and the actual file download, the same split CostPriceGrid uses
 * for save/remove.
 *
 * The file input is wrapped in a <label> and hidden, and its value is reset
 * after each pick so choosing the *same* file twice still fires `change` — a
 * seller who re-uploads a corrected sheet under the same name must not be met
 * with silence.
 */
defineProps({
  /** @type {boolean} A download or upload is in flight. */
  busy: { type: Boolean, default: false },
  /** @type {object|null} The last import summary: {applied, skipped, issues}. */
  result: { type: Object, default: null },
  currency: { type: String, default: 'KGS' },
})

const emit = defineEmits(['export', 'import'])

function onFile(event) {
  const file = event.target.files?.[0]
  if (file) emit('import', file)
  // Reset so re-picking the same file re-triggers change.
  event.target.value = ''
}
</script>

<template>
  <section class="mb-lg rounded-card border border-border-subtle bg-surface p-lg shadow-card">
    <div class="text-tiny font-medium uppercase tracking-wide text-muted">Excel: массовый ввод</div>
    <p class="mt-xs max-w-2xl text-base text-muted">
      Скачайте P&amp;L по артикулам, заполните столбец «Себестоимость за 1 ед.» (в
      {{ currency }}) и загрузите файл обратно. Читается только себестоимость и сопоставляется по
      «Артикул WB»; пустые ячейки ничего не меняют. Форматы: .xlsx, .xls, .csv.
    </p>

    <div class="mt-md flex flex-wrap items-center gap-md">
      <button
        type="button"
        class="rounded-btn border border-border-subtle px-lg py-sm text-base font-semibold text-primary transition hover:border-action disabled:cursor-not-allowed disabled:opacity-50"
        :disabled="busy"
        @click="emit('export')"
      >
        Скачать Excel
      </button>

      <label
        class="cursor-pointer rounded-btn bg-action px-lg py-sm text-base font-semibold text-white transition hover:bg-action-hover"
        :class="busy ? 'cursor-not-allowed opacity-50' : ''"
      >
        {{ busy ? 'Загрузка…' : 'Загрузить Excel' }}
        <input
          type="file"
          accept=".xlsx,.xls,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel,text/csv"
          class="hidden"
          :disabled="busy"
          @change="onFile"
        />
      </label>
    </div>

    <div
      v-if="result"
      class="mt-md rounded-card border border-border-subtle bg-canvas p-md text-base"
    >
      <p class="text-primary">
        Загружено себестоимостей: <b>{{ result.applied }}</b
        >. Пропущено строк: {{ result.skipped }}.
      </p>
      <div v-if="result.issues?.length" class="mt-sm">
        <p class="text-tiny font-medium uppercase tracking-wide text-status-warning">
          Не применены ({{ result.issues.length }}):
        </p>
        <ul class="mt-xs max-h-40 overflow-y-auto text-tiny text-muted">
          <li v-for="(issue, i) in result.issues" :key="i" class="tabular-nums">
            строка {{ issue.row }}<span v-if="issue.nm_id"> · nm_id {{ issue.nm_id }}</span> —
            {{ issue.reason }}
          </li>
        </ul>
      </div>
    </div>
  </section>
</template>
