// 统一 API 封装：统一包裹解包 + mock 开关（开发规范 §5）
// VITE_USE_MOCK=true 时读 src/mocks.js 的夹具，联调时删掉开关即可，组件零改动
import { mockFor } from './mocks'

const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true'

async function request(path, options = {}) {
  if (USE_MOCK) return mockFor(path, options)
  const res = await fetch(`/api${path}`, options)
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

// ---------- 简历 ----------
export const uploadResume = (file) => {
  if (USE_MOCK) return mockFor('/resumes/upload', { method: 'POST' })
  const form = new FormData()
  form.append('file', file)
  return request('/resumes/upload', { method: 'POST', body: form })
}
export const listResumes = (page = 1, pageSize = 20, corpus = 'all') =>
  request(`/resumes?page=${page}&page_size=${pageSize}&corpus=${corpus}`)
export const getResume = (id) => request(`/resumes/${id}`)
export const deleteResume = (id) => request(`/resumes/${id}`, { method: 'DELETE' })
// 简历原件地址（浏览器直接打开：PDF 预览 / DOCX 下载）
export const resumeFileUrl = (id) => `/api/resumes/${id}/file`
// 全文搜索 / 重解析 / 解析数据视图（T29）
export const searchResumes = (q, limit = 20) =>
  request(`/resumes/search?q=${encodeURIComponent(q)}&limit=${limit}`)
export const reparseResume = (id) => request(`/resumes/${id}/reparse`, { method: 'POST' })
export const getResumeData = (id) => request(`/resumes/${id}/data`)
// 反向推荐（API-17，T39）：这份简历最适合哪些岗位（Top-K JD，校准融合分）
export const getJdRecommendations = (id, topK = 3) =>
  request(`/resumes/${id}/jd_recommendations?top_k=${topK}`)

// ---------- JD ----------
export const createJd = (title, content) => request('/jds', jsonInit('POST', { title, content }))
export const listJds = (page = 1, pageSize = 20) =>
  request(`/jds?page=${page}&page_size=${pageSize}`)
export const getJd = (id) => request(`/jds/${id}`)
export const deleteJd = (id) => request(`/jds/${id}`, { method: 'DELETE' })

// ---------- 匹配 ----------
export const createMatchTask = (jdId, topK = 10) =>
  request('/match-tasks', jsonInit('POST', { jd_id: jdId, top_k: topK }))
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
