<script setup lang="ts">
import type { Crop } from '../api'
defineProps<{ src: string; alt: string; crop?: Crop | null }>()
</script>
<template>
  <!-- Wraps the image tightly so the crop overlay lines up with the visible pixels; the parent must be a size container. -->
  <span class="framed"><img :src="src" :alt="alt" draggable="false" /><span v-if="crop" class="framed-crop" :style="{ left: `${crop.x * 100}%`, top: `${crop.y * 100}%`, width: `${crop.width * 100}%`, height: `${crop.height * 100}%` }" /></span>
</template>
