<script setup>
/**
 * The matrix header's fourth row, «ID РК»: under each campaign group, the id of
 * the campaign that ran in it that day, linked to that campaign in WB's
 * advertising cabinet. «Общая»/«Органика» have no campaign — their header
 * cells span down through this row from the type row above.
 *
 * Renders a bare `<tr>` for MetricsTable's `<thead>`, so the ids share the
 * table's columns and scroll with their day.
 */
import { TRAFFIC_GROUPS } from '@/modules/labs/metricsMatrix'
import { campaignUrl } from '@/modules/labs/wbLinks'

const props = defineProps({
  /** @type {Array<{iso: string}>} oldest → newest */
  days: { type: Array, required: true },
  /** Campaign ids per ISO day, keyed by TRAFFIC_GROUPS `key`. */
  campaignIds: { type: Object, default: () => ({}) },
  /** The page's SKU — the campaign page opens on it. */
  nmId: { type: Number, default: null },
})

/** Every TRAFFIC_GROUPS entry that has zones of its own is a campaign group. */
const CAMPAIGN_GROUPS = TRAFFIC_GROUPS.filter((group) => !group.spansZones)

/** The campaign page, preset to the table's window and this SKU. */
function advertLink(advertId) {
  return campaignUrl(advertId, {
    nmId: props.nmId,
    from: props.days[0]?.iso,
    to: props.days.at(-1)?.iso,
  })
}
</script>

<template>
  <tr>
    <th>ID РК</th>
    <template v-for="day in days" :key="day.iso">
      <th v-for="group in CAMPAIGN_GROUPS" :key="`${day.iso}:${group.key}`" :colspan="group.span">
        <a
          v-if="campaignIds[day.iso]?.[group.key]"
          class="matrix-advert-link"
          :href="advertLink(campaignIds[day.iso][group.key])"
          target="_blank"
          rel="noopener noreferrer"
          :title="`Открыть кампанию ${campaignIds[day.iso][group.key]} в кабинете WB`"
        >
          {{ campaignIds[day.iso][group.key] }}
        </a>
      </th>
    </template>
  </tr>
</template>

<style scoped>
/* Same treatment as the zones row above it (main.css): tight padding, the
   group row's tracking. */
.app-datatable--matrix thead tr:nth-child(4) th:not(:first-child) {
  padding-left: 4px;
  padding-right: 4px;
  letter-spacing: 0.02em;
}

/* Seams, on this row's own stride — four campaign cells per day. A black day
   divider before each day's first cell (the very first one is drawn by the
   frozen column), a light one between campaign groups. */
.app-datatable--matrix thead tr:nth-child(4) th:nth-child(4n + 2):not(:nth-child(2)) {
  border-left: 2px solid var(--ui-daydivider);
}
.app-datatable--matrix thead tr:nth-child(4) th:nth-child(4n + 3),
.app-datatable--matrix thead tr:nth-child(4) th:nth-child(4n + 4),
.app-datatable--matrix thead tr:nth-child(4) th:nth-child(4n + 5) {
  border-left: 2px solid var(--ui-rule);
}

.matrix-advert-link {
  color: var(--ui-action);
  font-variant-numeric: tabular-nums;
  text-underline-offset: 2px;
  transition: color 0.15s;
}
.matrix-advert-link:hover {
  color: var(--ui-action-hover);
  text-decoration: underline;
}
.matrix-advert-link:active {
  opacity: 0.7;
}
</style>
