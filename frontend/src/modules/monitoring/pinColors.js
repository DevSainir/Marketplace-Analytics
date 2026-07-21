/**
 * The palette offered by the pinned-row paint tool.
 *
 * Soft macaron tints from the Open Color system (open-color.github.io) shade-2:
 * a cohesive pastel family that keeps `text-primary` readable on top, so a
 * painted chip reads as a highlighted chip rather than as a coloured button
 * competing with the action accent. Unlike a bare pale wash, each has enough
 * chroma to tell the pins apart at a glance without turning garish. They are
 * plain hex values (not Tailwind tokens) because the colour is DATA — it
 * round-trips through the API and is applied as an inline background.
 */
export const PIN_COLORS = [
  { value: '#ffc9c9', label: 'Красный' },
  { value: '#ffd8a8', label: 'Оранжевый' },
  { value: '#ffec99', label: 'Жёлтый' },
  { value: '#d8f5a2', label: 'Лаймовый' },
  { value: '#b2f2bb', label: 'Зелёный' },
  { value: '#96f2d7', label: 'Бирюзовый' },
  { value: '#99e9f2', label: 'Голубой' },
  { value: '#a5d8ff', label: 'Синий' },
  { value: '#bac8ff', label: 'Индиго' },
  { value: '#d0bfff', label: 'Фиолетовый' },
  { value: '#eebefa', label: 'Сиреневый' },
  { value: '#fcc2d7', label: 'Розовый' },
  { value: '#e9ecef', label: 'Серый' },
]
