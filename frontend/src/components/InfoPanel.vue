<script setup lang="ts">
import { infoCount, infoGroups, type StyleInfo } from '../api'
import Icon from './Icon.vue'
defineProps<{ info?: StyleInfo | null; loading?: boolean }>()
defineEmits<{ edit: [] }>()
</script>
<template>
  <aside class="info-panel" aria-label="款式信息">
    <header class="info-head"><h3>款式信息</h3><button class="button small ghost" @click="$emit('edit')"><Icon name="edit" :size="15" />编辑</button></header>
    <span v-if="loading" class="spinner" />
    <template v-else-if="info && infoCount(info)">
      <section v-for="group in infoGroups" v-show="info[group.key].length" :key="group.key" class="info-section"><h4>{{ group.label }}</h4><dl class="info-list"><template v-for="(entry, i) in info[group.key]" :key="i"><dt>{{ entry.name }}</dt><dd>{{ entry.value || '—' }}</dd></template></dl></section>
      <section v-if="info.notes" class="info-section"><h4>备注</h4><p class="multiline">{{ info.notes }}</p></section>
    </template>
    <p v-else class="info-empty">暂未填写参数和视觉信息。<br />点击“编辑”可以补充，也可以留空。</p>
  </aside>
</template>
