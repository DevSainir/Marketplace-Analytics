<script setup>
/**
 * The design system's page shell: ambient ground behind, content layer in
 * front. `App.vue` wraps the whole app in one of these, so no view has to
 * think about it.
 *
 * The ground is FIXED rather than scrolling on purpose — the orbs stay put
 * while the page moves over them, so glass refracts something different at
 * every scroll position instead of a flat wash.
 *
 * Attributes fall through to the CONTENT layer, not the wrapper: the wrapper's
 * only job is to establish the stacking context the ground sits behind, and a
 * layout class landing there would have nothing to lay out.
 */
defineOptions({ inheritAttrs: false })
</script>

<template>
  <div class="ui-next">
    <div class="ui-ground" aria-hidden="true">
      <div class="ui-ground__orbs">
        <span class="ui-orb ui-orb--a"></span>
        <span class="ui-orb ui-orb--c"></span>
        <span class="ui-orb ui-orb--d"></span>
        <span class="ui-orb ui-orb--e"></span>
      </div>
      <div class="ui-ground__grain"></div>
    </div>

    <div class="ui-page" v-bind="$attrs"><slot /></div>
  </div>
</template>
