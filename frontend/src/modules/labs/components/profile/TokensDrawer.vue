<script setup>
/**
 * The WB-token editor, in a drawer.
 *
 * What the list row cannot hold: the primary кабинет takes a token per WB API
 * category — thirteen password fields — and the old page kept them in an
 * accordion INSIDE a list item, which is why the list could not also say which
 * кабинет was actually wired up. The row reports «12 из 13»; this holds the
 * form.
 */
import SidePanel from '@/modules/labs/components/profile/SidePanel.vue'
import TokensPanel from '@/modules/labs/components/profile/TokensPanel.vue'

defineProps({
  /** The кабинет being edited, or null when the drawer is shut. */
  workspace: { type: Object, default: null },
  /** Kind slugs that currently have a stored token. */
  configured: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'save'])
</script>

<template>
  <SidePanel
    :open="Boolean(workspace)"
    title="Токены Wildberries"
    :subtitle="workspace?.name ?? ''"
    @close="emit('close')"
  >
    <TokensPanel
      v-if="workspace"
      :is-primary="Boolean(workspace.is_primary)"
      :configured="configured"
      :saving="busy"
      @save="emit('save', $event)"
    />
    <template #footer>
      <button type="submit" form="lp-tokens-form" class="lp-btn lp-btn--primary" :disabled="busy">
        {{ busy ? 'Сохранение…' : 'Сохранить токены' }}
      </button>
    </template>
  </SidePanel>
</template>
