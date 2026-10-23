/**
 * Turning one audit row into something a person can read.
 *
 * Split out of the components because two of them need it — the list shows the
 * headline, the drawer shows the detail — and because the mapping is the part
 * worth reading on its own: it is the only place that knows what each event's
 * `metadata` means.
 *
 * The event NAMES stay English in the database on purpose. The trail is a
 * machine record first — an incident is read with grep, at 02:00, by us — and a
 * screen second. An event this module does not recognise is rendered as its raw
 * name rather than hidden: an unfamiliar entry is the one most worth seeing.
 *
 * Module and level names come from `grantModules.js` rather than being repeated
 * here: a log that called a section something other than the form that granted
 * it would be worse than no log.
 */
import { levelLabel, moduleLabel } from '@/modules/profile/components/grantModules'
import { plural } from '@/core/utils/format'
import { formatMoscow } from '@/core/utils/moscow'

/** Headline per event. Anything missing falls through to the raw name. */
export const EVENT_LABELS = {
  ORG_ACTIVATED: 'Company activated',
  MEMBER_INVITED: 'Invitation issued',
  INVITATION_REVOKED: 'Invitation revoked',
  MEMBER_JOINED: 'Manager joined',
  MEMBER_REMOVED: 'Manager removed',
  MEMBER_ROLE_CHANGED: 'Role changed',
  MEMBER_ACCESS_CHANGED: 'Access changed',
  WORKSPACE_CREATED: 'Workspace created',
  WORKSPACE_DELETED: 'Workspace deleted',
  WB_TOKEN_ROTATED: 'Wildberries token updated',
  SESSIONS_REVOKED: 'Sessions ended',
  PASSWORD_CHANGED: 'Password changed',
  ACTIVATION_CODE_ISSUED: 'Activation code issued',
  WORKSPACE_GUEST_GRANTED: 'Guest access granted',
  WORKSPACE_GUEST_REVOKED: 'Guest access revoked',
  SUBSCRIPTION_CHANGED: 'Subscription changed',
}

/**
 * What to call the two people in an entry, per event.
 *
 * "Who" is not wrong, it is just empty: every entry has somebody, and the
 * useful half is what they did. `actor` names the person who acted, `target`
 * names whoever it happened to — and for the events where those are the same
 * person (joining, changing your own password) there is no target line at all,
 * because "Joined" has already said it.
 */
const ROLE_LABELS = {
  ORG_ACTIVATED: { actor: 'Activated by' },
  MEMBER_INVITED: { actor: 'Invited by', target: 'Invited' },
  INVITATION_REVOKED: { actor: 'Revoked by', target: 'Invitation' },
  MEMBER_JOINED: { actor: 'Joined' },
  MEMBER_REMOVED: { actor: 'Removed by', target: 'Removed' },
  MEMBER_ROLE_CHANGED: { actor: 'Changed by', target: 'Changed for' },
  MEMBER_ACCESS_CHANGED: { actor: 'Changed by', target: 'Changed for' },
  WORKSPACE_CREATED: { actor: 'Created by' },
  WORKSPACE_DELETED: { actor: 'Deleted by' },
  WB_TOKEN_ROTATED: { actor: 'Updated by' },
  SESSIONS_REVOKED: { actor: 'Account' },
  PASSWORD_CHANGED: { actor: 'Account' },
  ACTIVATION_CODE_ISSUED: { actor: 'Issued by' },
  WORKSPACE_GUEST_GRANTED: { actor: 'Granted by' },
  WORKSPACE_GUEST_REVOKED: { actor: 'Revoked by' },
  SUBSCRIPTION_CHANGED: { actor: 'Changed by' },
}

/** Events that take something away — the only ones worth colouring. */
export const REMOVING_EVENTS = new Set([
  'MEMBER_REMOVED',
  'INVITATION_REVOKED',
  'WORKSPACE_DELETED',
  'SESSIONS_REVOKED',
  'WORKSPACE_GUEST_REVOKED',
])

export function eventLabel(event) {
  return EVENT_LABELS[event] ?? event
}

