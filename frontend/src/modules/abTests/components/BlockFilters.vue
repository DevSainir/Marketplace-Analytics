<script setup>
/**
 * The heading of a block, with the two filters that narrow what it shows.
 *
 * Shared by «Ход теста» and «Тестирование» because the pair has to behave
 * identically in both: the same campaigns in the same order, the same laps, and
 * the campaign on the LEFT — it is the coarser cut, and reading right to left
 * («третий круг … единой ставки») is how the sentence comes out backwards.
 *
 * Each filter hides itself when it has nothing to offer. One campaign is not a
 * choice, and a test that has not completed a lap has no lap to pick.
 */
import CampaignPicker from '@/modules/abTests/components/CampaignPicker.vue'

defineProps({
  /** The block's heading. */
  title: { type: String, required: true },
  /** Tailwind classes for the heading — the two blocks size theirs differently. */
  titleClass: { type: String, default: 'text-base font-semibold text-primary' },
  /** The campaigns that brought traffic, in the page's order. */
  campaigns: { type: Array, default: () => [] },
  /** The selected campaign id; 0 is «Все». */
  campaign: { type: Number, default: 0 },
  /** The laps on offer, newest first. */
  rounds: { type: Array, default: () => [] },
  /** The selected lap; 0 is all of them. */
  round: { type: Number, default: 0 },
  /** What «all laps» is called here — the timeline says «Все круги». */
  allRoundsLabel: { type: String, default: 'Все' },
  /** `data-testid` of the campaign select. */
  campaignTestid: { type: String, default: 'campaign-filter' },
  /** `data-testid` of the lap select. */
  roundTestid: { type: String, default: 'round-filter' },
})
defineEmits(['update:campaign', 'update:round'])
</script>

<template>
  <header class="mb-md flex flex-wrap items-center justify-between gap-md">
    <h2 :class="titleClass">{{ title }}</h2>

    <div class="flex flex-wrap items-center gap-md">
      <CampaignPicker
        v-if="campaigns.length > 1"
        :campaigns="campaigns"
        :model-value="campaign"
        :testid="campaignTestid"
        @update:model-value="$emit('update:campaign', $event)"
      />

      <label v-if="rounds.length" class="flex items-center gap-sm text-tiny text-muted">
        <span>Круг</span>
        <select
          class="ui-select"
          :value="round"
          :data-testid="roundTestid"
          @change="$emit('update:round', Number($event.target.value))"
        >
          <option :value="0">{{ allRoundsLabel }}</option>
          <option v-for="option in rounds" :key="option" :value="option">{{ option }}</option>
        </select>
      </label>
    </div>
  </header>
</template>
