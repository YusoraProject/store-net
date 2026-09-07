import Vue from 'vue'
import axios from 'axios'
import App from './App.vue'
import './chipsnet.css'
import router from './router'

const api = axios.create({ baseURL: process.env.VUE_APP_API_URL || '/api/v1' })
api.interceptors.request.use((config) => {
  // 浏览器只携带登录凭证，角色和门店范围由后端判断。
  const token = localStorage.getItem('store_net_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})
api.interceptors.response.use(
  (x) => x,
  (error) => {
    if (error.response && error.response.status === 401) {
      localStorage.removeItem('store_net_token')
      if (router.currentRoute.name !== 'login')
        router.replace({ name: 'login' })
    }
    return Promise.reject(error)
  }
)
Vue.prototype.$api = api
Vue.config.productionTip = false
new Vue({ router, render: (h) => h(App) }).$mount('#app')
