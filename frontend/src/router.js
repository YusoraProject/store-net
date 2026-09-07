import Vue from 'vue'
import VueRouter from 'vue-router'
const Login = () => import('./views/Login.vue')
const Register = () => import('./views/Register.vue')
const Dashboard = () => import('./views/Dashboard.vue')
Vue.use(VueRouter)
const router = new VueRouter({
  mode: 'history',
  routes: [
    { path: '/login', name: 'login', component: Login, meta: { public: true } },
    {
      path: '/register',
      name: 'register',
      component: Register,
      meta: { public: true },
    },
    { path: '/', name: 'dashboard', component: Dashboard },
  ],
})
router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('store_net_token')
  if (!to.meta.public && !token) next({ name: 'login' })
  else if (to.meta.public && token) next({ name: 'dashboard' })
  else next()
})
export default router
