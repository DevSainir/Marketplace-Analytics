<script setup>
/**
 * Первая (закреплённая) ячейка отчёта: треугольник размеров, фото и артикул.
 *
 * Треугольник живёт именно здесь, а не в отдельной колонке: таблица уезжает
 * вбок на двадцать денежных колонок, и раскрывающий элемент в своей колонке
 * уехал бы от строки, которую открывает. По той же причине здесь же фото —
 * картинка, отъехавшая от артикула, перестаёт быть опознавательным знаком.
 */
import SkuThumb from '@/core/components/SkuThumb.vue'

defineProps({
  /** @type {object} Плоская строка таблицы. */
  row: { type: Object, required: true },
  open: { type: Boolean, default: false },
})

defineEmits(['toggle'])
</script>

<template>
  <span class="flex items-center gap-sm">
    <button
      v-if="!row.isBucket"
      type="button"
      class="pnl-expander"
      :aria-expanded="open"
      :title="open ? 'Свернуть размеры' : 'Показать размеры'"
      @click="$emit('toggle')"
    >
      <span class="inline-block transition" :class="open && 'rotate-90'">▶</span>
    </button>
    <!-- Строка счёта не раскрывается: у неё нет ни артикула, ни размеров. -->
    <span v-else class="w-4"></span>

    <SkuThumb v-if="!row.isBucket" :src="row.photoUrl" :label="row.saName" size="sm" />
    <span :class="row.isBucket ? 'text-muted' : 'font-medium text-primary'">{{ row.saName }}</span>
  </span>
</template>
