<script setup>
/**
 * The WB-token editor, in a drawer.
 *
 * What the list row cannot hold: the primary workspace takes a token per WB API
 * category — thirteen password fields — and the old page kept them in an
 * accordion INSIDE a list item, which is why the list could not also say which
 * workspace was actually wired up. The row reports "12 of 13"; this holds the
 * form.
 */
import SidePanel from '@/modules/profile/components/SidePanel.vue'
import TokensPanel from '@/modules/profile/components/TokensPanel.vue'

defineProps({
  /** The workspace being edited, or null when the drawer is shut. */
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
    title="Wildberries tokens"
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
      <button type="submit" form="pf-tokens-form" class="ui-btn ui-btn--primary" :disabled="busy">
        {{ busy ? 'Saving…' : 'Save tokens' }}
      </button>
    </template>
  </SidePanel>
</template>
