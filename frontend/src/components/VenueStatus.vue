<template>
  <section class="venue-status">
    <div class="toolbar">
      <h2>场况</h2>
      <el-select v-model="storeId" placeholder="选择门店"
        ><el-option
          v-for="s in stores"
          :key="s.id"
          :value="s.id"
          :label="s.name" /></el-select
      ><el-button :loading="loading" :disabled="!storeId" @click="load"
        >刷新</el-button
      >
    </div>
    <p v-if="!stores.length" class="muted">加入门店后即可查看场况。</p>
    <el-alert v-if="error" :title="error" type="warning" :closable="false" />
    <template v-if="snapshot">
      <div class="venue-summary">
        <div>
          <strong>{{ snapshot.online_count }}</strong
          ><span>当前上机</span>
        </div>
        <div>
          <strong>{{ snapshot.areas.length }}</strong
          ><span>计费区域</span>
        </div>
        <div>
          <strong>{{ snapshot.pending_count }}</strong
          ><span title="入场或换区申请待确认">待确认</span>
        </div>
      </div>
      <p v-if="!snapshot.store_active" class="muted">该门店已停用。</p>
      <div class="venue-areas">
        <el-card
          v-for="area in snapshot.areas"
          :key="area.id || 'unassigned'"
          class="venue-area"
        >
          <div slot="header" class="venue-area-heading">
            <div>
              <h3>{{ area.name }}</h3>
              <span v-if="!area.enabled" class="muted">{{
                area.id ? '区域已停用' : '历史记录未关联区域'
              }}</span>
            </div>
            <span class="venue-count">{{ area.users.length }} 人上机</span>
          </div>
          <p v-if="area.booking" class="venue-booking">
            {{
              area.booking.pending_payment
                ? '包场预留中，等待订金'
                : '当前包场中'
            }}
            · 至 {{ displayTime(area.booking.ends_at) }}
          </p>
          <p v-if="area.pending_count" class="muted">
            {{ area.pending_count }}
            条入场或换区申请待确认，尚未计入本区上机人数。
          </p>
          <div v-if="!area.users.length" class="venue-empty">
            当前暂无用户上机
          </div>
          <div
            v-for="user in area.users"
            :key="user.session_id"
            class="venue-person"
          >
            <el-avatar
              :src="user.avatar"
              :size="42"
              icon="el-icon-user-solid"
            />
            <div class="venue-person-details">
              <div class="venue-person-name">
                <strong>{{ user.name }}</strong
                ><span v-if="user.is_me" class="venue-me">我</span
                ><span v-if="user.free" class="venue-free">包场免费</span>
              </div>
              <p>上机 {{ duration(user.elapsed_seconds + elapsed) }}</p>
              <p class="muted">
                进入本区 {{ displayTime(user.area_entered_at) }}
              </p>
            </div>
          </div>
        </el-card>
      </div>
      <p v-if="!snapshot.areas.length" class="venue-empty">
        门店尚未配置计费区域。
      </p>
    </template>
  </section>
