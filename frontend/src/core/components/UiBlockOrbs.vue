<script setup>
/**
 * A local light source for a band of glass.
 *
 * Unlike the ambient orbs in `UiPage`, these are absolutely positioned inside
 * the block they light and scroll with it. That is what makes a glass pane's
 * transparency legible: over a flat ground a pane shows nothing, over a colour
 * edge it shows everything.
 *
 * Placement lives in `ui-next/components.css` — the orbs are anchored from the
 * band's bottom edge so each lands under its own block.
 */
</script>

<template>
  <div class="ui-blockorbs" aria-hidden="true">
    <span class="ui-blockorb ui-blockorb--orange"></span>
    <span class="ui-blockorb ui-blockorb--pink"></span>
  </div>
</template>
