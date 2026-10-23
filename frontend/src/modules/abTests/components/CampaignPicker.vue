<script setup>
/**
 * "Campaign" — which campaign's measurements a block is showing.
 *
 * Sits to the left of the lap picker in both "Test progress" and "Results",
 * because the two filters compose: "the third lap of the unified bid" is a question
 * the page can now answer, and either filter alone is a different one.
 *
 * Rendered only when more than one campaign has actually brought the test
 * traffic — the parent decides that. A picker with one option is furniture.
 */
import { computed } from 'vue'

import { formatSku } from '@/core/utils/format'
import { campaignKindLabel } from '@/modules/abTests/campaignKinds'

const props = defineProps({
  /** The campaigns that brought traffic, as the detail endpoint ordered them. */
  campaigns: { type: Array, default: () => [] },
  /** The selected campaign id; 0 is "All". */
  modelValue: { type: Number, default: 0 },
  /** The tested SKU's vendor code — the same for every campaign here. */
  vendorCode: { type: String, default: '' },
  /** Which `data-testid` the select carries. */
  testid: { type: String, default: 'campaign-filter' },
})
defineEmits(['update:modelValue'])

/**
 * "M-TRX01-BLK / 12345678 / Unified" — the SKU, the campaign's id in WB, and
 * what kind of campaign it is.
 *
 * Not the campaign's own name: sellers often name a campaign after the
 * card's WB ID, so the name read as a SKU rather than a campaign. The id is what the seller finds in the WB seller portal.
 */
const options = computed(() =>
  props.campaigns.map((campaign) => ({
    id: campaign.campaign_id,
    label: [formatSku(props.vendorCode), campaign.campaign_id, campaignKindLabel(campaign)]
      .filter(Boolean)
      .join(' / '),
  })),
)
</script>

<template>
  <label class="flex items-center gap-sm text-tiny text-muted">
    <span>Campaign</span>
    <select
      class="ui-select"
      :value="modelValue"
      :data-testid="testid"
      @change="$emit('update:modelValue', Number($event.target.value))"
    >
      <option :value="0">All</option>
      <option v-for="option in options" :key="option.id" :value="option.id">
        {{ option.label }}
      </option>
    </select>
  </label>
</template>
