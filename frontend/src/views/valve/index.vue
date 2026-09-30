<template>
  <section class="page" data-module="valve">
    <header class="page-head">
      <div>
        <h2>阀门井室管理</h2>
        <p class="page-desc">维护阀门，围绕阀门编号、阀门类别、所在管段、公称直径做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记阀门</button>
        <button class="btn" type="button" @click="exportRows">导出阀门井室清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="() => reload()">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div class="batch-bar">
      <label class="select-all">
        <input v-model="selectAll" type="checkbox" @change="toggleSelectAll" />
        全选本页（已选 {{ selectedIds.length }} 条）
      </label>
      <select v-model="batchAction" class="batch-select">
        <option v-for="action in actions" :key="action" :value="action">{{ action }}</option>
      </select>
      <button class="btn primary" type="button" :disabled="batchLoading || !selectedIds.length" @click="runBatch(batchAction)">
        {{ batchLoading ? '执行中…' : `批量${batchAction}` }}
      </button>
      <button
        v-if="lastBatch && lastBatch.failedIds.length"
        class="btn"
        type="button"
        :disabled="batchLoading"
        @click="retryFailed"
      >
        重试失败项（{{ lastBatch.failedIds.length }}）
      </button>
    </div>

    <div v-if="batchSummary" class="batch-summary" :class="batchSummary.ok ? 'ok' : 'warn'">
      {{ batchSummary.message }}
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th class="col-check">选择</th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
          <th>最近操作结果</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'row-failed': feedbackOf(row)?.ok === false }">
          <td class="col-check">
            <input v-model="selectedIds" type="checkbox" :value="Number(row.id)" />
          </td>
          <td v-for="column in columns" :key="column">
            <template v-if="column === '阀门状态'">
              <span :class="['status-tag', statusClass(row.status)]">{{ row[column] ?? '—' }}</span>
              <em v-if="row.pending" class="pending-mark">待确认</em>
            </template>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actionsFor(row.status)"
              :key="action"
              class="link"
              type="button"
              :disabled="rowLoading[Number(row.id)] === action"
              @click="runAction(action, row)"
            >
              {{ rowLoading[Number(row.id)] === action ? '提交中…' : action }}
            </button>
          </td>
          <td>
            <p v-if="feedbackOf(row)" class="line-result" :class="feedbackOf(row)?.ok ? 'ok' : 'error-text'">
              {{ feedbackOf(row)?.message }}
            </p>
            <button
              v-if="feedbackOf(row)?.ok === false"
              class="link retry-link"
              type="button"
              @click="runAction(feedbackOf(row)?.action ?? '', row)"
            >
              重试
            </button>
            <span v-else-if="!feedbackOf(row)">—</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 3" class="empty-state">暂无阀门井室数据，可先登记阀门</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条阀门井室记录，待确认数与运营概览一致</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>
type Feedback = { ok: boolean; message: string; action: string }

const ENDPOINT = '/api/valve'
const columns = ["阀门编号", "阀门类别", "所在管段", "公称直径", "操作方向", "上次启闭日", "责任人员", "阀门状态"]
const actions = ["安排启闭", "确认正常", "确认卡涩", "停用阀门"] as const
const statuses = ["待启闭", "操作正常", "启闭卡涩", "已停用"]

// 每个状态下还能执行的动作；非法流转交给后端拦截并返回逐条原因。
const ACTIONS_BY_STATUS: Record<string, string[]> = {
  '待启闭': ['安排启闭', '确认正常', '确认卡涩', '停用阀门'],
  '启闭卡涩': ['确认正常', '停用阀门'],
  '操作正常': ['停用阀门'],
  '已停用': [],
}

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref([
  { label: '在册阀门', value: 0 },
  { label: '启闭卡涩', value: 0 },
  { label: '待确认阀门', value: 0 },
])
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const selectedIds = ref<number[]>([])
const batchAction = ref<string>('确认正常')
const batchLoading = ref(false)
const selectAll = ref(false)
const rowLoading = ref<Record<number, string>>({})
const rowFeedback = ref<Record<number, Feedback>>({})
const lastBatch = ref<{ action: string; failedIds: number[] } | null>(null)
const batchSummary = ref<{ ok: boolean; message: string } | null>(null)

function feedbackOf(row: Row): Feedback | undefined {
  return rowFeedback.value[Number(row.id)]
}

function actionsFor(status: unknown): string[] {
  return ACTIONS_BY_STATUS[String(status)] ?? []
}

function statusClass(status: unknown) {
  switch (String(status)) {
    case '操作正常':
      return 'status-ok'
    case '启闭卡涩':
      return 'status-abnormal'
    case '已停用':
      return 'status-off'
    default:
      return 'status-pending'
  }
}

