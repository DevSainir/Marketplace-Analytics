<script setup>
/**
 * ФИНМОДЕЛЬ — /labs/finmodel.
 *
 * Страница пришла готовым одностраничником (`docs/finmodelka/`): собственная
 * вёрстка, собственные токены, вся логика на голом DOM. Она перенесена сюда
 * как есть, а не переписана на Vue, и это осознанно — расчёты и разнесения в
 * ней проверены против контрольных цифр `docs/finmodelka/CONTEXT.md`, и
 * перекладывание их на реактивность поменяло бы цифры ради формы.
 *
 * Поэтому здесь ровно два шва:
 *   * разметка шапки и панели управления живёт в этом шаблоне — остальное
 *     страница рисует сама внутрь `#panels`;
 *   * `mountFinmodel` получает корень и от него ищет свои элементы, так что
 *     ни один id и ни один токен не выходят за пределы вьюхи.
 *
 * Данные — статический датапак из `public/labs/finmodel/`, окно P&L
 * 15.07–06.09.2026. Ни одного обращения к нашему API страница не делает.
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'

import { mountFinmodel } from '@/modules/labs/finmodel/mount'

const root = ref(null)
let unmount = null

onMounted(async () => {
  unmount = await mountFinmodel(root.value)
})

onBeforeUnmount(() => {
  if (unmount) unmount()
})
</script>

<template>
  <div ref="root" class="finmodel">
    <div class="wrap">
      <header class="masthead">
        <div>
          <h1>Финмодель Демо</h1>
          <div class="sub">Что приносит каждый артикул, когда он кончится и что будет дальше</div>
        </div>
        <div class="stamp" id="stamp"></div>
      </header>

      <div class="controls" id="controls" hidden>
        <div class="ctl-group">
          <span class="ctl-label">Период</span>
          <input type="date" id="dFrom" aria-label="Начало периода" />
          <span class="muted">—</span>
          <input type="date" id="dTo" aria-label="Конец периода" />
        </div>
        <div class="chips" id="presets"></div>
        <div class="ctl-group">
          <span class="ctl-label">Выручка по</span>
          <select id="revBase" aria-label="База выручки">
            <option value="gross">цене реализации WB</option>
            <option value="card">цене карточки — до СПП</option>
          </select>
        </div>
        <div class="spacer"></div>
        <span class="savestate" id="savestate"></span>
        <button class="btn" id="reset" type="button">Сбросить допущения</button>
      </div>

      <nav class="tabs" id="tabs" role="tablist" hidden></nav>
      <main id="panels"><div class="loading">Загружаю данные…</div></main>
    </div>
  </div>
</template>

<style src="@/modules/labs/views/LabFinmodelView.css"></style>
