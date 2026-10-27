<script setup lang="ts">
import { computed } from 'vue'
import type { Style } from '../api'
import { entryText, formatScore, stateLabel } from '../api'
import Icon from './Icon.vue'
const props = defineProps<{ item: Style; admin?: boolean; rank?: number }>()
// First two filled-in entries, parameters before visual traits.
const specs = computed(() => props.item.info ? [...props.item.info.params, ...props.item.info.visual].slice(0, 2).map(entryText).join(' · ') : '')
defineEmits<{ open: [] }>()
</script>
<template>
  <button class="style-card" :class="{ top: rank === 1 }" @click="$emit('open')">
    <div class="card-media"><img v-if="item.cover" :src="item.cover.thumbnailUrl" :alt="item.name" loading="lazy" /><Icon v-else name="image" :size="36" /><span v-if="rank" class="card-rank">{{ rank }}</span><span v-if="admin && item.state !== 'ready'" class="badge card-badge" :class="item.state">{{ stateLabel[item.state || 'draft'] }}</span></div>
    <div class="card-body">
      <h3 class="card-title" :title="item.name">{{ item.name }}</h3>
      <p v-if="specs" class="card-specs" :title="specs">{{ specs }}</p>
      <div v-if="item.similarity !== undefined" class="similarity" :title="`相似度 ${formatScore(item.similarity)}`"><b>{{ formatScore(item.similarity) }}</b><span class="meter"><i :style="{ width: `${Math.max(0, item.similarity) * 100}%` }" /></span></div>
      <p class="card-meta">{{ item.displayCount }} 张展示图<template v-if="admin"> · {{ item.recognitionCount }} 张识别图<span v-if="item.pendingCount" class="card-pending"> · {{ item.pendingCount }} 张索引中</span></template></p>
    </div>
  </button>
</template>
