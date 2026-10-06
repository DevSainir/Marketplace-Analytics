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

/** Headline per event. Anything missing falls through to the raw name. */
export const EVENT_LABELS = {
  ORG_ACTIVATED: 'Компания активирована',
  MEMBER_INVITED: 'Выдано приглашение',
  INVITATION_REVOKED: 'Приглашение отозвано',
  MEMBER_JOINED: 'Менеджер присоединился',
  MEMBER_REMOVED: 'Менеджер удалён из компании',
  MEMBER_ROLE_CHANGED: 'Изменена роль',
  MEMBER_ACCESS_CHANGED: 'Изменён доступ',
  WORKSPACE_CREATED: 'Создан кабинет',
  WORKSPACE_DELETED: 'Удалён кабинет',
  WB_TOKEN_ROTATED: 'Обновлён токен Wildberries',
  SESSIONS_REVOKED: 'Завершены сеансы',
  PASSWORD_CHANGED: 'Изменён пароль',
  ACTIVATION_CODE_ISSUED: 'Выдан ключ активации',
  WORKSPACE_GUEST_GRANTED: 'Открыт гостевой доступ к кабинету',
  WORKSPACE_GUEST_REVOKED: 'Закрыт гостевой доступ к кабинету',
  SUBSCRIPTION_CHANGED: 'Изменена подписка',
}

/**
 * What to call the two people in an entry, per event.
 *
 * «Кто» is not wrong, it is just empty: every entry has somebody, and the
 * useful half is what they did. `actor` names the person who acted, `target`
 * names whoever it happened to — and for the events where those are the same
 * person (joining, changing your own password) there is no target line at all,
 * because «Кто присоединился» has already said it.
 */
const ROLE_LABELS = {
  ORG_ACTIVATED: { actor: 'Кто активировал' },
  MEMBER_INVITED: { actor: 'Кто пригласил', target: 'Кого пригласили' },
  INVITATION_REVOKED: { actor: 'Кто отозвал', target: 'Какое приглашение' },
  MEMBER_JOINED: { actor: 'Кто присоединился' },
  MEMBER_REMOVED: { actor: 'Кто удалил', target: 'Кого удалили' },
  MEMBER_ROLE_CHANGED: { actor: 'Кто изменил', target: 'Кому изменили' },
  MEMBER_ACCESS_CHANGED: { actor: 'Кто изменил', target: 'Кому изменили' },
  WORKSPACE_CREATED: { actor: 'Кто создал' },
  WORKSPACE_DELETED: { actor: 'Кто удалил' },
  WB_TOKEN_ROTATED: { actor: 'Кто обновил' },
  SESSIONS_REVOKED: { actor: 'Чьи сеансы' },
  PASSWORD_CHANGED: { actor: 'Чей пароль' },
  ACTIVATION_CODE_ISSUED: { actor: 'Кто выдал' },
  WORKSPACE_GUEST_GRANTED: { actor: 'Кто открыл' },
  WORKSPACE_GUEST_REVOKED: { actor: 'Кто закрыл' },
  SUBSCRIPTION_CHANGED: { actor: 'Кто изменил' },
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

/** «14 сентября 2026, 17:42» — a full stamp, for the detail view. */
export function fullMoment(iso) {
  return new Date(iso).toLocaleString('ru-RU', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** «14 сентября 2026» — a day, for a subscription's end. */
function dayLabel(iso) {
  return new Date(iso).toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })
}

/**
 * Who changed a subscription. The database writes these entries itself, so a
 * change made straight in SQL arrives with no actor and `source: 'sql'` — a
 * person did it, just not through the tool that would have named them, and
 * «система» would say the opposite.
 */
function actorLabel(entry, meta) {
  if (entry.actor_email) return entry.actor_email
  if (entry.event === 'SUBSCRIPTION_CHANGED' && meta.source === 'sql') return 'вручную в базе'
  return 'система'
}

/** «14.09, 17:42» — the compact stamp the list column carries. */
export function shortMoment(iso) {
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** «12 часов» / «3 дня» — an invitation's validity window, from its hours. */
export function validityLabel(hours) {
  if (!hours) return null
  if (hours < 24) return `${hours} ч`
  const days = Math.round(hours / 24)
  return `${days} дн`
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

  rows.push({ label: 'Когда', value: fullMoment(entry.occurred_at) })
  rows.push({ label: names.actor ?? 'Кто', value: actorLabel(entry, meta) })

  // Who it was ABOUT. Written into the metadata at the moment it happened, so
  // it still names a person after that account is deleted — which is the point
  // of keeping it denormalised rather than joining a user id at read time.
  //
  // Skipped entirely when the event has no second party: an entry that said
  // «Кто присоединился: X» and then «Кого касается: X» would be saying the
  // same name twice under two questions.
  if (names.target) {
    rows.push({
      label: names.target,
      value: meta.email || (entry.target_type === 'invitation' ? 'ссылка без адреса' : '—'),
    })
  }

  if (meta.access_level) {
    rows.push({ label: 'Уровень', value: levelLabel(meta.access_level) })
  }
  if (Array.isArray(meta.modules)) {
    rows.push({
      label: 'Разделы',
      value: meta.modules.length ? meta.modules.map(moduleLabel).join(', ') : 'ни одного',
    })
  }

  // The «было» half, and only when it differs — an unchanged line in a diff is
  // noise, and the entry is written only when something did change.
  if (meta.previous_access_level && meta.previous_access_level !== meta.access_level) {
    rows.push({ label: 'Было: уровень', value: levelLabel(meta.previous_access_level) })
  }
  if (
    Array.isArray(meta.previous_modules) &&
    meta.previous_modules.join() !== (meta.modules ?? []).join()
  ) {
    rows.push({
      label: 'Было: разделы',
      value: meta.previous_modules.length
        ? meta.previous_modules.map(moduleLabel).join(', ')
        : 'ни одного',
    })
  }

  const validity = validityLabel(meta.valid_for_hours)
  if (validity) rows.push({ label: 'Ссылка действовала', value: validity })

  if (meta.note) rows.push({ label: 'Заметка', value: meta.note })
  if (meta.subscription_days) {
    rows.push({ label: 'Подписка на', value: `${meta.subscription_days} дн` })
  }
  if (entry.event === 'SUBSCRIPTION_CHANGED') {
    if (meta.expires_at) rows.push({ label: 'Действует до', value: dayLabel(meta.expires_at) })
    if (meta.previous_expires_at && meta.previous_expires_at !== meta.expires_at) {
      rows.push({ label: 'Было: до', value: dayLabel(meta.previous_expires_at) })
    }
    if (meta.operation === 'delete') rows.push({ label: 'Подписка', value: 'удалена' })
  }
  if (meta.revoked !== undefined)
    rows.push({ label: 'Сеансов завершено', value: `${meta.revoked}` })
  if (meta.scope) rows.push({ label: 'Область', value: meta.scope })

  if (entry.ip_address) rows.push({ label: 'Откуда', value: entry.ip_address })

  return rows
}
