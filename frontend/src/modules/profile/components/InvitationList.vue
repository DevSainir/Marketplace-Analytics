<script setup>
/**
 * "Invitations" — the links that are out there but not yet used.
 *
 * The missing half of the team page. Issuing an invitation showed its link
 * once and then forgot it existed, so a link handed to the wrong person, or
 * simply never used, was untrackable and unrevokable from the product — and an
 * invitation is a door standing open until it expires.
 *
 * `status` is resolved server-side against the server's clock, so two people
 * looking at the same link read the same state. Acceptance is deliberately NOT
 * a status: a link stays usable until it expires, so "someone joined" says
 * nothing about whether it still works — which is why the count of joiners is
 * its own column and "Revoke" stays available on a link somebody has used.
 */
import { computed } from 'vue'

import DataState from '@/core/components/DataState.vue'
import { confirmLabel, useConfirmClick } from '@/core/utils/confirmClick'
import { formatMoscowDate } from '@/core/utils/moscow'

const props = defineProps({
  /** @type {Array<object>} rows from GET /v1/organizations/invitations */
  invitations: { type: Array, default: () => [] },
  /** The list is still being read — until then "none" would be a guess. */
  loading: { type: Boolean, default: false },
  /** invitation id being revoked, or null. */
  busy: { type: [String, null], default: null },
})

const emit = defineEmits(['revoke'])

/** A revoked link cannot be re-issued as the same link: asked first (`confirmClick`). */
const revocation = useConfirmClick()

const STATUS = {
  pending: { label: 'active', tone: 'is-ok' },
  expired: { label: 'expired', tone: 'is-quiet' },
}

/**
 * Revoked links are dropped entirely.
 *
 * The API keeps them — the audit trail needs them, and "who revoked this
 * link" is answered on the log below. But this table is for deciding what to
 * do about a link that is still out there, and a revoked one has nothing left
 * to decide: it cannot be un-revoked, and it is not a door standing open.
 * Listing it only makes the reader scan past it.
 */
const visible = computed(() => props.invitations.filter((invite) => invite.status !== 'revoked'))

/** "3 h" while it is alive; the date once it is not. */
function expiry(invitation) {
  const ms = new Date(invitation.expires_at).getTime() - Date.now()
  if (invitation.status !== 'pending' || ms <= 0) {
    return formatMoscowDate(invitation.expires_at)
  }
  const hours = Math.round(ms / 3600000)
  if (hours < 1) return `${Math.max(1, Math.round(ms / 60000))} min`
  if (hours < 48) return `${hours} h`
  return `${Math.round(hours / 24)} days`
}
</script>

<template>
  <div class="pf-panel">
    <header class="pf-panel__head">
      <div class="min-w-0">
        <h2 class="pf-panel__title">Invitations</h2>
        <p class="pf-panel__note">While a link is valid, anyone who has it can join.</p>
      </div>
    </header>

    <DataState v-if="loading && !visible.length" kind="loading" />
    <DataState v-else-if="!visible.length" kind="empty" text="No active invitations" />

    <div v-else class="pf-grid" role="table">
      <div class="pf-grid__head" role="row">
        <span role="columnheader">To</span>
        <span role="columnheader">Status</span>
        <span role="columnheader">Joined</span>
        <span role="columnheader">Left</span>
        <span role="columnheader" class="sr-only">Actions</span>
      </div>

      <div v-for="invite in visible" :key="invite.id" class="pf-grid__row" role="row">
        <span class="pf-cell pf-cell--who" role="cell">
          <span class="pf-who__mail">{{ invite.email || 'Link without an address' }}</span>
          <span class="pf-who__meta"> issued {{ formatMoscowDate(invite.created_at) }} </span>
        </span>

        <span class="pf-cell" role="cell">
          <span class="ui-badge" :class="STATUS[invite.status]?.tone">
            {{ STATUS[invite.status]?.label ?? invite.status }}
          </span>
        </span>

        <span class="pf-cell pf-who__meta" role="cell">{{ invite.accepted_count }}</span>

        <span class="pf-cell pf-who__meta" role="cell">{{ expiry(invite) }}</span>

        <span class="pf-cell pf-cell--act" role="cell">
          <button
            v-if="invite.status === 'pending'"
            type="button"
            class="ui-btn ui-btn--danger ui-btn--sm"
            :class="revocation.isArmed(invite.id) ? 'is-armed' : ''"
            :disabled="busy === invite.id"
            @click="revocation.press(invite.id, () => emit('revoke', invite.id))"
          >
            {{
              busy === invite.id
                ? 'Revoking…'
                : revocation.isArmed(invite.id)
                  ? confirmLabel('Revoke')
                  : 'Revoke'
            }}
          </button>
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pf-grid__head,
.pf-grid__row {
  grid-template-columns: minmax(12rem, 2fr) 8rem 5rem 6rem 7rem;
}

@media (max-width: 1023px) {
  .pf-grid__head {
    @apply hidden;
  }

  .pf-grid__row {
    @apply grid-cols-1 gap-sm;
  }

  .pf-cell--act {
    @apply justify-start;
  }
}
</style>
