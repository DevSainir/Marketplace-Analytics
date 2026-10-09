<script setup>
/**
 * «Куда ушли деньги» — one card per kind of campaign.
 *
 * Each card answers its two questions top to bottom: how much this kind of
 * campaign took (the figure, and its share of all advertising), then where it
 * was shown (a segmented bar and the zones under it, in the colours the rest
 * of the page gives them). WB's bonus sits in a footer pinned to the card's
 * foot, so across the row the footers line up whatever the zone count.
 *
 * A kind that did not run stays in its place, dimmed: the row is a map of how
 * WB bills, and a gap in it would read as a layout fault.
 *
 * A zone too small to see at its true width (unified search is ~1 % of its
 * card) gets a 3px floor, so a non-zero zone is never invisible — its exact
 * share is printed beside it anyway.
 */
import { formatMoney } from '@/core/utils/format'
import { ZONE_COLORS, ratioPct } from '@/modules/advertising/adsFormat'

const props = defineProps({
  /** `bidCards(...).cards`. */
  cards: { type: Array, required: true },
  currency: { type: String, default: '' },
  showBonus: { type: Boolean, default: false },
})

const money = (value) => formatMoney(value, props.currency)

const segmentStyle = (zone) => ({
  width: `${(zone.share ?? 0) * 100}%`,
  minWidth: zone.spend > 0 ? '3px' : '0',
  background: ZONE_COLORS[zone.kind],
})
</script>

<template>
  <div class="grid gap-sm sm:grid-cols-2 lg:grid-cols-4">
    <article
      v-for="card in cards"
      :key="card.key"
      class="flex flex-col rounded-card border border-border-subtle bg-surface p-md shadow-card transition"
      :class="{ 'opacity-60': !card.spend }"
    >
      <header class="flex items-center justify-between gap-sm">
        <h3 class="text-base font-semibold text-primary">{{ card.label }}</h3>
        <span class="ui-badge">
          {{ card.tag }}
        </span>
      </header>

      <div class="mt-sm text-h2 font-bold tabular-nums text-primary">{{ money(card.spend) }}</div>
      <div class="text-tiny text-muted">
        <template v-if="card.spend">{{ ratioPct(card.share) }} всей рекламы</template>
        <template v-else>не крутилась в этом периоде</template>
      </div>

      <div
        class="mt-md flex h-2 gap-0.5 overflow-hidden rounded-full bg-canvas"
        role="img"
        :aria-label="
          card.zones.map((z) => `${z.label} ${ratioPct(z.share)}`).join(', ') || 'нет расхода'
        "
      >
        <span
          v-for="zone in card.zones.filter((z) => z.spend > 0)"
          :key="zone.kind"
          class="block h-full first:rounded-l-full last:rounded-r-full"
          :style="segmentStyle(zone)"
          :title="`${zone.label}: ${money(zone.spend)} · ${ratioPct(zone.share)}`"
        />
      </div>

      <ul class="mb-md mt-sm space-y-xs text-tiny tabular-nums">
        <li v-for="zone in card.zones" :key="zone.kind" class="flex items-center gap-sm">
          <span
            class="h-2 w-2 flex-none rounded-full"
            :style="{ background: ZONE_COLORS[zone.kind] }"
            aria-hidden="true"
          />
          <span class="flex-1" :class="zone.spend ? 'text-primary' : 'text-muted'">
            {{ zone.label }}
          </span>
          <span :class="zone.spend ? 'text-primary' : 'text-muted'">{{ money(zone.spend) }}</span>
          <span class="w-12 text-right text-muted">
            {{ zone.spend ? ratioPct(zone.share) : '' }}
          </span>
        </li>
      </ul>

      <!-- The same three columns as the zone rows above — label, money, share —
           so the bonus reads as one more line of the card's own arithmetic:
           part of the spend over it, not an extra figure beside it. -->
      <footer
        v-if="showBonus"
        class="mt-auto flex items-center gap-sm border-t border-border-subtle pt-sm text-tiny tabular-nums"
      >
        <span class="flex-1 text-muted">Бонусы WB</span>
        <span :class="card.bonus ? 'text-primary' : 'text-muted'">
          {{ money(card.bonus) }}
        </span>
        <span class="w-12 text-right text-muted">
          {{ card.bonus && card.spend ? ratioPct(card.bonus / card.spend) : '' }}
        </span>
      </footer>
    </article>
  </div>
</template>
