// 统一 API 封装：统一包裹解包 + mock 开关（开发规范 §5）+ 登录态注入（T54）
// VITE_USE_MOCK=true 时读 src/mocks.js 的夹具，联调时删掉开关即可，组件零改动
import { mockFor } from './mocks'

const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true'
const TOKEN_KEY = 'rm_token'

export const getToken = () => localStorage.getItem(TOKEN_KEY)
export const setToken = (t) => localStorage.setItem(TOKEN_KEY, t)
export const clearToken = () => localStorage.removeItem(TOKEN_KEY)

async function request(path, options = {}) {
  if (USE_MOCK) return mockFor(path, options)
  // T54：登录态统一注入——全部请求带 Authorization；401 一律清凭证回登录页
  // （/auth/login 自己的 401 是业务失败「用户名或密码错误」，不触发清登）
  const headers = { ...(options.headers || {}) }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  // C8 挑刺修复：裸 fetch 无超时，后端挂起时页面永远转圈——默认 30s 强制中断并报错
  const timeoutMs = options.timeoutMs ?? 30000
  let res
  try {
    res = await fetch(`/api${path}`, { ...options, headers, signal: AbortSignal.timeout(timeoutMs) })
  } catch (e) {
    if (e?.name === 'TimeoutError') throw new Error(`请求超时（${Math.round(timeoutMs / 1000)} 秒），请检查后端服务后重试`)
    throw e
  }
  if (res.status === 401 && !path.startsWith('/auth/login')) {
    clearToken()
    location.reload()
    throw new Error('登录已过期，请重新登录')
  }
  const body = await res.json().catch(() => ({}))
  if (!res.ok || body.code !== 0) {
    throw new Error(body.message || `HTTP ${res.status}`)
  }
  return body.data
}

function jsonInit(method, data) {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }
}

// ---------- 认证（T54） ----------
export const login = (username, password) =>
  request('/auth/login', jsonInit('POST', { username, password }))
export const logout = () => request('/auth/logout', { method: 'POST' })
export const getMe = () => request('/auth/me')

// ---------- 简历 ----------
export const uploadResume = (file) => {
  if (USE_MOCK) return mockFor('/resumes/upload', { method: 'POST' })
  const form = new FormData()
  form.append('file', file)
  return request('/resumes/upload', { method: 'POST', body: form })
}
export const listResumes = (page = 1, pageSize = 20, corpus = 'all') =>
  request(`/resumes?page=${page}&page_size=${pageSize}&corpus=${corpus}`)
// reveal=1 显示未打码原文，后端记审计（T54）
export const getResume = (id, reveal = false) =>
  request(`/resumes/${id}${reveal ? '?reveal=1' : ''}`)
export const deleteResume = (id) => request(`/resumes/${id}`, { method: 'DELETE' })
// 简历原件（T54）：window.open 带不了 Authorization 头，统一 fetch blob 中转新标签打开
export async function openResumeFile(id) {
  if (USE_MOCK) { window.open('about:blank', '_blank'); return }
  const headers = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const res = await fetch(`/api/resumes/${id}/file`, { headers })
  if (res.status === 401) { clearToken(); location.reload(); throw new Error('登录已过期，请重新登录') }
  if (!res.ok) throw new Error(`原件打开失败 HTTP ${res.status}`)
  const url = URL.createObjectURL(await res.blob())
  window.open(url, '_blank')
  setTimeout(() => URL.revokeObjectURL(url), 60000) // 一分钟后回收，给新标签加载留足时间
}
// 全文搜索 / 重解析 / 解析数据视图（T29）
export const searchResumes = (q, limit = 20) =>
  request(`/resumes/search?q=${encodeURIComponent(q)}&limit=${limit}`)
export const reparseResume = (id) => request(`/resumes/${id}/reparse`, { method: 'POST' })
export const getResumeData = (id, reveal = false) =>
  request(`/resumes/${id}/data${reveal ? '?reveal=1' : ''}`)
// 反向推荐（API-17，T39）：这份简历最适合哪些岗位（Top-K JD，校准融合分）
export const getJdRecommendations = (id, topK = 3) =>
  request(`/resumes/${id}/jd_recommendations?top_k=${topK}`)
// 风控体检（API-22，T55）：四类矛盾点检测，提示人工复核，不构成造假判定
export const getResumeRisk = (id) => request(`/resumes/${id}/risk`)

// ---------- JD ----------
export const createJd = (title, content) => request('/jds', jsonInit('POST', { title, content }))
export const listJds = (page = 1, pageSize = 20) =>
  request(`/jds?page=${page}&page_size=${pageSize}`)
export const getJd = (id) => request(`/jds/${id}`)
export const deleteJd = (id) => request(`/jds/${id}`, { method: 'DELETE' })

// ---------- 匹配 ----------
export const createMatchTask = (jdId, topK = 10) =>
  request('/match-tasks', jsonInit('POST', { jd_id: jdId, top_k: topK }))
// 历史任务列表（A4 挑刺修复）：结果按 task_id 完整存档，界面从此有入口再打开
export const listMatchTasks = (page = 1, pageSize = 10) =>
  request(`/match-tasks?page=${page}&page_size=${pageSize}`)
export const getMatchTask = (id) => request(`/match-tasks/${id}`)
export const getMatchResults = (id) => request(`/match-tasks/${id}/results`)
// 全量融合分分布（API-18，T40）：分布图数据源，历史任务返回空列表
export const getMatchScoreDistribution = (id) =>
  request(`/match-tasks/${id}/score_distribution`)

// ---------- 主页 ----------
// 主页总览（API-19，T48）：库规模 + 两类排名，口径说明见 docs/backend-api.md §6
export const getHomeStats = () => request('/stats/home')

// ---------- 模型 ----------
export const getModelInfo = () => request('/model/info')
