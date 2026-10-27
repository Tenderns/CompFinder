<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, infoCount, infoFile, infoSample, json, validateFile, type ImportGroup, type ImportJob, type ImportPreview } from '../api'
import { fail, notify } from '../ui'
import Icon from './Icon.vue'
const emit = defineEmits<{ changed: []; edit: [string] }>()
const picker = ref<HTMLInputElement>()
const files = ref<File[]>([])
// Text of each 款式信息.json by relative path; the server parses and checks it.
const infos = ref<Record<string, string>>({})
const preview = ref<ImportPreview | null>(null)
const job = ref<ImportJob | null>(null)
const history = ref<ImportJob[]>([])
const busy = ref(false)
const checking = ref(false)
const completed = ref(0)
const current = ref('')
const localErrors = ref<string[]>([])
const failures = computed(() => job.value?.files?.filter(f => f.state === 'failed' || f.state === 'skipped' || f.state === 'pending') || [])
const importable = computed(() => preview.value?.groups.filter(g => !g.skip || g.info).length || 0)
const updates = computed(() => preview.value?.groups.filter(g => g.skip && g.info).length || 0)
const sampleHref = `data:application/json;charset=utf-8,${encodeURIComponent(infoSample)}`
const isInfo = (file: File) => file.name.toLowerCase() === infoFile
const manifest = () => ({ paths: files.value.filter(f => !isInfo(f)).map(f => f.webkitRelativePath), infos: infos.value })
function action(group: ImportGroup) {
  if (group.skip) return group.info ? { text: group.displayCount + group.recognitionCount ? '跳过图片，更新信息' : '更新款式信息', tone: 'ready' } : { text: '同名跳过', tone: 'draft' }
  return group.displayCount && group.recognitionCount ? { text: '新建款式', tone: 'ready' } : { text: '保存为草稿', tone: 'draft' }
}
function preventUnload(event: BeforeUnloadEvent) { if (busy.value) { event.preventDefault(); event.returnValue = '' } }
async function loadHistory() { history.value = (await api<{ items: ImportJob[] }>('/admin/imports')).items }
async function select(event: Event) {
  files.value = Array.from((event.target as HTMLInputElement).files || []); infos.value = {}; preview.value = null; job.value = null; localErrors.value = []
  if (!files.value.length) return
  checking.value = true
  try {
    infos.value = Object.fromEntries(await Promise.all(files.value.filter(isInfo).map(async f => [f.webkitRelativePath, await f.text()] as const)))
    preview.value = await api<ImportPreview>('/admin/imports/preview', json('POST', manifest()))
  }
  catch (error) { fail(error) } finally { checking.value = false }
}
async function start() {
  busy.value = true; completed.value = 0; localErrors.value = []
  try {
    job.value = await api<ImportJob>('/admin/imports', json('POST', manifest()))
    const fileMap = new Map(files.value.map(file => [file.webkitRelativePath, file]))
    for (const entry of job.value.files || []) {
      current.value = entry.path
      if (entry.state === 'pending') {
        const file = fileMap.get(entry.path)!
        const invalid = validateFile(file)
        if (invalid) localErrors.value.push(invalid)
        else {
          const body = new FormData(); body.append('path', entry.path); body.append('file', file)
          try { await api(`/admin/imports/${job.value.id}/files`, { method: 'POST', body }) }
          catch (error) { localErrors.value.push(`${entry.path}：${error instanceof Error ? error.message : '上传失败'}`) }
        }
      }
      completed.value++
    }
    job.value = await api<ImportJob>(`/admin/imports/${job.value.id}/finish`, { method: 'POST' })
    preview.value = null; files.value = []; infos.value = {}; emit('changed'); await loadHistory()
    notify('文件导入完成，识别图片将在后台建立索引')
  } catch (error) { fail(error) }
  finally { busy.value = false; current.value = '' }
}
async function inspect(id: string) { try { job.value = await api<ImportJob>(`/admin/imports/${id}`); preview.value = null } catch (error) { fail(error) } }
onMounted(() => { loadHistory().catch(fail); window.addEventListener('beforeunload', preventUnload) })
onBeforeUnmount(() => window.removeEventListener('beforeunload', preventUnload))
defineExpose({ busy })
</script>
<template>
  <section class="page-head"><div><h1>批量导入</h1><p>按款式整理好展示图和识别图两套照片，选择文件夹一次导入；款式信息可以一起导入。</p></div></section>
  <div class="import-layout"><section class="panel import-panel"><div class="section-title"><div><h2>选择图库文件夹</h2><p>支持千款以内的图库，导入前会先预览检查。</p></div></div><input ref="picker" type="file" webkitdirectory multiple class="sr-only" aria-label="选择图库文件夹" :disabled="busy || checking" @change="select" /><button class="dropzone folder-drop" :disabled="busy || checking" @click="picker?.click()"><span class="upload-symbol"><Icon name="folder" :size="30" /></span><strong>{{ checking ? '正在检查文件夹…' : '选择文件夹' }}</strong><span>自动识别款式名称、两套图片集和款式信息</span></button><p class="import-note">同名款式不导入图片，只用其中的款式信息.json 更新信息；缺少一套图片时保存为草稿，可稍后补齐。</p></section>
    <aside class="folder-guide"><span class="eyebrow">FOLDER STRUCTURE</span><h3>像这样整理图片</h3><pre>待导入图库/
