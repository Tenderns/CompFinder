<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, json, type McpTool, type McpToken } from '../api'
import { confirmAction, copyText, fail, notify } from '../ui'
import Icon from './Icon.vue'
import Modal from './Modal.vue'
interface Draft { id: string | null; name: string; secret: string; original: string; tools: string[] }
const items = ref<McpToken[]>([])
const tools = ref<McpTool[]>([])
const loading = ref(true)
const problem = ref('')
const revealed = ref(new Set<string>())
const draft = ref<Draft | null>(null)
const saving = ref(false)
const endpoint = `${location.origin}/mcp`
const secure = location.protocol === 'https:' || ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname)
const titles = computed(() => new Map(tools.value.map(tool => [tool.name, tool.title])))
const writes = computed(() => new Set(tools.value.filter(tool => tool.writes).map(tool => tool.name)))
const groups = computed(() => [...new Set(tools.value.map(tool => tool.group))].map(group => ({ group, tools: tools.value.filter(tool => tool.group === group) })))
const presets = computed(() => [
  { label: '全部（可建档）', tools: tools.value.map(tool => tool.name) },
  { label: '只读（搜索和查看）', tools: tools.value.filter(tool => !tool.writes).map(tool => tool.name) },
])
const secretChanged = computed(() => !!draft.value?.id && draft.value.secret.trim() !== draft.value.original)
async function load() {
  try {
    const data = await api<{ items: McpToken[]; tools: McpTool[] }>('/admin/tokens')
    items.value = data.items; tools.value = data.tools; problem.value = ''
  } catch (error) { problem.value = '令牌加载失败，请重试'; fail(error) } finally { loading.value = false }
}
function randomSecret() {
  const bytes = crypto.getRandomValues(new Uint8Array(32))
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}
function generate() { if (draft.value) draft.value.secret = randomSecret() }
function applyPreset(names: string[]) { if (draft.value) draft.value.tools = [...names] }
function create() { draft.value = { id: null, name: '', secret: '', original: '', tools: tools.value.map(tool => tool.name) } }
function edit(token: McpToken) { draft.value = { id: token.id, name: token.name, secret: token.secret, original: token.secret, tools: [...token.tools] } }
async function save() {
  const value = draft.value
  if (!value) return
  saving.value = true
  try {
    // An empty or unchanged secret is left out: the server generates one for new tokens and keeps the old one otherwise.
    const secret = value.secret.trim()
    const body = { name: value.name.trim(), tools: value.tools, ...(secret && secret !== value.original ? { secret } : {}) }
    const saved = await api<McpToken>(value.id ? `/admin/tokens/${value.id}` : '/admin/tokens', json(value.id ? 'PATCH' : 'POST', body))
    revealed.value.add(saved.id)
    draft.value = null
    await load()
    notify(value.id ? '令牌已保存' : '令牌已创建，复制后填入 AI 客户端即可使用')
  } catch (error) { fail(error) } finally { saving.value = false }
}
async function toggle(token: McpToken) {
  try { await api(`/admin/tokens/${token.id}`, json('PATCH', { enabled: !token.enabled })); await load() } catch (error) { fail(error) }
}
async function remove(token: McpToken) {
  if (!await confirmAction(`删除后，使用“${token.name}”的 AI 客户端将无法再连接。`, { title: '删除令牌？', action: '删除' })) return
  try { await api(`/admin/tokens/${token.id}`, { method: 'DELETE' }); await load(); notify('令牌已删除') } catch (error) { fail(error) }
}
function reveal(id: string) { if (!revealed.value.delete(id)) revealed.value.add(id) }
async function copy(text: string, label: string) {
  try { await copyText(text); notify(`已复制${label}`) } catch (error) { fail(error) }
}
const mask = (secret: string) => `${secret.slice(0, 4)}••••••••••••${secret.slice(-4)}`
const time = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '从未使用'
const claudeCommand = (token: McpToken) => `claude mcp add --transport http compfinder ${endpoint} --header "Authorization: Bearer ${token.secret}"`
const jsonConfig = (token: McpToken) => JSON.stringify({ mcpServers: { compfinder: { url: endpoint, headers: { Authorization: `Bearer ${token.secret}` } } } }, null, 2)
onMounted(load)
</script>
<template>
  <section class="page-head"><div><h1>AI 接入</h1><p>为 AI 客户端创建 MCP 令牌，每个令牌单独限定可用的工具。网页登录令牌不能用于 MCP。</p></div><button class="button primary" :disabled="loading || !!problem" @click="create"><Icon name="plus" :size="17" />新建令牌</button></section>
  <div class="panel endpoint-panel"><div><span class="eyebrow">MCP 地址</span><code>{{ endpoint }}</code></div><button class="button small" @click="copy(endpoint, ' MCP 地址')"><Icon name="copy" :size="15" />复制</button></div>
  <p v-if="!secure" class="info-banner">当前不是 HTTPS 连接，令牌会以明文传输。公网使用前请按 README 配置 HTTPS。</p>
  <div v-if="loading" class="token-list"><div v-for="n in 2" :key="n" class="panel skeleton-token" /></div>
  <div v-else-if="problem" class="empty-state"><h3>{{ problem }}</h3><button class="button" @click="load">重新加载</button></div>
  <div v-else-if="items.length" class="token-list">
    <article v-for="token in items" :key="token.id" class="panel token-card" :class="{ disabled: !token.enabled }">
      <header class="token-head"><div><h3>{{ token.name }}</h3><p class="muted">创建于 {{ time(token.createdAt) }} · 最近使用 {{ time(token.lastUsedAt) }}</p></div><span class="badge" :class="token.enabled ? 'ready' : 'draft'">{{ token.enabled ? '启用中' : '已停用' }}</span></header>
      <div class="token-secret"><code>{{ revealed.has(token.id) ? token.secret : mask(token.secret) }}</code><button class="icon-button" :aria-label="revealed.has(token.id) ? '隐藏令牌' : '显示令牌'" :title="revealed.has(token.id) ? '隐藏令牌' : '显示令牌'" @click="reveal(token.id)"><Icon name="eye" :size="17" /></button><button class="icon-button" aria-label="复制令牌" title="复制令牌" @click="copy(token.secret, '令牌')"><Icon name="copy" :size="17" /></button></div>
      <div class="token-tools" aria-label="可用工具"><span v-for="name in token.tools" :key="name" class="badge" :class="{ draft: writes.has(name) }" :title="name">{{ titles.get(name) || name }}</span></div>
      <footer class="token-actions"><button class="button small" @click="copy(claudeCommand(token), ' Claude Code 命令')"><Icon name="copy" :size="15" />Claude Code 命令</button><button class="button small" @click="copy(jsonConfig(token), ' JSON 配置')"><Icon name="copy" :size="15" />JSON 配置</button><span class="spacer" /><button class="button small ghost" @click="toggle(token)">{{ token.enabled ? '停用' : '启用' }}</button><button class="button small" @click="edit(token)"><Icon name="edit" :size="15" />编辑</button><button class="button small danger-quiet" @click="remove(token)"><Icon name="trash" :size="15" />删除</button></footer>
    </article>
  </div>
  <div v-else class="empty-state boxed"><span class="empty-art"><Icon name="key" :size="40" /></span><h3>还没有 MCP 令牌</h3><p>新建一个令牌，把它和 MCP 地址填进 Claude Code、Cursor 等 AI 客户端，AI 就能以图搜图和建档。</p><button class="button primary" @click="create"><Icon name="plus" :size="17" />新建令牌</button></div>
  <Modal v-if="draft" :title="draft.id ? '编辑令牌' : '新建令牌'" :busy="saving" wide @close="draft = null">
    <form @submit.prevent="save">
      <label class="field-label">名称<input v-model="draft.name" maxlength="60" placeholder="例如：Claude Code 建档" required /></label>
      <div class="field-label"><label for="token-secret">令牌</label><div class="secret-field"><input id="token-secret" v-model="draft.secret" maxlength="200" :placeholder="draft.id ? '' : '留空则自动生成'" spellcheck="false" autocomplete="off" /><button type="button" class="button" @click="generate">随机生成</button></div></div>
      <p v-if="secretChanged" class="field-warning">保存后旧令牌立即失效，使用它的 AI 客户端需要换成新令牌。</p>
      <fieldset class="tool-picker"><legend>可用工具（已选 {{ draft.tools.length }} / {{ tools.length }}）</legend>
        <div class="tool-presets"><button v-for="preset in presets" :key="preset.label" type="button" class="button small" @click="applyPreset(preset.tools)">{{ preset.label }}</button></div>
        <div v-for="entry in groups" :key="entry.group" class="tool-group"><h4>{{ entry.group }}</h4>
          <label v-for="tool in entry.tools" :key="tool.name" class="tool-option"><input v-model="draft.tools" type="checkbox" :value="tool.name" /><span><strong>{{ tool.title }} <code>{{ tool.name }}</code></strong><small>{{ tool.description }}</small></span></label>
        </div>
      </fieldset>
      <footer class="modal-actions"><button type="button" class="button" :disabled="saving" @click="draft = null">取消</button><button class="button primary" :disabled="saving || !draft.name.trim() || !draft.tools.length">{{ saving ? '正在保存…' : '保存' }}</button></footer>
    </form>
  </Modal>
</template>