</template>
<script>
import { displayTime, message } from '../booking-utils'
export default {
  name: 'VenueStatus',
  props: { stores: { type: Array, required: true }, initialStoreId: Number },
  data() {
    return {
      storeId: this.initialStoreId || this.stores[0]?.id || null,
      snapshot: null,
      loading: false,
      error: '',
      elapsed: 0,
      receivedAt: 0,
      timer: null,
      clock: null,
      version: 0,
      stopped: false,
    }
  },
  watch: {
    storeId() {
      this.version++
      this.snapshot = null
      this.error = ''
      this.load()
    },
    stores(value) {
      if (!value.some((s) => s.id === this.storeId))
        this.storeId = value[0]?.id || null
    },
  },
  mounted() {
    this.load()
    this.timer = setInterval(() => {
      if (!document.hidden && !this.loading) this.load()
    }, 5000)
    this.clock = setInterval(() => {
      if (!this.error && this.receivedAt)
        this.elapsed = Math.floor((performance.now() - this.receivedAt) / 1000)
    }, 1000)
    document.addEventListener('visibilitychange', this.visible)
  },
  beforeDestroy() {
    this.stopped = true
    this.version++
    clearInterval(this.timer)
    clearInterval(this.clock)
    document.removeEventListener('visibilitychange', this.visible)
  },
  methods: {
    displayTime,
    duration(seconds) {
      const minutes = Math.floor(Math.max(0, seconds) / 60)
      return minutes >= 60
        ? `${Math.floor(minutes / 60)}小时${minutes % 60}分钟`
        : `${minutes}分钟`
    },
    visible() {
      if (!document.hidden) this.load()
    },
    async load() {
      const id = this.storeId,
        version = ++this.version
      if (!id) {
        this.loading = false
        return
      }
      this.loading = true
      try {
        const { data } = await this.$api.get(`/stores/${id}/venue-status`, {
          timeout: 10000,
        })
        if (this.stopped || version !== this.version) return
        this.snapshot = data
        this.receivedAt = performance.now()
        this.elapsed = 0
        this.error = ''
      } catch (e) {
        if (this.stopped || version !== this.version) return
        const status = e.response?.status
        if ([401, 403, 404].includes(status)) {
          this.snapshot = null
        }
        this.error = this.snapshot
          ? '场况暂时更新失败，当前显示上次的数据，请稍后刷新。'
          : message(e)
      } finally {
        if (version === this.version) this.loading = false
      }
    },
  },
}
</script>
<style scoped>
.venue-status {
  box-sizing: border-box;
  padding: 28px;
  border: 1px solid rgba(255, 255, 255, 0.85);
  border-radius: 24px;
  background: radial-gradient(
      ellipse at 12% 12%,
      rgba(255, 255, 255, 0.95),
      transparent 48%
    ),
    radial-gradient(
      ellipse at 88% 34%,
      rgba(159, 207, 255, 0.55),
      transparent 55%
    ),
    linear-gradient(145deg, #e8f4ff, #dceeff 55%, #edf7ff);
  color: #234564;
}
.venue-status h2,
.venue-status h3 {
  margin: 0;
}
.venue-status .toolbar {
  display: grid;
  grid-template-columns: auto minmax(160px, 240px) auto;
  justify-content: start;
  align-items: center;
  gap: 12px;
  margin-bottom: 0;
}
.venue-status .toolbar > .el-button {
  margin: 0;
  min-width: 84px;
}
.venue-status .muted {
  color: #58758e;
  line-height: 1.7;
}
.venue-status ::v-deep .el-input__inner,
.venue-status .toolbar > .el-button {
  background: rgba(255, 255, 255, 0.6);
  border-color: rgba(255, 255, 255, 0.9);
  border-radius: 12px;
  color: #315b7c;
  -webkit-backdrop-filter: blur(16px);
  backdrop-filter: blur(16px);
}
.venue-status .toolbar > .el-button:hover {
  background: rgba(255, 255, 255, 0.88);
  border-color: #a8cdec;
}
.venue-status ::v-deep .el-input__inner:focus,
.venue-status .toolbar > .el-button:focus-visible {
  border-color: #5997c9;
}
.venue-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  margin: 26px 0;
}
.venue-summary > div {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 20px 22px;
  border: 1px solid rgba(255, 255, 255, 0.82);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.42);
  box-shadow: 0 6px 24px rgba(76, 124, 164, 0.05),
    inset 0 1px 0 rgba(255, 255, 255, 0.7);
  -webkit-backdrop-filter: blur(20px) saturate(130%);
  backdrop-filter: blur(20px) saturate(130%);
}
.venue-summary strong {
  font-size: 32px;
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
  color: #285779;
}
.venue-summary span {
  color: #58758e;
  font-size: 13px;
  line-height: 1.6;
  white-space: nowrap;
}
.venue-areas {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 360px), 1fr));
  gap: 20px;
  align-items: start;
}
.venue-status .venue-area {
  min-width: 0;
  background: rgba(255, 255, 255, 0.48);
  border: 1px solid rgba(255, 255, 255, 0.86) !important;
  border-radius: 20px !important;
  box-shadow: 0 12px 32px rgba(68, 113, 155, 0.09),
    inset 0 1px 0 rgba(255, 255, 255, 0.8);
  color: #234564;
  -webkit-backdrop-filter: blur(24px) saturate(140%);
  backdrop-filter: blur(24px) saturate(140%);
}
.venue-area ::v-deep .el-card__header {
  padding: 22px 24px;
  background: rgba(255, 255, 255, 0.18);
  border-bottom: 1px solid rgba(255, 255, 255, 0.72);
}
.venue-area ::v-deep .el-card__body {
  padding: 12px 24px 20px;
}
.venue-area-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.venue-area-heading h3 {
  font-size: 17px;
  line-height: 1.5;
}
.venue-count,
.venue-me,
.venue-free {
  padding: 6px 10px;
  border-radius: 9px;
  border: 1px solid rgba(255, 255, 255, 0.8);
  background: rgba(210, 232, 252, 0.65);
  color: #315f85;
  font-size: 12px;
  white-space: nowrap;
}
.venue-free {
  background: rgba(219, 245, 233, 0.72);
  color: #28664e;
}
.venue-booking {
  background: rgba(255, 246, 222, 0.7);
  border: 1px solid rgba(255, 255, 255, 0.75);
  color: #87601e;
  padding: 12px;
  border-radius: 12px;
  line-height: 1.7;
}
.venue-person {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 0;
  border-bottom: 1px solid rgba(122, 162, 193, 0.18);
}
.venue-person:last-child {
  border-bottom: 0;
}
.venue-person .el-avatar {
  flex-shrink: 0;
  background: rgba(109, 153, 188, 0.25);
  color: #47779c;
  border: 1px solid rgba(255, 255, 255, 0.8);
}
.venue-person-details {
  min-width: 0;
}
.venue-person-name {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  overflow-wrap: anywhere;
}
.venue-person p {
  margin: 7px 0 0;
  font-size: 13px;
}
.venue-empty {
  color: #607e96;
  text-align: center;
  padding: 30px 12px;
}
.dark-mode .venue-status {
  color: #d9eafa;
  border-color: rgba(134, 182, 219, 0.2);
  background: radial-gradient(
      ellipse at 85% 25%,
      rgba(45, 94, 135, 0.5),
      transparent 60%
    ),
    linear-gradient(145deg, #172b40, #1c3853);
}
.dark-mode .venue-status .venue-area,
.dark-mode .venue-summary > div {
  background: rgba(39, 65, 89, 0.52);
  border-color: rgba(171, 209, 236, 0.22) !important;
  color: #d9eafa;
  box-shadow: 0 12px 32px rgba(4, 15, 29, 0.14),
    inset 0 1px 0 rgba(215, 235, 252, 0.08);
}
.dark-mode .venue-area ::v-deep .el-card__header {
  background: rgba(154, 197, 230, 0.05);
  border-color: rgba(171, 209, 236, 0.14);
}
.dark-mode .venue-status ::v-deep .el-input__inner,
.dark-mode .venue-status .toolbar > .el-button {
  background: rgba(41, 68, 92, 0.65);
  border-color: rgba(171, 209, 236, 0.28) !important;
  color: #d9eafa;
}
.dark-mode .venue-status .muted,
.dark-mode .venue-summary span,
.dark-mode .venue-empty {
  color: #aec8dd;
}
.dark-mode .venue-summary strong {
  color: #e2e8f0;
}
.dark-mode .venue-person {
  border-color: rgba(171, 209, 236, 0.16);
}
.dark-mode .venue-count,
.dark-mode .venue-me {
  background: rgba(61, 104, 144, 0.45);
  color: #b5d1f9;
}
.dark-mode .venue-count,
.dark-mode .venue-me,
.dark-mode .venue-free,
.dark-mode .venue-booking {
  border-color: rgba(171, 209, 236, 0.18);
}
.dark-mode .venue-free {
  background: #203e31;
  color: #a7dfbc;
}
.dark-mode .venue-booking {
  background: #423723;
  color: #f3cd94;
}
@media (max-width: 760px) {
  .venue-status {
    padding: 18px 14px;
    border-radius: 20px;
  }
  .venue-status .toolbar {
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 14px 12px;
  }
  .venue-status .toolbar > h2 {
    grid-column: 1;
    grid-row: 1;
  }
  .venue-status .toolbar > .el-button {
    grid-column: 2;
    grid-row: 1;
    min-height: 36px;
    padding: 9px 14px;
  }
  .venue-status .toolbar > .el-select {
    grid-column: 1 / -1;
    grid-row: 2;
    min-width: 0;
  }
  .venue-summary {
    gap: 8px;
    margin: 18px 0;
  }
  .venue-summary > div {
    padding: 14px 10px;
    border-radius: 14px;
    align-content: start;
  }
  .venue-summary strong {
    font-size: 27px;
  }
  .venue-summary span {
    font-size: 12px;
  }
  .venue-area ::v-deep .el-card__header {
    padding: 18px 16px;
  }
  .venue-area ::v-deep .el-card__body {
    padding: 10px 16px 18px;
  }
}
</style>
