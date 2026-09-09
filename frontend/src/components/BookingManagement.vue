<template>
  <section class="booking-management">
    <div class="toolbar">
      <el-button type="primary" @click="openCreate">新增包场</el-button
      ><el-button @click="openConfig">包场配置</el-button
      ><el-button :loading="loading" @click="load">刷新</el-button
      ><span class="muted">包场净收款 ¥{{ money(revenue) }}</span>
    </div>
    <p class="muted booking-help">
      包场期间仅付订金的发起人及已同意邀请的会员可免费上机。请在包场开始前清场，普通消费需正常结账。时段和总价在“定价”中设置。
    </p>
    <p v-if="error" role="alert" class="booking-warning">{{ error }}</p>
    <el-table :data="rows" v-loading="loading" empty-text="暂无包场记录">
      <el-table-column prop="area_name" label="包场范围" min-width="120" />
      <el-table-column label="客户 / 发起人" min-width="160"
        ><template slot-scope="s"
          ><strong>{{ s.row.customer_name }}</strong>
          <div class="muted">{{ s.row.host_name || '未关联用户' }}</div>
          <div class="muted">{{ s.row.contact }}</div></template
        ></el-table-column
      >
      <el-table-column label="时段" min-width="195"
        ><template slot-scope="s"
          ><strong>{{ s.row.slot_name || '自定义' }}</strong>
          <div>{{ displayTime(s.row.started_at) }}</div>
          <div>至 {{ displayTime(s.row.ended_at) }}</div></template
        ></el-table-column
      >
      <el-table-column label="状态" min-width="175"
        ><template slot-scope="s"
          ><div>{{ phase(s.row.phase) }}</div>
          <div v-if="s.row.occupancy_count" class="booking-warning">
            当前 {{ s.row.occupancy_count }} 条上机或发码记录
          </div></template
        ></el-table-column
      >
      <el-table-column label="金额" min-width="190"
        ><template slot-scope="s"
          ><div>总价 ¥{{ money(s.row.amount) }}</div>
          <div>
            订金 ¥{{ money(s.row.deposit) }}（{{ s.row.deposit_percent }}%）
          </div>
          <div class="muted">
            实收 ¥{{ money(s.row.paid) }} / 退款 ¥{{ money(s.row.refunded) }}
          </div></template
        ></el-table-column
      >
      <el-table-column label="参与会员" min-width="150"
        ><template slot-scope="s"
          ><div v-for="p in s.row.participants" :key="p.user_id">
            {{ p.name }} ·
            {{
              p.user_id === s.row.host_user_id ? '发起人' : invitation(p.status)
            }}
          </div>
          <span v-if="!s.row.participants.length" class="muted"
            >未选择</span
          ></template
        ></el-table-column
      >
      <el-table-column prop="remark" label="备注" min-width="130" />
      <el-table-column label="操作" min-width="300"
        ><template slot-scope="s"
          ><div class="table-actions" v-if="s.row.status !== 'cancelled'">
            <el-button
              v-if="
                !s.row.deposit_paid &&
                !['expired', 'ended'].includes(s.row.phase)
              "
              size="mini"
              :disabled="busy"
              @click="choose(s.row, 'deposit')"
              >登记订金</el-button
            ><el-button
              v-if="!s.row.is_paid && s.row.phase !== 'expired'"
              size="mini"
              type="primary"
              :disabled="busy"
              @click="choose(s.row, 'pay')"
              >{{ s.row.paid > 0 ? '登记尾款' : '登记全款' }}</el-button
            ><el-button
              size="mini"
              :disabled="busy"
              @click="choose(s.row, 'cancel')"
              >{{ s.row.paid > 0 ? '退款并取消' : '取消包场' }}</el-button
            >
          </div>
          <span v-else class="muted">已取消</span></template
        ></el-table-column
      >
    </el-table>

    <el-dialog
      title="包场配置"
      :visible.sync="configuring"
      width="480px"
      :close-on-click-modal="false"
    >
      <el-form label-position="top"
        ><el-form-item label="包场订金比例 / %"
          ><el-input-number
            v-model="draftPercent"
            :min="1"
            :max="100"
            :precision="0"
            aria-label="包场订金比例" /></el-form-item
      ></el-form>
      <p>
        会员创建包场后，按总价的此比例支付订金。支付成功后才开放邀请和免费上机资格。
      </p>
      <p class="muted">仅影响新创建的包场，已有订单保留原比例。</p>
      <p v-if="dialogError" role="alert" class="booking-warning">
        {{ dialogError }}
      </p>
      <span slot="footer"
        ><el-button :disabled="busy" @click="configuring = false"
          >返回</el-button
        ><el-button type="primary" :loading="busy" @click="saveConfig"
          >保存配置</el-button
        ></span
      >
    </el-dialog>

    <el-dialog
      title="新增包场"
      :visible.sync="creating"
      width="650px"
      :close-on-click-modal="false"
      :close-on-press-escape="!busy"
      :show-close="!busy"
    >
      <el-form label-position="top" @submit.native.prevent="create">
        <el-form-item label="包场时段"
          ><el-select v-model="form.slot_id" placeholder="选择包场时段"
            ><el-option
              v-for="s in slots.filter((x) => x.available)"
              :key="s.id"
              :value="s.id"
              :label="`${s.area_name} · ${s.name} ${s.start}—${
                s.end
              } · ¥${money(s.price)}`" /><el-option
              value=""
              label="自定义时间和价格" /></el-select
        ></el-form-item>
        <el-form-item v-if="form.slot_id" label="包场日期"
          ><input
            v-model="form.booking_date"
            type="date"
            aria-label="手动包场日期"
            class="booking-time"
        /></el-form-item>
        <template v-else>
          <el-form-item label="包场范围"
            ><el-select v-model="form.area_id"
              ><el-option label="整店（所有区域）" :value="0" /><el-option
                v-for="a in areas"
                :key="a.id"
                :label="a.name"
                :value="a.id" /></el-select
          ></el-form-item>
          <div class="booking-grid">
            <el-form-item label="开始时间"
              ><input
                v-model="form.started_at"
                type="datetime-local"
                aria-label="包场开始时间"
                class="booking-time" /></el-form-item
            ><el-form-item label="结束时间"
              ><input
                v-model="form.ended_at"
                type="datetime-local"
                aria-label="包场结束时间"
                class="booking-time"
            /></el-form-item>
          </div>
          <el-form-item label="包场总价 / 元"
            ><el-input-number
              v-model="form.amount"
              :min="0"
              :max="1000000"
              :precision="2"
          /></el-form-item>
        </template>
        <p>
          总价 ¥{{ money(total) }} · 订金 {{ depositPercent }}%：¥{{
            money(deposit(total, depositPercent))
          }}
        </p>
        <div class="booking-grid">
          <el-form-item label="客户 / 活动名称"
            ><el-input
              v-model="form.customer_name"
              maxlength="120" /></el-form-item
          ><el-form-item label="联系方式（选填）"
            ><el-input v-model="form.contact" maxlength="120"
          /></el-form-item>
        </div>
        <el-form-item label="发起用户（选填）"
          ><el-select
            v-model="form.host_user_id"
            clearable
            filterable
            placeholder="选择本店会员"
            ><el-option
              v-for="u in members"
              :key="u.id"
              :value="u.id"
              :label="`${u.name} (${u.username})`" /></el-select
        ></el-form-item>
        <el-form-item label="受邀会员（选填）"
          ><el-select
            v-model="form.user_ids"
            multiple
            filterable
            placeholder="选择参与会员，需对方同意"
            ><el-option
              v-for="u in members.filter((x) => x.id !== form.host_user_id)"
              :key="u.id"
              :value="u.id"
              :label="`${u.name} (${u.username})`" /></el-select
        ></el-form-item>
        <p class="muted">
          选中的发起人可自行支付订金，也可由店长登记线下订金。受邀会员须在支付后主动同意邀请。
        </p>
        <el-form-item label="备注（选填）"
          ><el-input
            v-model="form.remark"
            type="textarea"
            maxlength="500"
            :rows="2"
        /></el-form-item>
        <p v-if="dialogError" role="alert" class="booking-warning">
          {{ dialogError }}
        </p>
      </el-form>
      <span slot="footer"
        ><el-button :disabled="busy" @click="creating = false">返回</el-button
        ><el-button type="primary" :loading="busy" @click="create"
          >创建包场</el-button
        ></span
      >
    </el-dialog>

    <el-dialog
      :title="action === 'cancel' ? '取消包场' : '登记线下收款'"
      :visible.sync="confirming"
      width="490px"
      :close-on-click-modal="false"
      :show-close="!busy"
      :close-on-press-escape="!busy"
    >
      <template v-if="target"
        ><p>{{ target.customer_name }} · {{ target.area_name }}</p>
        <p v-if="action !== 'cancel'">
          请确认已在线下收到{{ action === 'deposit' ? '订金' : '剩余款项' }} ¥{{
            money(
              Math.max(
                0,
                (action === 'deposit' ? target.deposit : target.amount) -
                  target.paid
              )
            )
          }}。此操作只登记收款。
        </p>
        <template v-else
          ><p v-if="target.balance_paid > 0">
            充值余额支付的 ¥{{ money(target.balance_paid) }}
            将自动退回发起人的本店充值余额。
          </p>
          <p v-if="target.paid > target.balance_paid">
            请先在线下退还 ¥{{
              money(target.paid - target.balance_paid)
            }}，再确认取消。
          </p>
          <p>取消后释放时段并结束本次包场的免费上机，记录会保留。</p></template
        ></template
      >
      <p v-if="dialogError" role="alert" class="booking-warning">
        {{ dialogError }}
      </p>
      <span slot="footer"
        ><el-button :disabled="busy" @click="confirming = false">返回</el-button
        ><el-button type="primary" :loading="busy" @click="act">{{
          action !== 'cancel'
            ? '已收款，确认登记'
            : target && target.paid > target.balance_paid
            ? '已退线下款，确认取消'
            : '确认取消'
        }}</el-button></span
      >
    </el-dialog>
  </section>
</template>
<script>
import {
  money,
  beijingInput,
  beijingDate,
  toUTC,
  displayTime,
  deposit,
  phase,
  invitation,
  message,
  requestKey,
} from '../booking-utils'
export default {
  name: 'BookingManagement',
  props: { storeId: { type: Number, required: true } },
  data: () => ({
    rows: [],
    areas: [],
    slots: [],
    members: [],
    revenue: 0,
    depositPercent: 30,
    draftPercent: 30,
    loading: false,
    busy: false,
    error: '',
    dialogError: '',
    creating: false,
    confirming: false,
    configuring: false,
    form: {},
    target: null,
    action: '',
    timer: null,
  }),
  computed: {
    total() {
      return this.form.slot_id
        ? this.slots.find((s) => s.id === this.form.slot_id)?.price || 0
        : this.form.amount || 0
    },
  },
  mounted() {
    this.load()
    this.timer = setInterval(() => {
      if (!this.busy && !this.creating && !this.confirming && !this.configuring)
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
    async load() {
      if (this.loading) return
      this.loading = true
      try {
        const { data } = await this.$api.get(`/stores/${this.storeId}/bookings`)
        this.rows = data.items
        this.areas = data.areas
        this.slots = data.slots
        this.members = data.members
        this.depositPercent = data.deposit_percent
        this.revenue = data.revenue
        this.error = ''
      } catch (e) {
        this.error = message(e)
      } finally {
        this.loading = false
      }
    },
    openConfig() {
      this.draftPercent = this.depositPercent
      this.dialogError = ''
      this.configuring = true
    },
    async saveConfig() {
      if (this.busy) return
      this.busy = true
      try {
        await this.$api.put(`/stores/${this.storeId}/booking-config`, {
          deposit_percent: this.draftPercent,
        })
        this.configuring = false
        await this.load()
      } catch (e) {
        this.dialogError = message(e)
      } finally {
        this.busy = false
      }
    },
    openCreate() {
      const start = new Date(Date.now() + 5 * 60000)
      this.form = {
        slot_id: this.slots.find((s) => s.available)?.id || '',
        booking_date: beijingDate(),
        area_id: this.areas.length === 1 ? this.areas[0].id : 0,
        customer_name: '',
        contact: '',
        started_at: beijingInput(start),
        ended_at: beijingInput(new Date(start.getTime() + 3 * 3600000)),
        amount: 0,
        remark: '',
        host_user_id: null,
        user_ids: [],
        request_key: requestKey(),
      }
      this.dialogError = ''
      this.creating = true
    },
    async create() {
      if (this.busy) return
      if (
        !this.form.customer_name.trim() ||
        (this.form.slot_id
          ? !this.form.booking_date
          : !this.form.started_at ||
            !this.form.ended_at ||
            !Number.isFinite(this.form.amount))
      ) {
        this.dialogError = '请填写客户、有效起止时间和总价'
        return
      }
      this.busy = true
      this.dialogError = ''
      try {
        const data = {
          customer_name: this.form.customer_name,
          contact: this.form.contact,
          remark: this.form.remark,
          host_user_id: this.form.host_user_id || null,
          user_ids: this.form.user_ids,
          request_key: this.form.request_key,
          ...(this.form.slot_id
            ? {
                slot_id: this.form.slot_id,
                booking_date: this.form.booking_date,
              }
            : {
                area_id: this.form.area_id || null,
                started_at: toUTC(this.form.started_at),
                ended_at: toUTC(this.form.ended_at),
                amount: this.form.amount,
              }),
        }
        await this.$api.post(`/stores/${this.storeId}/bookings`, data)
        this.creating = false
        await this.load()
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
          `/stores/${this.storeId}/bookings/${this.target.id}/${this.action}`,
          this.action === 'cancel'
            ? { refund_confirmed: this.target.paid > this.target.balance_paid }
            : {}
        )
        this.confirming = false
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
.booking-help {
  line-height: 1.8;
  margin: 12px 0 20px;
}
.booking-warning {
  color: #b45309;
  line-height: 1.7;
}
.booking-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 18px;
}
.booking-time {
  display: block;
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  height: 40px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  padding: 0 10px;
  font: inherit;
  color: inherit;
  background: transparent;
}
.booking-management .el-select {
  width: 100%;
}
@media (max-width: 600px) {
  .booking-grid {
    grid-template-columns: 1fr;
  }
}
</style>
