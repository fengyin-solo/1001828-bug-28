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
        <input type="checkbox" :checked="allSelected" :indeterminate.prop="someSelected" @change="toggleAll" />
        全选本页
      </label>
      <span class="batch-tip">已选 {{ selectedIds.length }} 条，同一阀门井室只执行一次</span>
      <button
        v-for="action in actions"
        :key="action"
        class="btn"
        type="button"
        :disabled="!selectedIds.length || batchLoading"
        @click="runBatch(action)"
      >
        批量{{ action }}
      </button>
      <span v-if="batchSummary" class="batch-summary" :class="{ ok: batchOk, fail: !batchOk }">{{ batchSummary }}</span>
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
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'row-failed': rowLast(row)?.ok === false }">
          <td class="col-check">
            <input type="checkbox" :checked="isSelected(Number(row.id))" @change="toggleOne(Number(row.id))" />
          </td>
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              :disabled="rowLoading[Number(row.id)] === action"
              @click="runAction(action, row)"
            >
              {{ rowLoading[Number(row.id)] === action ? '执行中…' : action }}
            </button>
          </td>
          <td class="col-result">
            <template v-if="rowLoading[Number(row.id)]">
              <span class="state-running">执行中…</span>
            </template>
            <template v-else-if="rowLast(row)">
              <div :class="lastOf(row).ok ? 'state-ok' : 'state-fail'">
                <span>{{ lastOf(row).message }}</span>
                <span v-if="lastOf(row).last_time" class="state-time">{{ lastOf(row).last_time }}</span>
              </div>
              <button
                v-if="!lastOf(row).ok && lastOf(row).last_action"
                class="link retry-link"
                type="button"
                @click="runAction(lastOf(row).last_action as string, row)"
              >
                重试「{{ lastOf(row).last_action }}」
              </button>
            </template>
            <span v-else class="state-empty">—</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 3" class="empty-state">暂无阀门井室数据，可先登记阀门</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条阀门井室记录，待确认 {{ stats[2]?.value ?? 0 }} 条（与运营概览同口径）</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>

type RowResult = {
  ok: boolean
  message: string
  last_action?: string
  last_time?: string
}

type BatchItem = { id: number; ok: boolean; message: string; entry: Row | null }
type BatchPayload = {
  ok: boolean
  action: string
  total: number
  success_count: number
  failure_count: number
  message: string
  items: BatchItem[]
}

const ENDPOINT = '/api/valve'
const columns = ["阀门编号", "阀门类别", "所在管段", "公称直径", "操作方向", "上次启闭日", "责任人员", "阀门状态"]
const actions = ["安排启闭", "确认正常", "停用阀门"]

const stats = ref<{ label: string; value: number }[]>([
  { label: '在册阀门', value: 0 },
  { label: '异常阀门', value: 0 },
  { label: '待确认阀门', value: 0 },
])
const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const selected = ref<Set<number>>(new Set())
const rowLoading = reactive<Record<number, string>>({})
const batchLoading = ref(false)
const batchSummary = ref('')
const batchOk = ref(true)
// 行内最近结果：优先用本次会话返回的，刷新后由服务端 last_* 字段兜底
const localResults = reactive<Record<number, RowResult>>({})

const selectedIds = computed(() => Array.from(selected.value).sort((a, b) => a - b))
const allSelected = computed(() => rows.value.length > 0 && rows.value.every((row) => selected.value.has(Number(row.id))))
const someSelected = computed(() => !allSelected.value && rows.value.some((row) => selected.value.has(Number(row.id))))

function rowLast(row: Row): RowResult | null {
  const id = Number(row.id)
  if (localResults[id]) return localResults[id]
  if (typeof row.last_message === 'string') {
    return {
      ok: Boolean(row.last_ok),
      message: row.last_message,
      last_action: typeof row.last_action === 'string' ? row.last_action : undefined,
      last_time: typeof row.last_time === 'string' ? row.last_time : undefined,
    }
  }
  return null
}

