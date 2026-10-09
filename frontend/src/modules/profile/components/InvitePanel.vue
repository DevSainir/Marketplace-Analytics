<script setup>
/**
 * Inviting a manager — the drawer's contents.
 *
 * The grant travels WITH the invitation rather than being applied after the
 * person joins: between joining and being narrowed there would be a window
 * with real access in it, and nobody watching.
 *
 * The token is shown exactly once (the server stores only its hash), so the
 * link stays on screen until the drawer is closed.
 */
import { computed, ref } from 'vue'

import AccessGrantFields from '@/modules/profile/components/AccessGrantFields.vue'
import { GRANT_MODULES } from '@/modules/profile/components/grantModules'

defineProps({ saving: { type: [String, null], default: null } })
const emit = defineEmits(['invite'])

const email = ref('')
// An hour by default. The link is reusable until it expires, so the window is
// what bounds it — a week-long one that got out is a week-long open door.
const validForHours = ref(1)
const grant = ref({ accessLevel: 'read_write', modules: GRANT_MODULES.map((m) => m.key) })
const issued = ref(null)
const copied = ref(false)

const inviteLink = computed(() =>
  issued.value
    ? `${window.location.origin}/invite?token=${encodeURIComponent(issued.value.token)}`
    : '',
)

async function copyLink() {
  try {
    await navigator.clipboard.writeText(inviteLink.value)
    copied.value = true
  } catch {
    // Clipboard access is refused in some browsers and over plain HTTP. The
    // link is on screen and selectable either way.
  }
}

function submit() {
  emit('invite', {
    email: email.value.trim() || null,
    validForHours: validForHours.value,
    accessLevel: grant.value.accessLevel,
    modules: grant.value.modules,
    onIssued: (invitation) => {
      issued.value = invitation
      email.value = ''
    },
  })
}

defineExpose({ submit })
</script>

<template>
  <div class="flex flex-col gap-lg">
    <div class="grid grid-cols-2 gap-md phone:grid-cols-1">
      <label class="flex flex-col gap-xs">
        <span class="pf-field__label">Email (необязательно)</span>
        <input
          v-model="email"
          type="email"
          class="ui-input w-full"
          placeholder="Пусто — просто ссылка"
        />
      </label>
      <label class="flex flex-col gap-xs">
        <span class="pf-field__label">Ссылка действует, часов</span>
        <input
          v-model.number="validForHours"
          type="number"
          min="1"
          max="720"
          class="ui-input w-full"
        />
      </label>
    </div>

    <AccessGrantFields
      :access-level="grant.accessLevel"
      :modules="grant.modules"
      :disabled="saving === 'invite'"
      @update="(next) => (grant = next)"
    />

    <div v-if="issued" class="pf-issued">
      <p class="pf-field__label">
        Ссылка показывается один раз. Пока она действует, по ней может присоединиться любой, у кого
        она есть.
      </p>
      <code class="pf-issued__code">{{ inviteLink }}</code>
      <!-- Green, not violet: the drawer's primary action sits right below it in
           the footer, and two action-coloured buttons in a row make neither of
           them the thing to press. This one reports a success rather than
           asking for a decision, which is what the positive tone is for. -->
      <button type="button" class="ui-btn ui-btn--good" @click="copyLink">
        {{ copied ? 'Скопировано' : 'Скопировать ссылку' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.pf-field__label {
  @apply text-tiny font-semibold uppercase tracking-wide;
  color: var(--ui-faint);
}

.pf-issued {
  @apply flex flex-col items-start gap-sm rounded-card px-md py-md;
  background: var(--ui-action-soft);
}

.pf-issued__code {
  @apply block w-full break-all text-tiny font-medium text-primary;
}
</style>
