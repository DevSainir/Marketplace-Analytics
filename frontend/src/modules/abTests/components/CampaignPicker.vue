<script setup>
/**
 * «Рекламная кампания» — which campaign's measurements a block is showing.
 *
 * Sits to the left of the lap picker in both «Ход теста» and «Тестирование»,
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
  /** The selected campaign id; 0 is «Все». */
  modelValue: { type: Number, default: 0 },
  /** The tested article's own code — the same for every campaign here. */
  vendorCode: { type: String, default: '' },
  /** Which `data-testid` the select carries. */
  testid: { type: String, default: 'campaign-filter' },
})
defineEmits(['update:modelValue'])

/**
 * «M-TRX01-BLK / 12345678 / Единая» — the article, the campaign's id in WB, and
 * what kind of campaign it is.
 *
 * Not the campaign's own name: sellers often name a campaign after the
 * article's WB number, so the name read as an article id rather than a
 * campaign. The id is what the seller finds in the WB cabinet.
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
    <span>Рекламная кампания</span>
    <select
      class="ui-select"
      :value="modelValue"
      :data-testid="testid"
      @change="$emit('update:modelValue', Number($event.target.value))"
    >
      <option :value="0">Все</option>
      <option v-for="option in options" :key="option.id" :value="option.id">
        {{ option.label }}
      </option>
    </select>
  </label>
</template>
