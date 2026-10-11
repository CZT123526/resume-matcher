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
export const listResumes = (page = 1, pageSize = 100) =>
  request(`/resumes?page=${page}&page_size=${pageSize}`)
export const getResume = (id) => request(`/resumes/${id}`)
export const deleteResume = (id) => request(`/resumes/${id}`, { method: 'DELETE' })
// 简历原件地址（浏览器直接打开：PDF 预览 / DOCX 下载）
export const resumeFileUrl = (id) => `/api/resumes/${id}/file`

// ---------- JD ----------
export const createJd = (title, content) => request('/jds', jsonInit('POST', { title, content }))
export const listJds = (page = 1, pageSize = 100) =>
  request(`/jds?page=${page}&page_size=${pageSize}`)
export const getJd = (id) => request(`/jds/${id}`)

// ---------- 匹配 ----------
export const createMatchTask = (jdId, topK = 10) =>
  request('/match-tasks', jsonInit('POST', { jd_id: jdId, top_k: topK }))
export const getMatchTask = (id) => request(`/match-tasks/${id}`)
export const getMatchResults = (id) => request(`/match-tasks/${id}/results`)

// ---------- 模型 ----------
export const getModelInfo = () => request('/model/info')
