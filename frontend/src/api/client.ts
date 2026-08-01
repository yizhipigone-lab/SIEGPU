import axios from 'axios'

export const http = axios.create({ baseURL: '/api' })

http.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// W8：不在拦截器里脱壳——保留 AxiosResponse 类型，调用方 .data 取数，类型不再"说谎"
http.interceptors.response.use(
  (response) => response,
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
