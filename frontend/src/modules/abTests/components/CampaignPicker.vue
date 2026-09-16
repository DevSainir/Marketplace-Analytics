<script setup>
/**
 * «Рекламная кампания» — which campaign's measurements a block is showing.
 *
 * Sits to the left of the lap picker in both «Ход теста» and «Тестирование»,
 * because the two filters compose: «третий круг единой ставки» is a question
 * the page can now answer, and either filter alone is a different one.
 *
 * Rendered only when more than one campaign has actually brought the test
 * traffic — the parent decides that. A picker with one option is furniture.
 */
import { computed } from 'vue'

const props = defineProps({
  /** The campaigns that brought traffic, as the detail endpoint ordered them. */
  campaigns: { type: Array, default: () => [] },
  /** The selected campaign id; 0 is «Все». */
  modelValue: { type: Number, default: 0 },
  /** Which `data-testid` the select carries. */
  testid: { type: String, default: 'campaign-filter' },
})
defineEmits(['update:modelValue'])

/**
 * «Первая (Единая по платьям)» — the position, then the campaign's own name.
 *
 * The position is what the seller says out loud («первая, вторая») and the name
 * is what they can find in the WB cabinet; neither on its own identifies a
 * campaign to somebody looking at both screens.
 */
const ORDINALS = ['Первая', 'Вторая', 'Третья', 'Четвёртая', 'Пятая']

const options = computed(() =>
  props.campaigns.map((campaign, index) => ({
    id: campaign.campaign_id,
    label: `${ORDINALS[index] ?? `№${index + 1}`} (${campaign.name})`,
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
