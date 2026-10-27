<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { api, type Style } from '../api'
import { fail } from '../ui'
import Icon from './Icon.vue'
import StyleCard from './StyleCard.vue'
const props = defineProps<{ admin?: boolean; revision: number }>()
defineEmits<{ detail: [string]; edit: [string]; create: []; import: [] }>()
const items = ref<Style[]>([])
const query = ref('')
const loading = ref(true)
const problem = ref('')
const filter = ref<'all' | 'ready' | 'draft'>('all')
let alive = true
let serial = 0
const filters = computed(() => [
  { id: 'all', label: '全部', count: items.value.length },
  { id: 'ready', label: '可检索', count: items.value.filter(i => i.searchable).length },
  { id: 'draft', label: '待完善', count: items.value.filter(i => !i.searchable).length },
] as const)
// Name, parameters, visual traits and notes are all searchable.
const searchText = (item: Style) => [item.name, item.info?.notes || '', ...[...item.info?.params || [], ...item.info?.visual || []].flatMap(e => [e.name, e.value])].join('\n').toLocaleLowerCase()
const filtered = computed(() => {
  const needle = query.value.trim().toLocaleLowerCase()
  return items.value.filter(item => (!needle || searchText(item).includes(needle)) && (filter.value === 'all' || (filter.value === 'ready' ? item.searchable : !item.searchable)))
})
async function refresh(silent = false) {
  const ticket = ++serial
  try {
    const data = await api<{ items: Style[] }>(props.admin ? '/admin/styles' : '/styles')
    if (alive && ticket === serial) { items.value = data.items; problem.value = '' }
  } catch (error) { if (!silent && alive) { problem.value = '图库加载失败，请重试'; fail(error) } }
  finally { if (alive) loading.value = false }
}
watch(() => [props.admin, props.revision], () => refresh(true))
onMounted(() => refresh())
const timer = setInterval(() => { if (items.value.some(item => item.pendingCount)) refresh(true) }, 3000)
onBeforeUnmount(() => { alive = false; clearInterval(timer) })
</script>
<template>
  <section class="page-head"><div><h1>{{ admin ? '图库管理' : '我的图库' }}</h1><p>{{ admin ? '每个款式包含展示图与识别图两套图片，齐全并完成索引后即可被搜索。' : '所有可被搜索的款式。点击查看展示图，或用其中一张图搜索相似款式。' }}</p></div><div v-if="admin" class="actions"><button class="button" @click="$emit('import')"><Icon name="folder" :size="17" />批量导入</button><button class="button primary" @click="$emit('create')"><Icon name="plus" :size="17" />新建款式</button></div></section>
  <div class="toolbar"><label class="search-field"><Icon name="search" :size="17" /><input v-model="query" type="search" placeholder="按名称、参数查找" aria-label="查找款式" /></label><div v-if="admin" class="segmented" role="group" aria-label="按状态筛选"><button v-for="f in filters" :key="f.id" :class="{ active: filter === f.id }" :aria-pressed="filter === f.id" @click="filter = f.id">{{ f.label }}<span>{{ f.count }}</span></button></div><span class="toolbar-count">{{ filtered.length }} 个款式</span></div>
  <div v-if="loading" class="result-grid"><div v-for="n in 8" :key="n" class="skeleton-card"><span /><i /><i /></div></div>
  <div v-else-if="problem" class="empty-state"><h3>{{ problem }}</h3><button class="button" @click="refresh()">重新加载</button></div>
  <div v-else-if="filtered.length" class="result-grid"><StyleCard v-for="item in filtered" :key="item.id" :item="item" :admin="admin" @open="admin ? $emit('edit', item.id) : $emit('detail', item.id)" /></div>
  <div v-else class="empty-state boxed"><span class="empty-art"><Icon name="layers" :size="40" /></span><h3>{{ items.length ? '没有找到匹配的款式' : '图库还是空的' }}</h3><p>{{ items.length ? '换一个名称或筛选条件试试。' : admin ? '新建款式并上传两套图片，也可以按文件夹批量导入。' : '在图库管理中上传展示图与识别图，索引完成后会出现在这里。' }}</p><button v-if="admin && !items.length" class="button primary" @click="$emit('create')"><Icon name="plus" :size="17" />建立第一个款式</button></div>
</template>
