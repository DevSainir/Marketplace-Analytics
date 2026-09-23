<script setup>
/**
 * Отметка «Не включать в общий счёт» — последняя колонка отчёта по артикулам.
 *
 * Подпись у колонки пустая (заголовок съел бы ширину, которой в таблице нет),
 * поэтому смысл галочки объясняет подсказка при наведении. Она открывается
 * ВЛЕВО: колонка крайняя правая, и всплывающая вправо подсказка вылезает за
 * край области прокрутки.
 */
defineProps({
  checked: { type: Boolean, default: false },
})

defineEmits(['change'])
</script>

<template>
  <label class="group relative flex items-center justify-center" title="Не включать в общий счёт">
    <input
      type="checkbox"
      :checked="checked"
      aria-label="Не включать в общий счёт"
      class="h-4 w-4 cursor-pointer rounded border-border-subtle text-action focus:ring-action/20"
      @change="$emit('change', $event.target.checked)"
    />
    <span
      class="pointer-events-none absolute right-full top-1/2 z-20 mr-sm hidden -translate-y-1/2 whitespace-nowrap rounded-input border border-border-subtle bg-surface px-sm py-xs text-tiny text-primary shadow-card group-hover:block"
    >
      Не включать в общий счёт
    </span>
  </label>
</template>
