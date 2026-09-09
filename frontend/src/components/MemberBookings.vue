<template>
  <section class="member-bookings">
    <div class="toolbar">
      <h3>包场预约与邀请</h3>
      <el-button
        type="primary"
        :disabled="!config.slots.length"
        @click="openCreate"
        >发起包场</el-button
      ><el-button :loading="loading" @click="load">刷新</el-button>
    </div>
    <p class="muted">
      支付订金后可邀请本店会员，同意邀请的会员可在预约时段内免费上机。包场结束后自动结束免费会话。
    </p>
    <p v-if="!config.slots.length && !loading" class="muted">
      店长尚未开放包场时段。
    </p>
    <p v-if="error" class="booking-error" role="alert">{{ error }}</p>
    <p v-if="!rows.length && !loading" class="muted">暂无包场预约或邀请。</p>
    <el-card v-for="row in rows" :key="row.id" class="booking-card">
      <div class="toolbar">
        <strong>{{ row.customer_name }}</strong
        ><span class="booking-state">{{ phase(row.phase) }}</span
        ><span class="muted">{{
          row.host_user_id === userId
            ? '我发起的包场'
            : `${row.host_name || '店长'} 的邀请`
        }}</span>
      </div>
      <p>{{ row.area_name }} · {{ row.slot_name || '自定义时段' }}</p>
      <p>
        {{ displayTime(row.started_at) }} 至 {{ displayTime(row.ended_at) }}
      </p>
      <p>
        总价 ¥{{ money(row.amount) }} · 订金 ¥{{ money(row.deposit) }}（{{
          row.deposit_percent
        }}%）· {{ row.deposit_paid ? '订金已支付' : '订金未支付' }}
      </p>
      <p v-if="row.phase === 'awaiting_deposit'" class="booking-error">
        请在 {{ displayTime(row.hold_until) }} 前支付订金，超时自动释放时段。
      </p>
      <p v-if="row.phase === 'cancelled' && row.refunded > 0" class="muted">
        已退款 ¥{{ money(row.refunded) }}
      </p>
      <template v-if="row.host_user_id === userId">
        <div class="toolbar" v-if="active(row)">
          <el-button
            v-if="!row.deposit_paid"
            type="primary"
            :disabled="busy"
            @click="choose(row, 'deposit')"
            >支付订金 ¥{{ money(row.deposit) }}</el-button
          >
          <el-button
            v-else
            type="primary"
            :disabled="busy"
            @click="openInvite(row)"
            >邀请会员</el-button
          >
          <el-button
            v-if="row.paid === 0"
            :disabled="busy"
            @click="choose(row, 'cancel')"
            >取消包场</el-button
          >
        </div>
        <p v-if="row.paid > 0 && active(row)" class="muted">
          剩余尾款 ¥{{ money(Math.max(0, row.amount - row.paid)) }}
          由店长收取；取消或退款请联系店长。
        </p>
        <div v-if="row.participants.length" class="booking-people">
          <span v-for="p in row.participants" :key="p.user_id"
            >{{ p.name }} ·
            {{
              p.user_id === row.host_user_id ? '发起人' : invitation(p.status)
            }}</span
          >
        </div>
      </template>
      <template v-else-if="active(row)">
        <p v-if="!row.deposit_paid" class="muted">
          等待发起人支付订金后即可处理邀请。
        </p>
        <div v-else class="toolbar">
          <el-button
            v-if="row.my_invitation !== 'accepted'"
            type="primary"
            :disabled="busy"
            @click="respond(row, true)"
            >同意邀请</el-button
          >
          <span v-else class="booking-success"
            >已同意，可在包场时段内免费上机</span
          >
          <el-button
            v-if="row.my_invitation !== 'declined'"
            :disabled="busy"
            @click="choose(row, 'decline')"
            >{{
              row.my_invitation === 'accepted' ? '退出包场' : '拒绝邀请'
            }}</el-button
          >
        </div>
      </template>
      <el-button
        v-if="
          row.phase === 'in_progress' &&
          row.deposit_paid &&
          row.my_invitation === 'accepted'
        "
        @click="$emit('go-home')"
        >前往免费上机</el-button
      >
    </el-card>

    <el-dialog
      title="发起包场"
      :visible.sync="creating"
      width="580px"
      :close-on-click-modal="false"
      :show-close="!busy"
    >
      <el-form label-position="top">
        <el-form-item label="包场名称"
          ><el-input v-model="form.customer_name" maxlength="120"
        /></el-form-item>
        <el-form-item label="包场日期"
          ><input
            type="date"
            v-model="form.booking_date"
            :min="today"
            aria-label="包场日期"
            class="booking-date"
        /></el-form-item>
        <el-form-item label="包场时段"
          ><el-select v-model="form.slot_id" placeholder="选择包场时段"
            ><el-option
              v-for="s in config.slots"
              :key="s.id"
              :value="s.id"
              :label="`${s.area_name} · ${s.name} ${s.start}—${
                s.end
              } · ¥${money(s.price)}`" /></el-select
        ></el-form-item>
        <div v-if="selectedSlot" class="booking-price">
          <strong>总价 ¥{{ money(selectedSlot.price) }}</strong>
          <p>
            订金 {{ config.deposit_percent }}%：¥{{
              money(deposit(selectedSlot.price, config.deposit_percent))
            }}
          </p>
          <p v-if="selectedSlot.start >= selectedSlot.end">
            {{
              selectedSlot.start === selectedSlot.end
                ? '全天包场，至次日同一时间结束。'
                : '此时段跨午夜，至次日结束。'
            }}
          </p>
        </div>
        <p class="muted">
          创建后保留时段15分钟，请使用本店充值余额支付订金。赠送余额和次卡不用于订金。
        </p>
        <p v-if="dialogError" role="alert" class="booking-error">
          {{ dialogError }}
        </p>
      </el-form>
      <span slot="footer"
        ><el-button :disabled="busy" @click="creating = false">返回</el-button
        ><el-button type="primary" :loading="busy" @click="create"
          >创建并前往支付</el-button
        ></span
      >
    </el-dialog>

    <el-dialog
      :title="
        action === 'deposit'
          ? '支付包场订金'
          : action === 'cancel'
          ? '取消包场'
          : '退出或拒绝邀请'
      "
      :visible.sync="confirming"
      width="470px"
      :close-on-click-modal="false"
      :show-close="!busy"
    >
      <template v-if="target"
        ><p>{{ target.customer_name }} · {{ target.area_name }}</p>
        <template v-if="action === 'deposit'"
          ><p>从本店充值余额支付订金 ¥{{ money(target.deposit) }}。</p>
          <p>当前充值余额：¥{{ money(config.balance) }}</p></template
        >
        <p v-else-if="action === 'cancel'">取消后释放该包场时段。</p>
        <p v-else>
          确认不参加本次包场？正在进行的包场免费上机会同时结束。
        </p></template
      >
      <p v-if="dialogError" role="alert" class="booking-error">
        {{ dialogError }}
      </p>
      <span slot="footer"
        ><el-button :disabled="busy" @click="confirming = false">返回</el-button
        ><el-button type="primary" :loading="busy" @click="act">{{
          action === 'deposit' ? '确认支付订金' : '确认'
        }}</el-button></span
      >
    </el-dialog>

    <el-dialog
      title="邀请会员参加包场"
      :visible.sync="inviting"
      width="520px"
      :close-on-click-modal="false"
      :show-close="!busy"
    >
      <p>搜索本店会员的用户名或姓名，发送邀请后需对方同意。</p>
      <el-select
        v-model="inviteIds"
        multiple
        filterable
        remote
        :remote-method="search"
        :loading="searching"
        placeholder="输入用户名或姓名搜索"
        ><el-option
          v-for="u in candidates"
          :key="u.id"
          :value="u.id"
          :label="`${u.name} (${u.username})`"
      /></el-select>
      <p v-if="dialogError" role="alert" class="booking-error">
        {{ dialogError }}
      </p>
      <span slot="footer"
        ><el-button :disabled="busy" @click="inviting = false">返回</el-button
        ><el-button
          type="primary"
          :loading="busy"
          :disabled="!inviteIds.length"
          @click="invite"
          >发送邀请</el-button
        ></span
      >
    </el-dialog>
  </section>
</template>
<script>
import {
  money,
  beijingDate,
  displayTime,
  deposit,
  phase,
  invitation,
  message,
  requestKey,
} from '../booking-utils'
export default {
  name: 'MemberBookings',
  props: {
    storeId: { type: Number, required: true },
    userId: { type: Number, required: true },
  },
  data: () => ({
    rows: [],
    config: { slots: [], deposit_percent: 30, balance: 0 },
    loading: false,
    busy: false,
    error: '',
    dialogError: '',
    creating: false,
    confirming: false,
    inviting: false,
    target: null,
    action: '',
    form: {},
    timer: null,
    today: beijingDate(),
    candidates: [],
    inviteIds: [],
    searching: false,
    searchVersion: 0,
  }),
  computed: {
    selectedSlot() {
      return this.config.slots.find((s) => s.id === this.form.slot_id)
    },
  },
  mounted() {
    this.load()
    this.timer = setInterval(() => {
      if (!this.busy && !this.creating && !this.confirming && !this.inviting)
        this.load()
    }, 30000)
  },
  beforeDestroy() {
    clearInterval(this.timer)
  },
  methods: {
    money,
    displayTime,
    deposit,
    phase,
    invitation,
    active(row) {
      return !['cancelled', 'ended', 'expired'].includes(row.phase)
    },
    async load() {
      if (this.loading) return
      this.loading = true
      try {
        const [config, rows] = await Promise.all([
          this.$api.get(`/me/stores/${this.storeId}/booking-config`),
          this.$api.get(`/me/stores/${this.storeId}/bookings`),
        ])
        this.config = config.data
        this.rows = rows.data
        this.error = ''
      } catch (e) {
        this.error = message(e)
      } finally {
        this.loading = false
      }
    },
    openCreate() {
      this.form = {
        customer_name: '我的包场',
        booking_date: beijingDate(),
        slot_id: this.config.slots[0]?.id,
        request_key: requestKey(),
      }
      this.dialogError = ''
      this.creating = true
    },
    async create() {
      if (this.busy) return
      if (
        !this.form.customer_name.trim() ||
        !this.form.booking_date ||
        !this.form.slot_id
      ) {
        this.dialogError = '请填写名称并选择日期和时段'
        return
      }
      this.busy = true
      this.dialogError = ''
      try {
        const { data } = await this.$api.post(
          `/me/stores/${this.storeId}/bookings`,
          this.form
        )
        this.creating = false
        await this.load()
        this.choose(data, 'deposit')
      } catch (e) {
        this.dialogError = message(e)
      } finally {
        this.busy = false
      }
    },
    choose(row, action) {
      this.target = row
      this.action = action
      this.dialogError = ''
      this.confirming = true
    },
    async act() {
      if (this.busy) return
      this.busy = true
      this.dialogError = ''
      try {
        await this.$api.post(
          `/me/stores/${this.storeId}/bookings/${this.target.id}/${
            this.action === 'decline' ? 'respond' : this.action
          }`,
          this.action === 'decline' ? { accept: false } : {}
        )
        this.confirming = false
        await this.load()
        this.$emit('changed')
      } catch (e) {
        this.dialogError = message(e)
      } finally {
        this.busy = false
      }
    },
    async respond(row, accept) {
      if (this.busy) return
      this.busy = true
      try {
        await this.$api.post(
          `/me/stores/${this.storeId}/bookings/${row.id}/respond`,
          { accept }
        )
        await this.load()
        this.$emit('changed')
      } catch (e) {
        this.error = message(e)
      } finally {
        this.busy = false
      }
    },
    openInvite(row) {
      this.target = row
      this.inviteIds = []
      this.candidates = []
      this.dialogError = ''
      this.inviting = true
    },
    async search(q) {
      const version = ++this.searchVersion
      if (!q.trim()) {
        this.candidates = []
        this.searching = false
        return
      }
      this.searching = true
      try {
        const { data } = await this.$api.get(
          `/me/stores/${this.storeId}/booking-members`,
          { params: { q: q.trim() } }
        )
        if (version === this.searchVersion) this.candidates = data
      } catch (e) {
        if (version === this.searchVersion) this.dialogError = message(e)
      } finally {
        if (version === this.searchVersion) this.searching = false
      }
    },
    async invite() {
      if (this.busy || !this.inviteIds.length) return
      this.busy = true
      try {
        await this.$api.post(
          `/me/stores/${this.storeId}/bookings/${this.target.id}/invite`,
          { user_ids: this.inviteIds }
        )
        this.inviting = false
        await this.load()
      } catch (e) {
        this.dialogError = message(e)
      } finally {
        this.busy = false
      }
    },
  },
}
</script>
<style scoped>
.member-bookings h3 {
  margin: 0;
}
.booking-card {
  margin: 16px 0;
}
.booking-card p,
.member-bookings > p {
  line-height: 1.8;
}
.booking-state {
  padding: 4px 10px;
  background: #eef4ff;
  border-radius: 6px;
  color: #2563eb;
  font-size: 13px;
}
.booking-error {
  color: #b45309;
  line-height: 1.8;
}
.booking-success {
  color: #15803d;
}
.booking-people {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 16px 0;
}
.booking-people span {
  padding: 5px 10px;
  background: #f4f6f8;
  border-radius: 6px;
  font-size: 13px;
}
.member-bookings .el-select {
  width: 100%;
}
.booking-date {
  width: 100%;
  min-width: 0;
  height: 40px;
  box-sizing: border-box;
  padding: 0 10px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  color: inherit;
  background: transparent;
  font: inherit;
}
.booking-price {
  padding: 16px;
  background: #f4f7fb;
  border-radius: 8px;
}
.dark-mode .booking-state,
.dark-mode .booking-people span,
.dark-mode .booking-price {
  background: #202d40;
}
</style>
