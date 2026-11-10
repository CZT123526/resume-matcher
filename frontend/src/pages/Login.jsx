// 登录页（T54）：全站唯一入口，凭证校验由后端完成，token 存 localStorage 由 api.js 统一注入。
// 样式零新组件库：居中 .card 复用设计令牌，错误提示走 .error-text。
import { useState } from 'react'
import { login, setToken } from '../api'

export default function Login({ onLogin }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    if (!username.trim() || !password) { setErr('请输入用户名和密码'); return }
    setBusy(true)
    setErr('')
    try {
      const data = await login(username.trim(), password)
      setToken(data.token)
      onLogin(data)
    } catch (e2) {
      setErr(e2.message || '登录失败，请重试')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-wrap">
      <form className="card login-card" onSubmit={submit}>
        <div className="brand" style={{ marginBottom: 20 }}>
          <span className="brand-mark">简</span>
          <div className="brand-text"><h1>简历解析与人才推荐</h1></div>
        </div>
        <div className="field-label">用户名</div>
        <input
          value={username} onChange={(e) => setUsername(e.target.value)}
          placeholder="请输入用户名" autoFocus autoComplete="username"
        />
        <div className="field-label">密码</div>
        <input
          type="password" value={password} onChange={(e) => setPassword(e.target.value)}
          placeholder="请输入密码" autoComplete="current-password"
        />
        {err && <div className="error-text" style={{ marginTop: 10 }}>{err}</div>}
        <button className="btn" type="submit" disabled={busy} style={{ width: '100%', marginTop: 18 }}>
          {busy ? '登录中…' : '登录'}
        </button>
        <div className="muted" style={{ marginTop: 16, fontSize: 12, textAlign: 'center' }}>
          简历数据含个人联系方式，仅限授权人员登录查看，全程留痕
        </div>
      </form>
    </div>
  )
}
