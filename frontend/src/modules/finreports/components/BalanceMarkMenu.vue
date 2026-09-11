<script setup>
/**
 * The balance grid's two floating overlays: the ⋮ mark menu and the full-name
 * tooltip.
 *
 * Both are teleported to `body` with fixed coordinates — inside the grid's
 * scroll container they would be clipped by it. Split out of BalanceTable.vue
 * to keep it under the size limit; it owns no state, the composable does.
 *
 * Both axes offer the same mark: «Не считать» sends a row or column to the back
 * and out of every total while leaving it on screen — the seller still wants to
 * see stock they have stopped counting.
 */
defineProps({
  /** `{kind, value, label, uncounted, x, y}` or `null`. */
  menu: { type: Object, default: null },
  /** `{name, x, y}` or `null` — the shortened warehouse name, in full. */
  tip: { type: Object, default: null },
})

const emit = defineEmits(['toggle-uncounted'])
</script>

<template>
  <Teleport to="body">
    <div
      v-if="tip"
      class="fixed z-50 rounded-card border border-border-subtle bg-surface px-sm py-xs text-tiny text-primary shadow-card"
      :style="{ left: `${tip.x}px`, top: `${tip.y}px` }"
    >
      {{ tip.name }}
    </div>
  </Teleport>

  <Teleport to="body">
    <div
      v-if="menu"
      class="mark-menu fixed z-50 rounded-card border border-border-subtle bg-surface p-sm shadow-card"
      :style="{ left: `${menu.x}px`, top: `${menu.y}px` }"
    >
      <label class="flex cursor-pointer select-none items-center gap-sm text-base text-primary">
        <input
          type="checkbox"
          class="mark-menu-checkbox"
          :checked="false"
          @change="emit('toggle-uncounted')"
        />
        {{ menu.uncounted ? 'Считать' : 'Не считать' }}
      </label>
    </div>
  </Teleport>
</template>
