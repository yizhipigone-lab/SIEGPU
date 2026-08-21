import axios from 'axios'

export const http = axios.create({ baseURL: '/api' })

http.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// W8：不在拦截器里脱壳——保留 AxiosResponse 类型，调用方 .data 取数，类型不再"说谎"
http.interceptors.response.use(
  (response) => {
    // 滑动续期：后端在令牌剩余有效期过半时下发新令牌，静默替换
    const newToken = response.headers['x-token-refresh']
    if (newToken) localStorage.setItem('token', newToken)
    return response
  },
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      // 组件外无法直接用 naive-ui message，改用 query 参数由登录页提示
      if (location.pathname !== '/login') location.href = '/login?expired=1'
    }
    return Promise.reject(err)
  }
)

export const api = http
