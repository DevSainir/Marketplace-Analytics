<script setup>
/**
 * One A/Б-тест: upload the photos, then read what each of them earned.
 *
 * The result table is transposed relative to WB's own A/Б screen. WB compares
 * exactly two images, so it can afford variants as columns and metrics as rows;
 * a rotation runs up to ten, so **photos are the rows** — the picture itself in
 * the first cell — and the metrics are the columns. Otherwise the table grows
 * sideways off the page.
 *
 * A ratio reads «—» rather than 0 % when its denominator is empty: a photo that
 * has not been live yet has not converted nobody, it has not been measured.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import { MAX_VARIANTS, STATUS_LABELS, useAbTestsStore } from '@/modules/abTests'

const route = useRoute()
const store = useAbTestsStore()
const fileInput = ref(null)

const test = computed(() => store.detail)

onMounted(() => store.loadTest(route.params.testId))
watch(
  () => route.params.testId,
  (id) => id && store.loadTest(id),
)

function percent(value) {
  return value === null || value === undefined ? '—' : `${Number(value).toFixed(2)} %`
}

function count(value) {
  return Number(value ?? 0).toLocaleString('ru-RU')
}

async function onFiles(event) {
  const files = Array.from(event.target.files || []).slice(0, store.remainingSlots)
  for (const file of files) {
    const ok = await store.addPhoto(route.params.testId, file)
    if (!ok) break
  }
  if (fileInput.value) fileInput.value.value = ''
}
</script>

<template>
  <main class="app-container py-xl phone:py-lg">
    <header class="mb-lg">
      <RouterLink
        :to="{ name: 'ab-tests' }"
        class="text-base font-medium text-action hover:underline"
      >
        ← Ко всем A/Б-тестам
      </RouterLink>
      <h1 v-if="test" class="mt-sm text-h2 font-bold text-primary">{{ test.name }}</h1>
      <p v-if="test" class="mt-xs text-base text-muted">
        WB артикул: {{ test.nm_id }}
        <span v-if="test.vendor_code"> · Артикул продавца: {{ test.vendor_code }}</span>
        · Статус: {{ STATUS_LABELS[test.status] || test.status }} · Смена фото каждые
        {{ count(test.impression_budget) }} показов
      </p>
    </header>

    <p v-if="store.error" class="mb-md text-base text-status-negative" data-testid="error">
      {{ store.error }}
    </p>

    <section
      v-if="test"
      class="mb-lg rounded-card border border-border-subtle bg-surface p-lg shadow-card phone:p-md"
    >
      <div class="flex flex-wrap items-center gap-md">
        <label class="text-base font-medium text-primary">
          Фото в ротации: {{ test.variants.length }} из {{ MAX_VARIANTS }}
        </label>
        <input
          ref="fileInput"
          type="file"
          accept="image/*"
          multiple
          data-testid="upload"
          :disabled="!store.canUpload || store.saving"
          class="text-base"
          @change="onFiles"
        />
        <button
          v-if="test.status === 'draft' || test.status === 'paused'"
          type="button"
          class="rounded-control bg-action px-md py-sm text-base font-medium text-white hover:opacity-90 disabled:opacity-50"
          :disabled="store.saving || !test.variants.length"
          data-testid="start"
          @click="store.changeStatus(test.id, 'running')"
        >
          Запустить
        </button>
        <button
          v-if="test.status === 'running'"
          type="button"
          class="rounded-control border border-border-subtle px-md py-sm text-base font-medium text-primary hover:bg-zebra"
          :disabled="store.saving"
          data-testid="pause"
          @click="store.changeStatus(test.id, 'paused')"
        >
          Пауза
        </button>
      </div>
      <p class="mt-sm text-base text-muted">
        Первое фото встаёт на карточку сразу при запуске. Дальше вариант меняется, когда наберёт
        свои показы — данные по рекламе WB отдаёт за прошедшие сутки, поэтому смена происходит на
        следующий день, а сам день смены не засчитывается ни одному из фото.
      </p>
    </section>

    <section
      v-if="test && test.variants.length"
      class="rounded-card border border-border-subtle bg-surface shadow-card"
    >
      <table class="app-datatable w-full" data-testid="results">
        <thead>
          <tr class="text-left text-tiny font-medium uppercase tracking-wide text-muted">
            <th class="px-lg py-md">Фото</th>
            <th class="px-lg py-md">Доля переходов в карточку</th>
            <th class="px-lg py-md">Доля добавлений в корзину</th>
            <th class="px-lg py-md">Доля оформлений заказов</th>
            <th class="px-lg py-md">Показы карточки в выдаче</th>
            <th class="px-lg py-md">Переходы в карточку</th>
            <th class="px-lg py-md">Добавления в корзину</th>
            <th class="px-lg py-md">Оформления заказов</th>
            <th class="px-lg py-md">Дней в тесте</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="variant in test.variants"
            :key="variant.variant_id"
            class="border-t border-border-subtle"
            :class="variant.variant_id === test.leader_variant_id ? 'bg-zebra' : ''"
            data-testid="variant-row"
          >
            <td class="px-lg py-md">
              <div class="flex items-center gap-sm">
                <img
                  :src="variant.image_url"
                  :alt="`Вариант ${variant.position}`"
                  class="h-20 w-16 rounded-control object-cover"
                />
                <div>
                  <div class="text-base font-medium text-primary">
                    Вариант {{ variant.position }}
                  </div>
                  <div v-if="variant.is_active" class="text-tiny text-status-positive">
                    Сейчас на карточке
                  </div>
                  <div
                    v-else-if="variant.variant_id === test.leader_variant_id"
                    class="text-tiny text-status-positive"
                  >
                    Лидер по CTR
                  </div>
                  <button
                    v-if="!variant.is_active"
                    type="button"
                    class="mt-xs text-tiny text-muted hover:underline"
                    :disabled="store.saving"
                    @click="store.removePhoto(test.id, variant.variant_id)"
                  >
                    Удалить
                  </button>
                </div>
              </div>
            </td>
            <td class="px-lg py-md text-base tabular-nums" data-testid="ctr">
              {{ percent(variant.click_through) }}
            </td>
            <td class="px-lg py-md text-base tabular-nums">{{ percent(variant.add_to_cart) }}</td>
            <td class="px-lg py-md text-base tabular-nums">{{ percent(variant.order_rate) }}</td>
            <td class="px-lg py-md text-base tabular-nums">{{ count(variant.views) }}</td>
            <td class="px-lg py-md text-base tabular-nums">{{ count(variant.clicks) }}</td>
            <td class="px-lg py-md text-base tabular-nums">{{ count(variant.atbs) }}</td>
            <td class="px-lg py-md text-base tabular-nums">{{ count(variant.orders) }}</td>
            <td class="px-lg py-md text-base tabular-nums">{{ count(variant.days_measured) }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <p v-else-if="test" class="text-base text-muted">
      Загрузите до {{ MAX_VARIANTS }} вариантов главного фото — они будут сменять друг друга по мере
      набора показов, и здесь появится их сравнение.
    </p>
  </main>
</template>
