<template>
  <div class="login-shell">
    <div class="login-hero">
      <div class="brand">{{ 'StoreNet' }} 控制台</div>
      <p class="subtitle">创建新账号以访问控制台，完成后即可登录。</p>
      <ul class="bullets">
        <li>· 支持用户名与邮箱登录</li>
        <li>· 头像、昵称均可自定义</li>
      </ul>
    </div>
    <div class="mobile-brand">{{ 'StoreNet' }} 控制台</div>
    <div class="card-shell">
      <el-card class="login-card" shadow="never">
        <div class="card-header">
          <h2>注册新账号</h2>
          <p class="muted">填写信息后自动登录</p>
        </div>
        <el-form
          :model="form"
          @submit.native.prevent="onSubmit"
          label-width="0"
        >
          <el-form-item>
            <el-input
              v-model="form.username"
              placeholder="用户名"
              autocomplete="username"
              prefix-icon="el-icon-user"
            />
          </el-form-item>
          <el-form-item>
            <el-input
              v-model="form.email"
              placeholder="邮箱"
              autocomplete="email"
              prefix-icon="el-icon-message"
            />
          </el-form-item>
          <el-form-item>
            <el-input
              v-model="form.password"
              placeholder="密码"
              type="password"
              autocomplete="new-password"
              prefix-icon="el-icon-lock"
            />
          </el-form-item>
          <el-form-item>
            <el-input
              v-model="form.name"
              placeholder="昵称（可选）"
              prefix-icon="el-icon-edit"
            />
          </el-form-item>
          <el-form-item>
            <el-button
              type="primary"
              :loading="loading"
              style="width: 100%"
              @click="onSubmit"
              >注册并登录</el-button
            >
          </el-form-item>
          <div class="muted" style="text-align: center; margin-top: 4px">
            已有账号？<el-link
              type="primary"
              @click="$router.push({ name: 'login' })"
              >去登录</el-link
            >
          </div>
          <transition name="fade">
            <el-alert
              v-if="error"
              type="error"
              :closable="false"
              :title="error"
              show-icon
              style="margin-top: 12px"
            />
          </transition>
        </el-form>
      </el-card>
      <div class="floating-orb orb-1"></div>
      <div class="floating-orb orb-2"></div>
    </div>
  </div>
</template>

<script>
import '../ui/base'
export default {
  name: 'RegisterView',
  data() {
    return {
      form: {
        username: '',
        email: '',
        password: '',
        name: '',
      },
      loading: false,
      error: '',
    }
  },
  methods: {
    async onSubmit() {
      if (!this.form.username || !this.form.email || !this.form.password) {
        this.error = '请填写用户名、邮箱和密码'
        return
      }
      this.loading = true
      this.error = ''
      try {
        const res = await this.$api.post('/auth/register', this.form)
        localStorage.setItem('store_net_token', res.data.token)
        this.$router.push(this.getPostLoginTarget())
      } catch (err) {
        this.error =
          (err.response && err.response.data && err.response.data.detail) ||
          '注册失败，请稍后重试'
      } finally {
        this.loading = false
      }
    },
    getPostLoginTarget() {
      const redirect =
        this.$route && this.$route.query && this.$route.query.redirect
      if (
        typeof redirect === 'string' &&
        redirect.startsWith('/') &&
        !redirect.startsWith('//')
      ) {
        return redirect
      }
      return { name: 'dashboard' }
    },
  },
}
</script>

<style scoped>
.login-shell {
  display: grid;
  grid-template-columns: minmax(320px, 1.05fr) minmax(320px, 0.95fr);
  align-items: center;
  min-height: 100vh;
  min-height: 100dvh;
  max-width: 1180px;
  margin: 0 auto;
  padding: 48px 24px;
  background: #f5f7fb;
  color: #1f2937;
  gap: 32px;
}

.login-hero {
  padding: 24px 12px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 14px;
}

