<script setup>
/**
 * The «Баланс по товарным остаткам» block of the finreports page: title, its own
 * day picker, and the grid.
 *
 * Its own period, deliberately: the P&L above it aggregates a RANGE of
 * settlement days, while stock is a point-in-time snapshot — summing two days of
 * it would count the same units twice. So this picks one day, bounded by the
 * days WB actually captured (`available_from`/`available_to`), since stock is
 * never carried over into a day that has no snapshot.
 *
 * A view-level composition rather than a page of its own: the balance is the
 * other half of the same question the P&L asks — the P&L is what the goods that
 * moved did to the money, this is where the money that has not moved is sitting.
 */
import { onMounted } from 'vue'

import BalanceTable from '@/modules/finreports/components/BalanceTable.vue'
import { useFinReportsStore } from '@/modules/finreports/store'

import BusyRegion from '@/core/components/BusyRegion.vue'
import DataState from '@/core/components/DataState.vue'
import DayPicker from '@/core/components/DayPicker.vue'

const store = useFinReportsStore()

onMounted(() => {
  // No day picked yet → the backend answers with its newest snapshot, and the
  // picker adopts that day from the response.
  if (!store.balance) store.loadBalance()
})
</script>

<template>
  <section class="mt-xl">
    <header class="mb-sm flex flex-wrap items-end justify-between gap-md">
      <div>
        <h2 class="text-h3 font-semibold text-primary">Баланс по товарным остаткам</h2>
        <p class="mt-xs max-w-4xl text-tiny text-muted">
          Остатки на складах WB на выбранный день и их стоимость по себестоимости.
        </p>
      </div>

      <DayPicker
        v-if="store.balanceDate"
        :model-value="store.balanceDate"
        :min="store.balance?.available_from ?? ''"
        :max="store.balance?.available_to ?? store.balanceDate"
        aria-label="День остатков"
        @update:model-value="store.setBalanceDate($event)"
      />
    </header>

    <DataState v-if="!store.balance && store.balanceLoading" kind="loading" />
    <DataState
      v-else-if="!store.balance && store.balanceError"
      kind="error"
      :text="store.balanceError"
    />

    <BusyRegion v-else-if="store.balance" :busy="store.balanceLoading">
      <!-- A failed MARK must not take the grid away: it is written in the
           background while the table already shows the new order, so the
           rollback is a line above the grid, not an empty state. -->
      <DataState
        v-if="store.balanceError"
        kind="error"
        layout="line"
        :text="store.balanceError"
        class="mb-sm"
      />
      <BalanceTable
        :balance="store.balance"
        @mark="store.toggleBalancePin($event.kind, $event.value, $event.pinned)"
      />
      <ul v-if="store.balance.notes?.length" class="mt-sm space-y-xs">
        <li v-for="note in store.balance.notes" :key="note" class="text-tiny text-muted">
          ⚠ {{ note }}
        </li>
      </ul>
    </BusyRegion>
  </section>
</template>
