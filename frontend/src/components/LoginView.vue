<script setup lang="ts">
import { ref } from 'vue'
import { api, json } from '../api'
import Icon from './Icon.vue'
const token = ref('')
const busy = ref(false)
const error = ref('')
async function login() {
  busy.value = true; error.value = ''
  // A full reload starts every view fresh with the new session cookie.
  try { await api('/auth/login', json('POST', { token: token.value.trim() })); location.reload() }
  catch (problem) { error.value = problem instanceof Error ? problem.message : '登录失败，请重试' }
  finally { busy.value = false }
}
</script>
<template>
  <main class="login-page">
    <form class="panel login-card" @submit.prevent="login">
      <span class="brand-mark"><Icon name="lock" :size="18" /></span>
      <h1>CompFinder</h1>
      <p class="muted">请输入访问令牌。令牌在服务器的 data/access-token.txt 中，启动窗口也会显示。</p>
      <label class="field-label">访问令牌<input v-model="token" type="password" autocomplete="current-password" required autofocus /></label>
      <p v-if="error" class="login-error" role="alert">{{ error }}</p>
      <button class="button primary" :disabled="busy || !token.trim()">{{ busy ? '正在验证…' : '进入' }}</button>
    </form>
  </main>
</template>
