<script setup>
/**
 * «Куда ушли деньги» — a sentence, then one bar per kind of campaign.
 *
 * The live page answers this with four cards, each with its own segmented bar
 * and zone list. The kit's rule is «фраза вместо таблицы»: the sentence says
 * which kind took the money and where it was shown, the kit's `BC.hbars` puts
 * the four kinds side by side at one scale, and the zones are summed across
 * all kinds into one line. What that gives up is each kind's own zone split:
 * the sentence still gives it for the largest kind, the others lose it.
 *
 * Bars are `--fact` (it is money that was spent); a kind that did not run keeps
 * its row, dimmed, so the rows stay in the same place from one period to the next.
 */
import { computed } from 'vue'

import { shortMoney } from '@/modules/labs/advertising/adsFormat'
import { BC } from '@/modules/labs/advertising/bold/charts'
import { ZONE_KINDS } from '@/modules/labs/advertising/zoneModel'

const props = defineProps({
  /** `bidCards(...).cards`. */
  cards: { type: Array, required: true },
  /** `bidCards(...).untyped` — spend no card can hold. */
  untyped: { type: Number, default: 0 },
  currency: { type: String, default: '' },
  showBonus: { type: Boolean, default: false },
})

const money = (value) => shortMoney(value, props.currency)
/** Shares in running text are whole percents — the kit's `BC.pct`. */
const pct = (ratio) => BC.pct(ratio)
const total = computed(() => props.cards.reduce((sum, card) => sum + card.spend, 0))

const lead = computed(() => {
  const top = [...props.cards].sort((a, b) => b.spend - a.spend)[0]
  if (!top?.spend) return 'Ни один вид кампаний не крутился в этом периоде.'
  const zone = [...top.zones].sort((a, b) => b.spend - a.spend)[0]
  const where =
    top.zones.filter((z) => z.spend > 0).length > 1
      ? `, в основном ${zone.label.toLowerCase()} (${pct(zone.share)})`
      : ''
  return `Больше всего ушло на «${top.label}» — ${pct(top.share)} всей рекламы${where}.`
})

const bars = computed(() =>
  BC.hbars(
    props.cards.map((card) => ({
      label: `${card.label} · ${card.tag}`,
      v: card.spend,
      color: 'var(--fact)',
      dim: !card.spend,
    })),
    { valueFmt: money, max: Math.max(1, ...props.cards.map((card) => card.spend)) },
  ),
)

/** Each zone summed across every kind of campaign, as a share of all of it. */
const zones = computed(() =>
  ZONE_KINDS.map(({ kind, label }) => {
    const spend = props.cards
      .flatMap((card) => card.zones)
      .filter((zone) => zone.kind === kind)
      .reduce((sum, zone) => sum + zone.spend, 0)
    return { kind, label, share: total.value ? spend / total.value : null }
  }).filter((zone) => zone.share),
)

const bonus = computed(() => props.cards.reduce((sum, card) => sum + card.bonus, 0))
</script>

<template>
  <section class="band">
    <div class="app-container stack">
      <h2 class="t-display">Куда ушли деньги</h2>
      <p class="lead">{{ lead }}</p>
      <div v-html="bars" />
      <p v-if="zones.length" class="note">
        Где показывали:
        <template v-for="(zone, i) in zones" :key="zone.kind">
          {{ i ? ' · ' : '' }}{{ zone.label }} {{ pct(zone.share) }}
        </template>
      </p>
      <p v-if="showBonus && bonus" class="note">
        Из этих денег {{ money(bonus) }} ({{ pct(total ? bonus / total : null) }}) оплатил WB
        промо-бонусами.
      </p>
      <p v-if="untyped" class="note">
        Ещё {{ money(untyped) }} не разнесено по видам: WB не отдал настройки этих кампаний.
      </p>
    </div>
  </section>
</template>