.brand {
  font-size: 34px;
  font-weight: 800;
  letter-spacing: 0.5px;
  color: #111827;
}

.subtitle {
  color: #6b7280;
  max-width: 460px;
}

.bullets {
  list-style: none;
  padding: 0;
  margin: 0;
  color: #6b7280;
  line-height: 1.6;
}

.mobile-brand {
  display: none;
}

.login-card {
  width: 100%;
  max-width: 440px;
  justify-self: center;
  align-self: center;
  border: 1px solid #e5e7eb;
  border-radius: 18px;
  background: #ffffff;
  box-shadow: 0 16px 40px rgba(15, 23, 42, 0.08);
}

.card-header {
  margin-bottom: 12px;
}

.card-header h2 {
  margin: 0;
  font-weight: 700;
  color: #111827;
}

.muted {
  margin: 6px 0 0;
  color: #6b7280;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.25s;
}

.fade-enter,
.fade-leave-to {
  opacity: 0;
}

.card-shell {
  position: relative;
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 420px;
}

.floating-orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(32px);
  opacity: 0.3;
}

.orb-1 {
  width: 180px;
  height: 180px;
  background: #93c5fd;
  top: -60px;
  right: -120px;
}

.orb-2 {
  width: 200px;
  height: 200px;
  background: #bfdbfe;
  bottom: -100px;
  left: -140px;
}

@media (max-width: 960px) {
  .login-shell {
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    min-height: 100vh;
    min-height: 100dvh;
    padding: 24px 16px;
    gap: 10px;
  }

  .login-hero {
    display: none;
  }

  .login-card {
    width: 100%;
    max-width: 520px;
  }

  .card-shell {
    width: 100%;
    min-height: 0;
  }

  .mobile-brand {
    display: block;
    width: min(100%, 520px);
    text-align: center;
    font-size: 22px;
    font-weight: 800;
    color: #0f172a;
    letter-spacing: 0.4px;
    text-shadow: 0 1px 0 rgba(255, 255, 255, 0.75);
    margin-bottom: 2px;
  }
}

@media (max-width: 640px) {
  .login-shell {
    padding: max(24px, env(safe-area-inset-top))
      max(14px, env(safe-area-inset-right))
      calc(24px + env(safe-area-inset-bottom))
      max(14px, env(safe-area-inset-left));
  }

  .login-card {
    max-width: 100%;
  }
}

@media (max-width: 480px) {
  .login-shell {
    min-height: 100vh;
    min-height: 100dvh;
    padding: max(14px, env(safe-area-inset-top))
      max(10px, env(safe-area-inset-right))
      calc(14px + env(safe-area-inset-bottom))
      max(10px, env(safe-area-inset-left));
    align-items: center;
    justify-items: center;
    background: radial-gradient(
        circle at 10% 10%,
        rgba(147, 197, 253, 0.28),
        transparent 45%
      ),
      radial-gradient(
        circle at 90% 85%,
        rgba(191, 219, 254, 0.36),
        transparent 46%
      ),
      #f5f7fb;
  }

  .card-shell {
    min-height: 0;
  }

  .mobile-brand {
    font-size: 18px;
    margin-bottom: 0;
  }

  .login-card {
    border-radius: 16px;
    border: 1px solid rgba(255, 255, 255, 0.8);
    box-shadow: 0 18px 36px rgba(15, 23, 42, 0.12);
    backdrop-filter: blur(2px);
  }

  .card-header h2 {
    font-size: 20px;
  }

  .muted {
    font-size: 13px;
  }

  .login-card :deep(.el-card__body) {
    padding: 16px 14px;
  }

  .login-card :deep(.el-input__inner) {
    height: 40px;
    border-radius: 10px;
  }

  .login-card :deep(.el-button) {
    border-radius: 10px;
    height: 40px;
    font-weight: 600;
  }

  .floating-orb {
    display: none;
  }
}
</style>
