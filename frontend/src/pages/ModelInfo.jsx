import { useEffect, useState } from 'react'
import { getModelInfo } from '../api'

export default function ModelInfo() {
  const [info, setInfo] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    getModelInfo().then(setInfo).catch((e) => setErr(e.message))
  }, [])

  if (err) return <div className="card error-text">加载失败：{err}</div>
  if (!info) return <div className="card muted">加载中…</div>

  return (
    <div className="card">
      <h3>模型状态</h3>
      <table>
        <tbody>
          <tr><td>模型</td><td>{info.model_name}</td></tr>
          <tr><td>版本</td><td>{info.version}</td></tr>
          <tr>
            <td>实体级 F1</td>
            <td>{info.f1 > 0 ? `${(info.f1 * 100).toFixed(1)}%` : '未微调（训练完成后自动展示）'}</td>
          </tr>
          <tr><td>训练样本数</td><td>{info.train_samples || '—'}</td></tr>
          <tr><td>更新时间</td><td>{info.updated_at || '—'}</td></tr>
        </tbody>
      </table>
      <p className="muted" style={{ marginBottom: 0 }}>
        说明：微调模型未就位时，实体抽取走规则兜底（source=rule），语义匹配仍可用；
        Colab 训练产物放入 backend/models/ner/ 后自动切换为 BERT 推理，无需改代码。
      </p>
    </div>
  )
}
