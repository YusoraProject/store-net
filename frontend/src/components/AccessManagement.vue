<template>
  <el-card class="access-panel" shadow="never">
    <div slot="header">
      <strong>门锁与计费区域</strong
      ><el-button style="float: right" size="mini" @click="load"
        >刷新</el-button
      >
    </div>
    <el-alert
      :title="error || status.message || '正在加载门锁配置'"
      :type="error ? 'error' : 'warning'"
      :closable="false"
      show-icon
    />
    <template v-if="status.initialized">
      <el-tabs v-model="tab">
        <el-tab-pane label="通通锁授权" name="authorization">
          <p>
            状态：{{
              status.credential_configured ? '已配置（密钥不回显）' : '未配置'
            }}。填写通通锁 App 账号，不是开放平台登录账号。
          </p>
          <el-alert
            title="需要 HTTPS 和服务器端启用真实调用。账号密码仅用于本次授权，不保存；系统会提前续期，续期结果不明时需要人工重新授权。"
            type="warning"
            :closable="false"
          />
          <p v-if="status.credential_configured">
            续期状态：{{ refreshLabel(status.refresh_status) }}；授权有效至：{{
              status.expires_at
                ? new Date(status.expires_at * 1000).toLocaleString()
                : '暂不可用'
            }}。
          </p>
          <el-alert
            v-if="status.refresh_error"
            :title="status.refresh_error"
            type="error"
            :closable="false"
          />
          <el-button
            v-if="status.credential_configured"
            size="small"
            :loading="renewing"
            @click="refreshAuthorization"
          >
            检查授权续期
          </el-button>
          <el-form
            label-width="130px"
            style="max-width: 520px; margin-top: 16px"
          >
            <el-form-item label="服务区域"
              ><el-select v-model="auth.region"
                ><el-option label="中国" value="cn" /><el-option
                  label="欧洲"
                  value="eu" /></el-select
            ></el-form-item>
            <el-form-item label="应用编号"
              ><el-input v-model="auth.client_id" autocomplete="off"
            /></el-form-item>
            <el-form-item label="应用密钥"
              ><el-input
                v-model="auth.client_secret"
                type="password"
                autocomplete="new-password"
            /></el-form-item>
            <el-form-item label="通通锁账号"
              ><el-input v-model="auth.username" autocomplete="off"
            /></el-form-item>
            <el-form-item label="通通锁密码"
              ><el-input
                v-model="auth.password"
                type="password"
                autocomplete="new-password"
            /></el-form-item>
            <el-form-item
              ><el-button
                type="primary"
                :loading="saving"
                @click="authorizeLock"
                >授权并测试连接</el-button
              ></el-form-item
            >
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="计费区域" name="areas">
          <el-button size="small" type="primary" @click="edit()"
            >新增区域</el-button
          >
          <el-table :data="areas" v-loading="loading">
            <el-table-column prop="name" label="区域" />
            <el-table-column label="状态"
              ><template slot-scope="x">{{
                x.row.enabled ? '启用' : '停用'
              }}</template></el-table-column
            >
            <el-table-column label="门锁"
              ><template slot-scope="x">{{
                x.row.lock_name || '尚未绑定'
              }}</template></el-table-column
            >
            <el-table-column label="操作"
              ><template slot-scope="x"
                ><el-button size="mini" @click="edit(x.row)">编辑</el-button
                ><el-button size="mini" @click="bind(x.row)">绑定门锁</el-button
                ><el-button
                  size="mini"
                  :disabled="!x.row.lock_id || !x.row.enabled"
                  @click="issue(x.row)"
                  >手动发码</el-button
                ></template
              ></el-table-column
            >
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="密码创建记录" name="records">
          <div class="access-filters">
            <el-select
              v-model="filter.area_id"
              clearable
              placeholder="全部区域"
              @change="reloadRecords"
              ><el-option
                v-for="a in areas"
                :key="a.id"
                :label="a.name"
                :value="a.id" /></el-select
            ><el-select
              v-model="filter.status"
              clearable
              placeholder="全部结果"
              @change="reloadRecords"
              ><el-option
                v-for="(label, key) in states"
                :key="key"
                :label="label"
                :value="key"
            /></el-select>
          </div>
          <el-table :data="records.items">
            <el-table-column prop="area_id" label="区域编号" />
            <el-table-column prop="operator_id" label="操作人编号" />
            <el-table-column prop="recipient_id" label="领取人编号" />
            <el-table-column label="来源"
              ><template slot-scope="x">{{
                x.row.source === 'manual'
                  ? '手动创建'
                  : x.row.source === 'switch'
                  ? '换区自动创建'
                  : '上机自动创建'
              }}</template></el-table-column
            >
            <el-table-column label="结果"
              ><template slot-scope="x">{{
                states[x.row.status] || '未知状态'
              }}</template></el-table-column
            >
            <el-table-column prop="created_at" label="创建时间" />
            <el-table-column prop="error" label="说明" /><el-table-column
              label="密码操作"
              ><template slot-scope="x"
                ><el-button
                  v-if="x.row.status === 'ready'"
                  size="mini"
                  @click="reveal(x.row)"
                  >查看密码</el-button
                ><el-button
                  v-else-if="
                    ['review', 'unknown', 'issuing'].includes(x.row.status)
                  "
                  size="mini"
                  @click="reconcile(x.row)"
                  >核对结果</el-button
                ><el-button
                  v-if="
                    ['automatic', 'switch'].includes(x.row.source) &&
                    ['unknown', 'review'].includes(x.row.status)
                  "
                  size="mini"
                  type="danger"
                  @click="cancelPending(x.row)"
                  >取消申请</el-button
                ></template
              ></el-table-column
            >
          </el-table>
          <el-pagination
            :current-page.sync="page"
            :page-size="20"
            :total="records.total"
            layout="prev, pager, next, total"
            @current-change="loadRecords"
          />
        </el-tab-pane>
      </el-tabs>
    </template>
    <el-dialog
      title="计费区域"
      :visible.sync="visible"
      width="min(680px, 94vw)"
      append-to-body
    >
      <el-alert
        title="修改价格只影响下一次上机；进行中的消费保持上机时的价格。"
        type="warning"
        :closable="false"
      />
      <el-form label-width="155px" style="margin-top: 16px">
        <el-form-item label="上机自动发码"
          ><el-switch v-model="form.auto_issue" :disabled="!form.lock_id" />
          <p>先绑定门锁再启用；仅可在HTTPS下使用。</p></el-form-item
        >
        <el-form-item label="区域名称"
          ><el-input v-model="form.name" maxlength="120"
        /></el-form-item>
        <el-form-item label="启用"
          ><el-switch v-model="form.enabled"
        /></el-form-item>
        <el-form-item v-for="p in priceFields" :key="p.key" :label="p.label"
          ><el-input-number
            v-model="form.pricing[p.key]"
            :min="0"
            :max="100000"
            :precision="2"
        /></el-form-item>
      </el-form>
      <span slot="footer"
        ><el-button @click="visible = false">取消</el-button
        ><el-button type="primary" :loading="saving" @click="save"
          >保存定价</el-button
        ></span
      >
    </el-dialog>
  </el-card>