├─ 款式A/
│  ├─ 款式信息.json  可选
│  ├─ 展示图/
│  │  └─ 正面.jpg
│  └─ 识别图/
│     ├─ 实拍1.jpg
│     └─ 实拍2.jpg
└─ 款式B/
   ├─ 展示图/
   └─ 识别图/</pre><p>子目录请命名为“展示图”和“识别图”。<br />JPG、PNG、WebP · 每张 ≤ 20 MB</p><h3 class="guide-gap">款式信息.json</h3><p>写“参数”“视觉信息”“备注”三部分，都可以省略。视觉信息填 AI 识别出的分类结果即可，内容可以是文字、数字或列表。用 UTF-8 编码保存。</p><a class="button small guide-sample" :href="sampleHref" :download="infoFile"><Icon name="download" :size="16" />下载示例文件</a></aside></div>
  <section v-if="preview && !busy" class="panel import-preview"><div class="section-title"><div><h2>导入预览</h2><p>{{ importable - updates }} 个新款式<template v-if="updates"> · {{ updates }} 个同名款式更新信息</template> · {{ preview.groups.length - importable }} 个同名款式跳过 · {{ preview.rejected.length }} 个无效文件</p></div><button class="button primary" :disabled="!importable" @click="start"><Icon name="upload" :size="18" />开始导入</button></div><div class="table-scroll"><table><thead><tr><th>款式名称</th><th>展示图</th><th>识别图</th><th>款式信息</th><th>处理方式</th></tr></thead><tbody><tr v-for="group in preview.groups" :key="group.name"><td>{{ group.name }}</td><td>{{ group.displayCount }} 张</td><td>{{ group.recognitionCount }} 张</td><td>{{ group.info ? `${infoCount(group.info)} 项` : '—' }}</td><td><span class="badge" :class="action(group).tone">{{ action(group).text }}</span></td></tr></tbody></table></div><details v-if="preview.rejected.length"><summary>查看无效文件</summary><p v-for="entry in preview.rejected" :key="entry.path" class="file-error">{{ entry.path }}：{{ entry.message }}</p></details></section>
  <section v-if="busy" class="panel import-progress" aria-live="polite"><div class="section-title"><h2><span class="spinner" />正在导入文件</h2><span>{{ completed }} / {{ job?.total || files.length }}</span></div><progress :value="completed" :max="job?.total || files.length || 1" /><p class="muted truncate">{{ current }}</p><p class="muted">请保持页面打开。识别图片会在后台依次建立索引。</p></section>
  <section v-else-if="job" class="panel import-report"><div class="section-title"><div><h2>{{ job.state === 'complete' ? '导入结果' : '导入尚未完成' }}</h2><p>已上传 {{ job.counts.uploaded }} 张 · 重复 {{ job.counts.duplicate }} 张 · 跳过 {{ job.counts.skipped }} 张 · 失败 {{ job.counts.failed }} 张<template v-if="job.counts.info"> · 款式信息 {{ job.counts.info }} 份</template></p></div><span class="badge" :class="job.counts.failed ? 'draft' : 'ready'">{{ job.state === 'complete' ? '文件处理完成' : '可在款式中补图' }}</span></div><p v-if="job.state === 'interrupted'" class="info-banner">上次上传被中断，已保存的图片仍在。可打开对应款式补充剩余图片。</p><div v-if="localErrors.length" class="error-banner multiline">{{ localErrors.join('\n') }}</div><details v-if="failures.length" open><summary>需要关注的文件（{{ failures.length }}）</summary><div v-for="entry in failures" :key="entry.path" class="import-file-row"><div><strong>{{ entry.path }}</strong><p>{{ entry.message || '未完成上传' }}</p></div><button v-if="entry.styleId" class="button small" @click="emit('edit', entry.styleId)">补充图片</button></div></details><p v-else class="muted">图片已保存。可在图库管理中查看识别图片的索引进度。</p></section>
  <section v-if="history.length && !busy" class="import-history"><h2>最近导入</h2><button v-for="entry in history" :key="entry.id" class="history-row" @click="inspect(entry.id)"><span>{{ new Date(entry.createdAt).toLocaleString('zh-CN') }}</span><span>{{ entry.total }} 个文件</span><span>{{ entry.state === 'complete' ? '已完成' : '未完成' }}</span><Icon name="arrow" :size="18" /></button></section>
</template>
