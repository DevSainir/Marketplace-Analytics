<script setup>
/**
 * Under the grid: how many rows a page holds, and which page is on screen.
 *
 * Thirty by default, as in the reference — enough to see a кабинет's leaders
 * and the start of its tail on one screen. Paging is answered from rows the
 * page already holds, so it never waits on the network.
 */
defineProps({
  page: { type: Number, required: true },
  pages: { type: Number, required: true },
  pageSize: { type: Number, required: true },
  total: { type: Number, required: true },
})
const emit = defineEmits(['update:page', 'update:pageSize'])

const SIZES = [30, 50, 100]
</script>

<template>
  <div class="mt-md flex flex-wrap items-center gap-sm">
    <select
      class="ui-select ui-select--sm phone:w-full"
      :value="pageSize"
      aria-label="Строк на странице"
      @change="emit('update:pageSize', Number($event.target.value))"
    >
      <option v-for="size in SIZES" :key="size" :value="size">{{ size }}</option>
    </select>
    <span class="text-tiny text-muted">строк · всего {{ total }}</span>

    <div v-if="pages > 1" class="ml-auto flex items-center gap-xs">
      <button
        type="button"
        class="hm-trigger hm-trigger--icon"
        :disabled="page <= 1"
        aria-label="Предыдущая страница"
        @click="emit('update:page', page - 1)"
      >
        ‹
      </button>
      <span class="px-sm text-base tabular-nums text-primary">{{ page }} из {{ pages }}</span>
      <button
        type="button"
        class="hm-trigger hm-trigger--icon"
        :disabled="page >= pages"
        aria-label="Следующая страница"
        @click="emit('update:page', page + 1)"
      >
        ›
      </button>
    </div>
  </div>
</template>
