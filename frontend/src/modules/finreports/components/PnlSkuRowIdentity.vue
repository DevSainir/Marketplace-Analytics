<script setup>
/**
 * Первая (закреплённая) ячейка отчёта: треугольник размеров, фото и артикул.
 *
 * Треугольник живёт именно здесь, а не в отдельной колонке: таблица уезжает
 * вбок на двадцать денежных колонок, и раскрывающий элемент в своей колонке
 * уехал бы от строки, которую открывает. По той же причине здесь же фото —
 * картинка, отъехавшая от артикула, перестаёт быть опознавательным знаком.
 *
 * The «no cost» mark sits here for the same reason: the «Себестоимость»
 * column is fourteen columns to the right, off screen on most laptops, and a
 * mark nobody scrolls to marks nothing.
 */
import SkuThumb from '@/core/components/SkuThumb.vue'

defineProps({
  /** @type {object} Плоская строка таблицы. */
  row: { type: Object, required: true },
  open: { type: Boolean, default: false },
  /** The mark is a button that asks for the cost, not just a label. */
  canEnterCost: { type: Boolean, default: false },
})

defineEmits(['toggle', 'cost'])
</script>

<template>
  <span class="flex items-center gap-sm">
    <button
      v-if="row.isSku"
      type="button"
      class="pnl-expander"
      :aria-expanded="open"
      :title="open ? 'Свернуть размеры' : 'Показать размеры'"
      @click="$emit('toggle')"
    >
      <span class="inline-block transition" :class="open && 'rotate-90'">▶</span>
    </button>
    <!-- Строка счёта и строка-сумма (предмет, бренд, группа) не раскрываются:
         у них нет ни артикула, ни размеров. -->
    <span v-else class="w-4"></span>

    <SkuThumb v-if="row.isSku" :src="row.photoUrl" :label="row.saName" size="sm" />
    <span :class="row.isBucket ? 'text-muted' : 'font-medium text-primary'">{{ row.saName }}</span>
    <span v-if="row.isGroup" class="text-muted">· {{ row.n }}</span>
    <template v-if="row.uncosted">
      <button
        v-if="canEnterCost"
        type="button"
        class="ui-badge is-warn transition hover:bg-status-warning/20"
        data-testid="enter-cost"
        @click.stop="$emit('cost')"
      >
        + себестоимость
      </button>
      <span v-else class="ui-badge is-warn">нет себестоимости</span>
    </template>
  </span>
</template>
