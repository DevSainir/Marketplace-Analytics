/** Campaign status display maps (WB `status_label` -> badge style / ru text). */

export const CAMPAIGN_STATUS_BADGE = {
  active: 'bg-status-positive/10 text-status-positive ring-status-positive/20',
  paused: 'bg-status-warning/10 text-status-warning ring-status-warning/20',
  completed: 'bg-canvas text-muted ring-border-subtle',
}

export const CAMPAIGN_STATUS_TEXT = {
  active: 'активна',
  paused: 'пауза',
  completed: 'завершена',
}