</template>
<script>
const priceFields = []
for (const [day, d] of [
  ['workday', '工作日'],
  ['weekend', '周末'],
  ['holiday', '节假日'],
]) {
  for (const [period, p] of [
    ['day', '日间'],
    ['night', '夜间'],
  ]) {
    for (const [rate, r] of [
      ['hourly', '每小时'],
      ['cap', '封顶价'],
    ])
      priceFields.push({
        key: day + '_' + period + '_' + rate,
        label: d + p + r,
      })
  }
}
const fresh = () => ({
  name: '',
  enabled: true,
  pricing: Object.fromEntries(
    priceFields.map((p) => [p.key, p.key.endsWith('hourly') ? 8 : 40])
  ),
})
export default {
  name: 'AccessManagement',
  props: { storeId: { type: Number, required: true } },
  data: () => ({
    auth: {
      region: 'cn',
      client_id: '',
      client_secret: '',
      username: '',
      password: '',
    },
    issueKeys: {},
    status: {},
    error: '',
    areas: [],
    loading: false,
    saving: false,
    renewing: false,
    visible: false,
    form: fresh(),
    tab: 'areas',
    page: 1,
    records: { items: [], total: 0 },
    filter: { area_id: null, status: null },
    priceFields,
    states: {
      pending: '等待处理',
      issuing: '正在发码',
      unknown: '正在核对',
      review: '需店长核对',
      ready: '创建成功',
      failed: '创建失败',
      cancelled: '店长已取消',
    },
  }),
  watch: {
    storeId: {
      immediate: true,
      handler() {
        this.load()
      },
    },
  },
  methods: {
    refreshLabel(value) {
      return (
        {
          ready: '可用',
          due: '等待续期',
          refreshing: '正在续期',
          unknown: '需人工处理',
          reauthorize: '需要重新授权',
          initialization_required: '请检查数据库初始化',
        }[value] || '未检查'
      )
    },
    async refreshAuthorization() {
      const storeId = this.storeId
      this.renewing = true
      try {
        const { data } = await this.$api.post(
          '/access/stores/' + storeId + '/authorization/refresh'
        )
        if (storeId !== this.storeId) return
        if (data.status === 'ready') this.$message.success(data.message)
        else this.$message.warning(data.message)
        await this.load()
      } catch (e) {
        if (storeId === this.storeId) this.$message.error(this.message(e))
      } finally {
        this.renewing = false
      }
    },
    async authorizeLock() {
      this.saving = true
      try {
        await this.$api.post(
          '/access/stores/' + this.storeId + '/authorization',
          this.auth
        )
        this.$message.success('授权及连接测试成功')
        await this.load()
      } catch (e) {
        this.$message.error(this.message(e))
      } finally {
        this.auth.password = ''
        this.auth.client_secret = ''
        this.saving = false
      }
    },
    async bind(area) {
      try {
        const { data } = await this.$api.get(
          '/access/stores/' + this.storeId + '/locks'
        )
        if (!data.length) return this.$message.warning('当前账号没有可用门锁')
        const text = data.map((x) => x.lock_id + '：' + x.name).join('；')
        const result = await this.$prompt(
          '填写门锁编号。当前列表：' + text,
          '绑定门锁',
          { inputPattern: /^[0-9]+$/, inputErrorMessage: '请输入门锁编号' }
        )
        await this.$api.put(
          '/access/stores/' + this.storeId + '/areas/' + area.id + '/lock',
          { lock_id: result.value }
        )
        await this.load()
      } catch (e) {
        if (e !== 'cancel' && e !== 'close')
          this.$message.error(this.message(e))
      }
    },
    async issue(area) {
      try {
        await this.$confirm(
          '为“' +
            area.name +
            '”创建一次性密码？不会创建消费或扣费。结果不确定时请核对原记录。',
          '手动发码'
        )
        if (!this.issueKeys[area.id])
          this.$set(this.issueKeys, area.id, window.crypto.randomUUID())
        const { data } = await this.$api.post(
          '/access/stores/' + this.storeId + '/areas/' + area.id + '/issue',
          { idempotency_key: this.issueKeys[area.id] }
        )
        if (['ready', 'failed'].includes(data.status))
          this.$delete(this.issueKeys, area.id)
        this.$message.info(this.states[data.status] || '请求已提交')
        this.tab = 'records'
        await this.loadRecords()
      } catch (e) {
        if (e !== 'cancel' && e !== 'close')
          this.$message.error(this.message(e))
      }
    },
    async reveal(row) {
      try {
        const { data } = await this.$api.post(
          '/access/stores/' + this.storeId + '/records/' + row.id + '/reveal'
        )
        await this.$alert(
          '一次性密码：' + data.password + '。请勿转发给无关人员。',
          '密码查看（已记录审计）'
        )
      } catch (e) {
        if (e !== 'cancel' && e !== 'close')
          this.$message.error(this.message(e))
      }
    },
    async reconcile(row) {
      try {
        const { data } = await this.$api.post(
          '/access/stores/' + this.storeId + '/records/' + row.id + '/reconcile'
        )
        this.$message.info(data.message)
        await this.loadRecords()
      } catch (e) {
        this.$message.error(this.message(e))
      }
    },
    async cancelPending(row) {
      try {
        await this.$confirm(
          row.source === 'switch'
            ? '取消换区后仍按原区域计费，不会结束消费，也不会撤销可能已生成的新区密码。请先确认门店入场风险。'
            : '取消后不开始计费并释放上机占用，但不会撤销可能已生成的密码。请先确认门店入场风险。',
          '取消待确认申请',
          { type: 'warning' }
        )
        const reason = await this.$prompt('请输入处理原因', '取消申请')
        const { data } = await this.$api.post(
          '/access/stores/' + this.storeId + '/records/' + row.id + '/cancel',
          { acknowledged: true, reason: reason.value }
        )
        this.$message.warning(data.message)
        await this.loadRecords()
      } catch (e) {
        if (e !== 'cancel' && e !== 'close')
          this.$message.error(this.message(e))
      }
    },
    message(e) {
      return typeof e.response?.data?.detail === 'string'
        ? e.response.data.detail
        : '操作失败，请稍后重试'
    },
    async load() {
      this.auth.password = ''
      this.auth.client_secret = ''
      const id = this.storeId
      if (!id) return
      this.loading = true
      this.error = ''
      this.status = {}
      this.areas = []
      try {
        const { data } = await this.$api.get('/access/stores/' + id + '/status')
        if (id !== this.storeId) return
        this.status = data
        if (data.initialized) {
          const areas = await this.$api.get('/access/stores/' + id + '/areas')
          if (id !== this.storeId) return
          this.areas = areas.data
          this.page = 1
          await this.loadRecords()
        }
      } catch (e) {
        if (id === this.storeId) this.error = this.message(e)
      } finally {
        if (id === this.storeId) this.loading = false
      }
    },
    async loadRecords() {
      const id = this.storeId
      try {
        const { data } = await this.$api.get(
          '/access/stores/' + id + '/records',
          {
            params: {
              page: this.page,
              area_id: this.filter.area_id || undefined,
              status: this.filter.status || undefined,
            },
          }
        )
        if (id === this.storeId) this.records = data
      } catch (e) {
        if (id === this.storeId) this.error = this.message(e)
      }
    },
    reloadRecords() {
      this.page = 1
      this.loadRecords()
    },
    edit(row) {
      this.form = row ? JSON.parse(JSON.stringify(row)) : fresh()
      this.visible = true
    },
    async save() {
      this.saving = true
      try {
        const base = '/access/stores/' + this.storeId + '/areas'
        const payload = {
          name: this.form.name,
          enabled: this.form.enabled,
          pricing: this.form.pricing,
          auto_issue: !!this.form.auto_issue,
        }
        if (this.form.id)
          await this.$api.put(base + '/' + this.form.id, payload)
        else await this.$api.post(base, payload)
        this.visible = false
        this.$message.success('区域已保存')
        await this.load()
      } catch (e) {
        this.$message.error(this.message(e))
      } finally {
        this.saving = false
      }
    },
  },
}
</script>
<style scoped>
.access-panel {
  margin-top: 16px;
}
.access-filters {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin: 12px 0;
}
</style>