function toggleSelectAll() {
  selectedIds.value = selectAll.value ? rows.value.map((row) => Number(row.id)) : []
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '阀门登记入口尚未接入审批流'
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) return
    const payload = (await response.json()) as { total: number; pending: number; abnormal: number }
    stats.value = [
      { label: '在册阀门', value: payload.total },
      { label: '启闭卡涩', value: payload.abnormal },
      { label: '待确认阀门', value: payload.pending },
    ]
  } catch {
    // 统计读取失败不阻塞列表，页脚会保留列表接口自身的错误说明
  }
}

function markFeedback(items: { id: number; ok: boolean; message: string; action?: string }[], action: string) {
  for (const item of items) {
    rowFeedback.value[item.id] = { ok: item.ok, message: item.message, action: item.action ?? action }
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  const id = Number(row.id)
  rowLoading.value[id] = action
  try {
    const response = await request(`${ENDPOINT}/${id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error(`接口返回 ${response.status}，操作未提交，请重试`)
    }
    const payload = (await response.json()) as { ok: boolean; message: string }
    // 业务失败也是 HTTP 200：必须按 ok 判断，并把后端给出的原因显示出来
    markFeedback([{ id, ok: payload.ok, message: payload.message }], action)
    await reload()
  } catch (error) {
    markFeedback(
      [{ id, ok: false, message: error instanceof Error ? error.message : '阀门井室操作失败，请重试' }],
      action,
    )
  } finally {
    delete rowLoading.value[id]
  }
}

async function runBatch(action: string, ids = selectedIds.value as number[]) {
  errorMessage.value = ''
  if (!ids.length) {
    errorMessage.value = '请先勾选要处理的阀门'
    return
  }
  batchLoading.value = true
  try {
    const response = await request(`${ENDPOINT}/batch-actions`, {
      method: 'POST',
      body: JSON.stringify({ action, ids }),
    })
    if (!response.ok) {
      throw new Error(`接口返回 ${response.status}，本批操作未提交，请重试`)
    }
    const payload = (await response.json()) as {
      ok: boolean
      message: string
      results: { id: number; ok: boolean; message: string }[]
    }
    markFeedback(payload.results, action)
    const failedIds = payload.results.filter((item) => !item.ok).map((item) => item.id)
    lastBatch.value = { action, failedIds }
    batchSummary.value = { ok: payload.ok, message: payload.message }
    // 成功的记录已经落库；刷新列表即可看到当前进度，失败项保持勾选方便重试
    await reload({ keepSelection: true })
    // 刷新后默认只勾选失败项，引导用户重试；没有失败则清空选择
    selectedIds.value = failedIds
    selectAll.value = false
  } catch (error) {
    batchSummary.value = {
      ok: false,
      message: error instanceof Error ? error.message : '批量操作请求失败，请重试',
    }
  } finally {
    batchLoading.value = false
  }
}

async function retryFailed() {
  if (!lastBatch.value) return
  const failedIds = [...lastBatch.value.failedIds]
  await runBatch(lastBatch.value.action, failedIds)
}

async function reload(options: { keepSelection?: boolean } = {}) {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('阀门列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    // 重新进入页面/刷新后，勾选状态以服务端最新数据为准
    if (!options.keepSelection) selectedIds.value = []
    selectAll.value = false
    await loadStats()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '阀门井室列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.batch-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 12px;
  margin-bottom: 10px;
  font-size: 13px;
}
.select-all { display: flex; align-items: center; gap: 6px; color: var(--muted); }
.batch-select { padding: 5px 8px; border: 1px solid var(--border); border-radius: 6px; }
.col-check { width: 42px; text-align: center; }
.col-check input { margin: 0; }
.batch-summary { border-radius: 6px; padding: 8px 12px; margin-bottom: 10px; font-size: 13px; }
.batch-summary.ok { background: #ecfdf3; border: 1px solid #75e0a7; color: #027a48; }
.batch-summary.warn { background: #fffaeb; border: 1px solid #fedf89; color: #b54708; }
.status-tag { padding: 1px 8px; border-radius: 10px; font-size: 12px; white-space: nowrap; }
.status-pending { background: #eff4ff; color: #1d4ed8; }
.status-ok { background: #ecfdf3; color: #027a48; }
.status-abnormal { background: #fef3f2; color: #b42318; }
.status-off { background: #f2f4f7; color: #475467; }
.pending-mark { color: #b42318; font-style: normal; font-size: 12px; margin-left: 6px; }
.line-result { margin: 0; max-width: 240px; word-break: break-all; }
.retry-link { margin-top: 2px; }
.row-failed { background: #fff8f7; }
.btn:disabled { opacity: 0.55; cursor: not-allowed; }
.link:disabled { opacity: 0.6; cursor: default; }
</style>
