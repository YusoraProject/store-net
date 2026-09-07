<template>
  <section v-loading="loading" class="registration-stats">
    <div class="toolbar">
      <h2>注册统计</h2>
      <el-button size="small" @click="load">刷新</el-button>
    </div>
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      show-icon
    />
    <div class="stat-grid">
      <el-card class="stat-card" shadow="hover"
        ><div class="stat-label">用户总数</div>
        <div class="stat-number">{{ stats.total_users }}</div>
        <div class="stat-hint">含管理员与普通用户</div></el-card
      >
      <el-card class="stat-card" shadow="hover"
        ><div class="stat-label">本月新增</div>
        <div class="stat-number">{{ stats.new_this_month }}</div>
        <div class="stat-hint">本自然月注册（协调世界时）</div></el-card
      >
    </div>
    <el-card class="chart-card" shadow="hover">
      <div slot="header" class="panel-title">最近6个月注册趋势</div>
      <div
        class="registration-chart"
        role="img"
        :aria-label="
          stats.months.map((m) => `${m.month}: ${m.count}人`).join('，')
        "
      >
        <div v-for="m in stats.months" :key="m.month" class="chart-column">
          <span>{{ m.count }}</span>
          <div class="chart-track">
            <div
              class="chart-bar"
              :style="{ height: `${Math.max(1, (m.count / maxCount) * 100)}%` }"
            />
          </div>
          <span>{{ m.month }}</span>
        </div>
      </div>
      <p class="stat-hint">仅统计本项目用户；已停用账号仍计入历史注册人数。</p>
    </el-card>
  </section>
</template>
<script>
export default {
  name: 'RegistrationStats',
  data: () => ({
    loading: false,
    error: '',
    stats: { total_users: 0, new_this_month: 0, months: [] },
  }),
  computed: {
    maxCount() {
      return Math.max(1, ...this.stats.months.map((m) => m.count))
    },
  },
  created() {
    this.load()
  },
  methods: {
    async load() {
      this.loading = true
      this.error = ''
      try {
        this.stats = (await this.$api.get('/admin/stats')).data
      } catch (e) {
        this.error = e.response?.data?.detail || '统计加载失败，请重试'
      } finally {
        this.loading = false
      }
    },
  },
}
</script>
