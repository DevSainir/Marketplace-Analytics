<script setup>
/**
 * The balance grid's two floating overlays: the ⋮ mark menu and the full-name
 * tooltip.
 *
 * Both are teleported to `body` with fixed coordinates — inside the grid's
 * scroll container they would be clipped by it. Split out of BalanceTable.vue
 * to keep it under the size limit; it owns no state, the composable does.
 *
 * A warehouse column offers both marks: «Закрепить» moves it to the front,
 * «Не считать» sends it to the back and out of every total. A SKU row offers
 * only the pin — a row cannot be «not counted»; that is what the search and the
 * filters are for.
 */
defineProps({
  /** `{kind, value, label, pinned, uncounted, x, y}` or `null`. */
  menu: { type: Object, default: null },
  /** `{name, x, y}` or `null` — the shortened warehouse name, in full. */
  tip: { type: Object, default: null },
})

const emit = defineEmits(['toggle-pin', 'toggle-uncounted'])
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
      class="pin-menu fixed z-50 flex flex-col gap-xs rounded-card border border-border-subtle bg-surface p-sm shadow-card"
      :style="{ left: `${menu.x}px`, top: `${menu.y}px` }"
    >
      <label class="flex cursor-pointer select-none items-center gap-sm text-base text-primary">
        <input
          type="checkbox"
          class="pin-menu-checkbox"
          :checked="false"
          @change="emit('toggle-pin')"
        />
        {{ menu.pinned ? 'Открепить' : 'Закрепить' }}
      </label>
      <label
        v-if="menu.kind === 'warehouse'"
        class="flex cursor-pointer select-none items-center gap-sm text-base text-primary"
      >
        <input
          type="checkbox"
          class="pin-menu-checkbox"
          :checked="false"
          @change="emit('toggle-uncounted')"
        />
        {{ menu.uncounted ? 'Считать' : 'Не считать' }}
      </label>
    </div>
  </Teleport>
</template>
