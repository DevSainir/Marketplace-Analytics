<script setup>
/**
 * The two team editors, both of them drawers.
 *
 * They live together because they are the same thing from the page's point of
 * view — a row was clicked, and the form for that row slid in — and because
 * they share the draft grant.
 *
 * That draft is owned here, not by the view: it is scratch state that exists
 * only while a drawer is open, and it is seeded from the row every time one
 * opens, so a cancelled edit leaves nothing behind.
 */
import { ref, watch } from 'vue'

import AccessGrantFields from '@/modules/profile/components/AccessGrantFields.vue'
import InvitePanel from '@/modules/profile/components/InvitePanel.vue'
import SidePanel from '@/modules/profile/components/SidePanel.vue'

const props = defineProps({
  /** `{ kind: 'invite' | 'access', manager? }` or null. */
  drawer: { type: Object, default: null },
  /** A user_id being written, 'invite', or null. */
  memberSaving: { type: [String, null], default: null },
})

const emit = defineEmits(['close', 'invite', 'save-access'])

const draftGrant = ref(null)
const invitePanel = ref(null)

watch(
  () => props.drawer,
  (next) => {
    draftGrant.value =
      next?.kind === 'access'
        ? { accessLevel: next.manager.access_level, modules: [...(next.manager.modules ?? [])] }
        : null
  },
  { immediate: true },
)
</script>

<template>
  <div>
    <SidePanel
      :open="drawer?.kind === 'invite'"
      title="Invite a manager"
      subtitle="Access is granted at once — the manager signs in with these rights"
      @close="emit('close')"
    >
      <InvitePanel ref="invitePanel" :saving="memberSaving" @invite="emit('invite', $event)" />
      <template #footer>
        <button
          type="button"
          class="ui-btn ui-btn--primary"
          :disabled="memberSaving === 'invite'"
          @click="invitePanel?.submit()"
        >
          {{ memberSaving === 'invite' ? 'Creating…' : 'Create invitation' }}
        </button>
      </template>
    </SidePanel>

    <SidePanel
      :open="drawer?.kind === 'access'"
      title="Manager access"
      :subtitle="drawer?.manager?.email ?? ''"
      @close="emit('close')"
    >
      <AccessGrantFields
        v-if="draftGrant"
        :access-level="draftGrant.accessLevel"
        :modules="draftGrant.modules"
        :disabled="memberSaving === drawer?.manager?.user_id"
        @update="(next) => (draftGrant = next)"
      />
      <template #footer>
        <button
          type="button"
          class="ui-btn ui-btn--primary"
          :disabled="memberSaving === drawer?.manager?.user_id"
          @click="emit('save-access', draftGrant)"
        >
          {{ memberSaving === drawer?.manager?.user_id ? 'Saving…' : 'Save' }}
        </button>
      </template>
    </SidePanel>
  </div>
</template>
