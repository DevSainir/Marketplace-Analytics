<script setup>
/**
 * «Приглашения» — the links that are out there but not yet used.
 *
 * The missing half of the team page. Issuing an invitation showed its link
 * once and then forgot it existed, so a link handed to the wrong person, or
 * simply never used, was untrackable and unrevokable from the product — and an
 * invitation is a door standing open until it expires.
 *
 * `status` is resolved server-side against the server's clock, so two people
 * looking at the same link read the same state. Acceptance is deliberately NOT
 * a status: a link stays usable until it expires, so «кто-то вошёл» says
 * nothing about whether it still works — which is why the count of joiners is
 * its own column and «Отозвать» stays available on a link somebody has used.
 */
import { computed } from 'vue'

const props = defineProps({
  /** @type {Array<object>} rows from GET /v1/organizations/invitations */
  invitations: { type: Array, default: () => [] },
  /** invitation id being revoked, or null. */
  busy: { type: [String, null], default: null },
})

const emit = defineEmits(['revoke'])

const STATUS = {
  pending: { label: 'действует', tone: 'is-ok' },
  expired: { label: 'истекло', tone: 'is-quiet' },
}

/**
 * Revoked links are dropped entirely.
 *
 * The API keeps them — the audit trail needs them, and «кто отозвал эту
 * ссылку» is answered on the log below. But this table is for deciding what to
 * do about a link that is still out there, and a revoked one has nothing left
 * to decide: it cannot be un-revoked, and it is not a door standing open.
 * Listing it only makes the reader scan past it.
 */
const visible = computed(() => props.invitations.filter((invite) => invite.status !== 'revoked'))

/** «через 3 ч» while it is alive; the date once it is not. */
function expiry(invitation) {
  const ms = new Date(invitation.expires_at).getTime() - Date.now()
  if (invitation.status !== 'pending' || ms <= 0) {
    return new Date(invitation.expires_at).toLocaleDateString('ru-RU')
  }
  const hours = Math.round(ms / 3600000)
  if (hours < 1) return `${Math.max(1, Math.round(ms / 60000))} мин`
  if (hours < 48) return `${hours} ч`
  return `${Math.round(hours / 24)} дн`
}
</script>

<template>
  <div class="lp-panel">
    <header class="lp-panel__head">
      <div class="min-w-0">
        <h2 class="lp-panel__title">Приглашения</h2>
        <p class="lp-panel__note">
          Пока ссылка действует, войти по ней может любой, у кого она есть.
        </p>
      </div>
    </header>

    <p v-if="!visible.length" class="lp-empty">Действующих приглашений нет.</p>

    <div v-else class="lp-grid" role="table">
      <div class="lp-grid__head" role="row">
        <span role="columnheader">Кому</span>
        <span role="columnheader">Состояние</span>
        <span role="columnheader">Вошли</span>
        <span role="columnheader">Осталось</span>
        <span role="columnheader" class="sr-only">Действия</span>
      </div>

      <div v-for="invite in visible" :key="invite.id" class="lp-grid__row" role="row">
        <span class="lp-cell lp-cell--who" role="cell">
          <span class="lp-who__mail">{{ invite.email || 'Ссылка без адреса' }}</span>
          <span class="lp-who__meta">
            выдано {{ new Date(invite.created_at).toLocaleDateString('ru-RU') }}
          </span>
        </span>

        <span class="lp-cell" role="cell">
          <span class="lp-pill" :class="STATUS[invite.status]?.tone">
            {{ STATUS[invite.status]?.label ?? invite.status }}
          </span>
        </span>

        <span class="lp-cell lp-who__meta" role="cell">{{ invite.accepted_count }}</span>

        <span class="lp-cell lp-who__meta" role="cell">{{ expiry(invite) }}</span>

        <span class="lp-cell lp-cell--act" role="cell">
          <button
            v-if="invite.status === 'pending'"
            type="button"
            class="lp-btn lp-btn--danger"
            :disabled="busy === invite.id"
            @click="emit('revoke', invite.id)"
          >
            {{ busy === invite.id ? 'Отзываем…' : 'Отозвать' }}
          </button>
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.lp-grid__head,
.lp-grid__row {
  grid-template-columns: minmax(12rem, 2fr) 8rem 5rem 6rem 7rem;
}

@media (max-width: 1023px) {
  .lp-grid__head {
    @apply hidden;
  }

  .lp-grid__row {
    @apply grid-cols-1 gap-sm;
  }

  .lp-cell--act {
    @apply justify-start;
  }
}
</style>