// 模板里 v-if 已保证非空，供 v-else-if 分支直接取字段
function lastOf(row: Row): RowResult {
  return rowLast(row) as RowResult
}

function isSelected(id: number | string) {
  return selected.value.has(Number(id))
}

function toggleOne(id: number | string) {
  const numericId = Number(id)
  if (selected.value.has(numericId)) selected.value.delete(numericId)
  else selected.value.add(numericId)
  selected.value = new Set(selected.value)
}

function toggleAll(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  selected.value = new Set(checked ? rows.value.map((row) => Number(row.id)) : [])
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

async function postAction(action: string, row: Row): Promise<boolean> {
  const id = Number(row.id)
  rowLoading[id] = action
  try {
    const response = await request(`${ENDPOINT}/${id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      const detail = await readErrorDetail(response)
      throw new Error(detail)
    }
    const payload = await response.json()
    localResults[id] = {
      ok: Boolean(payload.ok),
      message: payload.message ?? '动作未生效',
      last_action: action,
    }
    return Boolean(payload.ok)
  } catch (error) {
    localResults[id] = {
      ok: false,
      message: error instanceof Error ? error.message : '阀门井室操作失败',
      last_action: action,
    }
    return false
  } finally {
    delete rowLoading[id]
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  await postAction(action, row)
  await reload({ preserveResults: true })
}

async function runBatch(action: string) {
  const ids = selectedIds.value
  if (!ids.length || batchLoading.value) return
  errorMessage.value = ''
  batchLoading.value = true
  try {
    const response = await request(`${ENDPOINT}/batch-actions`, {
      method: 'POST',
      body: JSON.stringify({ action, entry_ids: ids }),
    })
    if (!response.ok) {
      const detail = await readErrorDetail(response)
      throw new Error(detail)
    }
    const payload = (await response.json()) as BatchPayload
    for (const item of payload.items) {
      localResults[item.id] = {
        ok: item.ok,
        message: item.message,
        last_action: action,
        last_time: item.entry?.last_time as string | undefined,
      }
    }
    batchSummary.value = payload.message
    batchOk.value = payload.ok
    // 只清掉本次成功的勾选，失败的保留，方便直接再次批量重试
    const failedIds = new Set(payload.items.filter((item) => !item.ok).map((item) => item.id))
    selected.value = new Set(ids.filter((id) => failedIds.has(id)))
    await reload({ preserveResults: true })
  } catch (error) {
    batchSummary.value = ''
    batchOk.value = false
    errorMessage.value = error instanceof Error ? error.message : '批量操作未送达，请重试'
  } finally {
    batchLoading.value = false
  }
}

async function readErrorDetail(response: Response): Promise<string> {
  try {
    const data = await response.json()
    if (typeof data?.detail === 'string') return data.detail
    if (typeof data?.message === 'string') return data.message
  } catch {
    // 非 JSON 错误响应时退回状态码说明
  }
  return `接口返回 ${response.status}，动作未生效，请重试`
}

async function reload(options: { preserveResults?: boolean } = {}) {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const [listResponse, statsResponse] = await Promise.all([
      request(`${ENDPOINT}?${query}`),
      request(`${ENDPOINT}/stats`),
    ])
    if (!listResponse.ok) throw new Error('阀门列表读取失败')
    if (!statsResponse.ok) throw new Error('阀门统计读取失败')
    const payload = await listResponse.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    const statPayload = await statsResponse.json()
    stats.value = [
      { label: '在册阀门', value: statPayload.total ?? 0 },
      { label: '启闭卡涩', value: statPayload.abnormal ?? 0 },
      { label: '待确认阀门', value: statPayload.pending ?? 0 },
    ]
    if (!options.preserveResults) {
      for (const key of Object.keys(localResults)) delete localResults[Number(key)]
    }
    // 翻页/筛选后清掉不在当前页的勾选
    const visibleIds = new Set(rows.value.map((row) => Number(row.id)))
    selected.value = new Set([...selected.value].filter((id) => visibleIds.has(id)))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '阀门井室列表读取失败'
  }
}

onMounted(() => reload())
</script>
