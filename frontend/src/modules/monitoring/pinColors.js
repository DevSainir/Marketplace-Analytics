/**
 * The palette offered by the pinned-row paint tool.
 *
 * Tints only: every swatch is a pale wash that keeps `text-primary` readable
 * on top of it, so a painted chip reads as a highlighted chip rather than as a
 * coloured button competing with the action accent. They are plain hex values
 * (not Tailwind tokens) because the colour is DATA — it round-trips through the
 * API and is applied as an inline background.
 */
export const PIN_COLORS = [
  { value: '#fee2e2', label: 'Красный' },
  { value: '#ffedd5', label: 'Оранжевый' },
  { value: '#fef3c7', label: 'Янтарный' },
  { value: '#fef9c3', label: 'Жёлтый' },
  { value: '#ecfccb', label: 'Лаймовый' },
  { value: '#dcfce7', label: 'Зелёный' },
  { value: '#ccfbf1', label: 'Бирюзовый' },
  { value: '#cffafe', label: 'Голубой' },
  { value: '#dbeafe', label: 'Синий' },
  { value: '#e0e7ff', label: 'Индиго' },
  { value: '#ede9fe', label: 'Фиолетовый' },
  { value: '#fce7f3', label: 'Розовый' },
  { value: '#f3f4f6', label: 'Серый' },
]
