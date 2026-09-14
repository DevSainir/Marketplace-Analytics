<script setup>
/**
 * The three editors, all of them drawers.
 *
 * They live together because they are the same thing from the page's point of
 * view — a row was clicked, and the form for that row slid in. Keeping them in
 * one component also keeps the view under the size limit, which is what forced
 * the grouping and turned out to be the right shape anyway.
 *
 * The draft grant is owned here, not by the view: it is scratch state that
 * exists only while a drawer is open, and it is seeded from the row every time
 * one opens so a cancelled edit leaves nothing behind.
 */
import { ref, watch } from 'vue'

import AccessGrantFields from '@/modules/labs/components/profile/AccessGrantFields.vue'
import InvitePanel from '@/modules/labs/components/profile/InvitePanel.vue'
import SidePanel from '@/modules/labs/components/profile/SidePanel.vue'
import TokensPanel from '@/modules/labs/components/profile/TokensPanel.vue'

const props = defineProps({
  /** `{ kind: 'invite' | 'access' | 'tokens', manager?, workspace? }` or null. */
  drawer: { type: Object, default: null },
  /** membersStore.saving — a user_id, 'invite', or null. */
  memberSaving: { type: [String, null], default: null },
  storeBusy: { type: Boolean, default: false },
  tokenStatuses: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['close', 'invite', 'save-access', 'save-tokens'])

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
      title="Пригласить менеджера"
      subtitle="Доступ выдаётся сразу — менеджер входит уже с этими правами"
      @close="emit('close')"
    >
      <InvitePanel ref="invitePanel" :saving="memberSaving" @invite="emit('invite', $event)" />
      <template #footer>
        <button
          type="button"
          class="lp-btn lp-btn--primary"
          :disabled="memberSaving === 'invite'"
          @click="invitePanel?.submit()"
        >
          {{ memberSaving === 'invite' ? 'Создаём…' : 'Создать приглашение' }}
        </button>
      </template>
    </SidePanel>

    <SidePanel
      :open="drawer?.kind === 'access'"
      title="Доступ менеджера"
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
          class="lp-btn lp-btn--primary"
          :disabled="memberSaving === drawer?.manager?.user_id"
          @click="emit('save-access', draftGrant)"
        >
          {{ memberSaving === drawer?.manager?.user_id ? 'Сохраняем…' : 'Сохранить' }}
        </button>
      </template>
    </SidePanel>

    <SidePanel
      :open="drawer?.kind === 'tokens'"
      title="Токены Wildberries"
      :subtitle="drawer?.workspace?.name ?? ''"
      @close="emit('close')"
    >
      <TokensPanel
        v-if="drawer?.kind === 'tokens'"
        :is-primary="Boolean(drawer.workspace.is_primary)"
        :configured="tokenStatuses[drawer.workspace.id]?.configured ?? []"
        :saving="storeBusy"
        @save="emit('save-tokens', $event)"
      />
      <template #footer>
        <button
          type="submit"
          form="lp-tokens-form"
          class="lp-btn lp-btn--primary"
          :disabled="storeBusy"
        >
          {{ storeBusy ? 'Сохранение…' : 'Сохранить токены' }}
        </button>
      </template>
    </SidePanel>
  </div>
</template>
