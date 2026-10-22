import { detailRows, eventLabel } from '@/modules/profile/components/auditEntry'

/**
 * How one audit row is read back to a person.
 *
 * The trail is a machine record first — an incident is read with grep, at
 * 02:00, by us — so the events are stored in English and translated here. Two
 * rules are worth pinning because both were got wrong in the first version:
 *
 *  * the labels name the ACTION, not the column. «Кто» is not wrong, it is
 *    empty: every entry has somebody, and the useful half is what they did;
 *  * an event with only one party gets one line. «Кто присоединился: X»
 *    followed by «Кого касается: X» is the same name under two questions.
 */
function entry(overrides = {}) {
  return {
    id: 'a-1',
    occurred_at: '2026-09-14T13:25:00Z',
    event: 'MEMBER_ACCESS_CHANGED',
    actor_email: 'owner@example.com',
    actor_user_id: 'u-0',
    target_type: 'membership',
    target_id: 'u-1',
    ip_address: null,
    metadata: null,
    ...overrides,
  }
}

const labelled = (rows, label) => rows.find((row) => row.label === label)?.value

describe('eventLabel', () => {
  it('translates a known event', () => {
    expect(eventLabel('MEMBER_REMOVED')).toBe('Менеджер удалён из компании')
  })

  it('shows an unknown event rather than hiding it', () => {
    // An unfamiliar entry is the one most worth seeing.
    expect(eventLabel('SOMETHING_NEW')).toBe('SOMETHING_NEW')
  })
})

describe('detailRows — who the two people are', () => {
  it('names the action rather than the column', () => {
    const rows = detailRows(entry({ metadata: { email: 'manager@example.com' } }))

    expect(labelled(rows, 'Кто изменил')).toBe('owner@example.com')
    expect(labelled(rows, 'Кому изменили')).toBe('manager@example.com')
  })

  it('uses the right verb per event', () => {
    const invited = detailRows(
      entry({ event: 'MEMBER_INVITED', target_type: 'invitation', metadata: { email: 'a@b.c' } }),
    )
    const revoked = detailRows(
      entry({ event: 'INVITATION_REVOKED', target_type: 'invitation', metadata: {} }),
    )

    expect(labelled(invited, 'Кто пригласил')).toBe('owner@example.com')
    expect(labelled(invited, 'Кого пригласили')).toBe('a@b.c')
    expect(labelled(revoked, 'Кто отозвал')).toBe('owner@example.com')
    // A bare link has no address, and saying «—» would read as missing data.
    expect(labelled(revoked, 'Какое приглашение')).toBe('ссылка без адреса')
  })

  it('gives a one-party event a single line', () => {
    // Joining is done BY the person it happens to, so the actor and the target
    // are the same address — and printing it twice under two questions is what
    // the per-event labels exist to avoid.
    const rows = detailRows(
      entry({ event: 'MEMBER_JOINED', actor_email: 'a@b.c', metadata: { email: 'a@b.c' } }),
    )

    expect(labelled(rows, 'Кто присоединился')).toBe('a@b.c')
    expect(rows.filter((row) => row.value === 'a@b.c')).toHaveLength(1)
  })

  it('calls an actorless entry «система» rather than leaving it blank', () => {
    const rows = detailRows(entry({ actor_email: null }))

    expect(labelled(rows, 'Кто изменил')).toBe('система')
  })
})

describe('detailRows — what actually changed', () => {
  it('spells the grant out in the words the form uses', () => {
    const rows = detailRows(
      entry({ metadata: { access_level: 'read_only', modules: ['finreports'] } }),
    )

    expect(labelled(rows, 'Уровень')).toBe('Только чтение')
    expect(labelled(rows, 'Разделы')).toBe('P&L')
  })

  it('names a grant of nothing instead of rendering an empty line', () => {
    const rows = detailRows(entry({ metadata: { modules: [] } }))

    expect(labelled(rows, 'Разделы')).toBe('ни одного')
  })

  it('shows the previous state only where it differs', () => {
    const unchanged = detailRows(
      entry({
        metadata: {
          access_level: 'read_only',
          modules: ['finreports'],
          previous_access_level: 'read_only',
          previous_modules: ['finreports'],
        },
      }),
    )
    const changed = detailRows(
      entry({
        metadata: {
          access_level: 'read_only',
          modules: ['finreports'],
          previous_access_level: 'read_write',
          previous_modules: ['monitoring', 'finreports'],
        },
      }),
    )

    expect(labelled(unchanged, 'Было: уровень')).toBeUndefined()
    expect(labelled(unchanged, 'Было: разделы')).toBeUndefined()
    expect(labelled(changed, 'Было: уровень')).toBe('Чтение и запись')
    expect(labelled(changed, 'Было: разделы')).toBe('Мониторинг, P&L')
  })

  it('reports an invitation’s window in hours or days, as fits', () => {
    const short = detailRows(entry({ event: 'MEMBER_INVITED', metadata: { valid_for_hours: 6 } }))
    const long = detailRows(entry({ event: 'MEMBER_INVITED', metadata: { valid_for_hours: 72 } }))

    expect(labelled(short, 'Ссылка действовала')).toBe('6 ч')
    expect(labelled(long, 'Ссылка действовала')).toBe('3 дн')
  })
})

describe('detailRows — a subscription change', () => {
  it('shows the new end of the term and the old one', () => {
    const rows = detailRows(
      entry({
        event: 'SUBSCRIPTION_CHANGED',
        actor_email: 'dev@example.com',
        metadata: {
          operation: 'update',
          source: 'tool',
          previous_expires_at: '2026-10-05T06:27:28+00:00',
          expires_at: '2026-10-19T06:27:28+00:00',
        },
      }),
    )

    expect(labelled(rows, 'Кто изменил')).toBe('dev@example.com')
    expect(labelled(rows, 'Действует до')).toBe('19 October 2026')
    expect(labelled(rows, 'Было: до')).toBe('5 October 2026')
  })

  it('says a change made straight in SQL was made by hand, not by the system', () => {
    // The trigger writes these with no actor; a person was still behind it.
    const rows = detailRows(
      entry({
        event: 'SUBSCRIPTION_CHANGED',
        actor_email: null,
        metadata: {
          source: 'sql',
          previous_expires_at: '2026-09-21T06:27:28+00:00',
          expires_at: '2026-10-05T06:27:28+00:00',
        },
      }),
    )

    expect(labelled(rows, 'Кто изменил')).toBe('вручную в базе')
  })
})