/** "14 September 2026, 17:42 MSK" — a full stamp, for the detail view. */
export function fullMoment(iso) {
  return formatMoscow(iso, {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** "14 September 2026" — a day, for a subscription's end. */
function dayLabel(iso) {
  return formatMoscow(iso, {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })
}

/**
 * Who changed a subscription. The database writes these entries itself, so a
 * change made straight in SQL arrives with no actor and `source: 'sql'` — a
 * person did it, just not through the tool that would have named them, and
 * "system" would say the opposite.
 */
function actorLabel(entry, meta) {
  if (entry.actor_email) return entry.actor_email
  if (entry.event === 'SUBSCRIPTION_CHANGED' && meta.source === 'sql')
    return 'by hand in the database'
  return 'system'
}

/** "14 Sep, 17:42 MSK" — the compact stamp the list column carries. */
export function shortMoment(iso) {
  return formatMoscow(iso, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** "12 h" / "3 days" — an invitation's validity window, from its hours. */
export function validityLabel(hours) {
  if (!hours) return null
  if (hours < 24) return `${hours} h`
  const days = Math.round(hours / 24)
  return `${days} ${plural(days, ['day', 'days'])}`
}

/**
 * The rows the drawer shows for one entry, in reading order.
 *
 * Every value here is already the tenant's own information — their members'
 * addresses, and what those members did inside their company. The writers keep
 * the rule that no secret reaches `metadata`; this only formats what is there.
 *
 * @param {object} entry one row from GET /v1/organizations/audit-log
 * @returns {Array<{label: string, value: string}>}
 */
export function detailRows(entry) {
  const meta = entry.metadata ?? {}
  const rows = []

  const names = ROLE_LABELS[entry.event] ?? {}

  rows.push({ label: 'When', value: fullMoment(entry.occurred_at) })
  rows.push({ label: names.actor ?? 'Who', value: actorLabel(entry, meta) })

  // Who it was ABOUT. Written into the metadata at the moment it happened, so
  // it still names a person after that account is deleted — which is the point
  // of keeping it denormalised rather than joining a user id at read time.
  //
  // Skipped entirely when the event has no second party: an entry that said
  // "Joined: X" and then "About: X" would be saying the
  // same name twice under two questions.
  if (names.target) {
    rows.push({
      label: names.target,
      value: meta.email || (entry.target_type === 'invitation' ? 'link without an address' : '—'),
    })
  }

  if (meta.access_level) {
    rows.push({ label: 'Level', value: levelLabel(meta.access_level) })
  }
  if (Array.isArray(meta.modules)) {
    rows.push({
      label: 'Sections',
      value: meta.modules.length ? meta.modules.map(moduleLabel).join(', ') : 'none',
    })
  }

  // The "previous" half, and only when it differs — an unchanged line in a diff is
  // noise, and the entry is written only when something did change.
  if (meta.previous_access_level && meta.previous_access_level !== meta.access_level) {
    rows.push({ label: 'Previous level', value: levelLabel(meta.previous_access_level) })
  }
  if (
    Array.isArray(meta.previous_modules) &&
    meta.previous_modules.join() !== (meta.modules ?? []).join()
  ) {
    rows.push({
      label: 'Previous sections',
      value: meta.previous_modules.length
        ? meta.previous_modules.map(moduleLabel).join(', ')
        : 'none',
    })
  }

  const validity = validityLabel(meta.valid_for_hours)
  if (validity) rows.push({ label: 'Link valid for', value: validity })

  if (meta.note) rows.push({ label: 'Note', value: meta.note })
  if (meta.subscription_days) {
    const days = meta.subscription_days
    rows.push({ label: 'Subscription for', value: `${days} ${plural(days, ['day', 'days'])}` })
  }
  if (entry.event === 'SUBSCRIPTION_CHANGED') {
    if (meta.expires_at) rows.push({ label: 'Valid until', value: dayLabel(meta.expires_at) })
    if (meta.previous_expires_at && meta.previous_expires_at !== meta.expires_at) {
      rows.push({ label: 'Previously until', value: dayLabel(meta.previous_expires_at) })
    }
    if (meta.operation === 'delete') rows.push({ label: 'Subscription', value: 'deleted' })
  }
  if (meta.revoked !== undefined) rows.push({ label: 'Sessions ended', value: `${meta.revoked}` })
  if (meta.scope) rows.push({ label: 'Scope', value: meta.scope })

  if (entry.ip_address) rows.push({ label: 'From', value: entry.ip_address })

  return rows
}
