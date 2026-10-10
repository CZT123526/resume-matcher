// mock 夹具：字段与 docs/api-schemas.md 完全一致（后端没好时前端不等待）
// 联调真实后端：.env.development 里 VITE_USE_MOCK=false 或删掉此文件引用即可

const delay = (ms = 300) => new Promise((r) => setTimeout(r, ms))

let resumeSeq = 3
let taskSeq = 100

const fixtures = {
  'POST /resumes/upload': async () => {
    await delay()
    return { resume_id: ++resumeSeq, file_name: '示例简历.pdf', parse_status: 'pending' }
  },
  'GET /resumes': async () => ({
    total: 3,
    items: [
      { resume_id: 1, file_name: '张三.pdf', parse_status: 'done', created_at: '2026-10-10T09:00:00' },
      { resume_id: 2, file_name: '李四.docx', parse_status: 'done', created_at: '2026-10-10T10:00:00' },
      { resume_id: 3, file_name: '王五.pdf', parse_status: 'processing', created_at: '2026-10-10T11:00:00' },
    ],
  }),
  'GET /resumes/': async (_opt, path) => {
    await delay(200)
    return {
      resume_id: 1,
      file_name: '张三.pdf',
      parse_status: 'done',
      raw_text: '（前500字预览）姓名：张三，硕士，5年工作经验，技能：Python/FastAPI/MySQL……',
      entities: [
        { field_key: 'name', field_value: '张三', source: 'bert' },
        { field_key: 'degree', field_value: '硕士', source: 'bert' },
        { field_key: 'school', field_value: '清华大学', source: 'bert' },
        { field_key: 'skill', field_value: 'python', source: 'bert' },
        { field_key: 'skill', field_value: 'fastapi', source: 'bert' },
        { field_key: 'years', field_value: '5', source: 'bert' },
      ],
      created_at: '2026-10-10T09:00:00',
    }
  },
  'DELETE /resumes/': async () => ({ resume_id: 1, deleted: true }),
  'POST /jds': async () => ({ jd_id: 1, title: 'Python后端工程师' }),
  'GET /jds': async () => ({
    total: 1,
    items: [{ jd_id: 1, title: 'Python后端工程师', created_at: '2026-10-10T09:30:00' }],
  }),
  'GET /jds/': async () => ({
    jd_id: 1,
    title: 'Python后端工程师',
    content: '负责后端服务开发。要求：3年以上Python经验，熟悉FastAPI，本科及以上。',
    req_json: { degree: '本科', min_years: 3, skills: ['python', 'fastapi', 'mysql'] },
    created_at: '2026-10-10T09:30:00',
  }),
  'POST /match-tasks': async () => ({ task_id: ++taskSeq, status: 'pending' }),
  'GET /match-tasks/': async (_opt, path) => ({
    task_id: 100,
    status: 'done',
    progress: 100,
    error: null,
  }),
  'GET /match-tasks/100/results': async () => ({
    task_id: 100,
    jd_title: 'Python后端工程师',
    items: [
      {
        rank: 1, resume_id: 1, candidate_name: '张三', score: 0.8712,
        evidence: ['技能重叠：Python/FastAPI (2/2)', '学历满足：硕士≥本科', '经验满足：5年≥3年'],
      },
      {
        rank: 2, resume_id: 2, candidate_name: '候选人2', score: 0.6235,
        evidence: ['技能重叠：Python (1/2)', '缺少技能：FastAPI', '学历：未识别', '经验满足：3年≥3年'],
      },
    ],
  }),
  'GET /model/info': async () => ({
    model_name: 'bert-base-chinese（语义编码）；NER=规则兜底',
    version: 'v0-rules',
    f1: 0,
    train_samples: 0,
    updated_at: '',
  }),
}

export async function mockFor(path, options = {}) {
  const method = (options.method || 'GET').toUpperCase()
  const key = `${method} ${path}`
  const hit =
    fixtures[key] ||
    Object.entries(fixtures).find(([k]) => key.startsWith(k))
  if (!hit) throw new Error(`mock 未覆盖: ${key}`)
  const fn = hit[1]
  return fn(options, path)
}
