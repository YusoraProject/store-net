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
      :type="error ? 'error' : 'info'"
      :closable="false"
      show-icon
    />
    <template v-if="status.initialized">
      <el-tabs v-model="tab">
        <el-tab-pane label="通通锁授权" name="authorization">
          <section class="authorization-summary" aria-label="通通锁授权状态">
            <div class="authorization-heading">
              <div>
                <h3>连接通通锁</h3>
                <p>连接门店账号后，即可选择门锁并配置区域发码。</p>
              </div>
              <span
                class="authorization-badge"
                :class="{ configured: status.credential_configured }"
              >
                <span class="authorization-dot" aria-hidden="true"></span>
                {{ status.credential_configured ? '已配置' : '待授权' }}
              </span>
            </div>
            <div
              v-if="status.credential_configured"
              class="authorization-details"
            >
              <div>
                <span>续期状态</span
                ><strong>{{ refreshLabel(status.refresh_status) }}</strong>
              </div>
              <div>
                <span>授权有效至</span
                ><strong>{{
                  status.expires_at
                    ? new Date(status.expires_at * 1000).toLocaleString()
                    : '暂不可用'
                }}</strong>
              </div>
              <el-button
                size="small"
                :loading="renewing"
                @click="refreshAuthorization"
                >检查授权续期</el-button
              >
            </div>
            <div v-else class="authorization-guide">
              <strong>还没有通通锁 App 账号？</strong>
              <p>
                先注册 App 账号，并在 App
                中添加门锁或获得门锁授权，再回到这里连接。仅有开放平台应用编号和密钥，暂时无法完成授权测试。
              </p>
            </div>
          </section>
          <el-alert
            v-if="status.refresh_error"
            :title="status.refresh_error"
            type="error"
            :closable="false"
            show-icon
          />
          <el-form
            class="authorization-form"
            label-position="top"
            @submit.native.prevent="authorizeLock"
          >
            <div class="authorization-columns">
              <section class="authorization-group">
                <h4><span>1</span>开放平台应用</h4>
                <p class="authorization-help">
                  在通通锁开放平台的应用详情中获取。
                </p>
                <el-form-item label="服务区域">
                  <el-select v-model="auth.region"
                    ><el-option label="中国" value="cn" /><el-option
                      label="欧洲"
                      value="eu"
                  /></el-select>
                </el-form-item>
                <el-form-item label="应用编号（client_id）">
                  <el-input
                    v-model="auth.client_id"
                    placeholder="请输入应用编号"
                    autocomplete="off"
                  />
                </el-form-item>
                <el-form-item label="应用密钥（client_secret）">
                  <el-input
                    v-model="auth.client_secret"
                    type="password"
                    placeholder="请输入应用密钥"
                    autocomplete="new-password"
                  />
                </el-form-item>
              </section>
              <section class="authorization-group">
                <h4><span>2</span>通通锁 App 账号</h4>
                <p class="authorization-help">
                  填写手机 App 的登录账号，不是开放平台账号。
                </p>
                <el-form-item label="通通锁账号">
                  <el-input
                    v-model="auth.username"
                    placeholder="请输入通通锁 App 账号"
                    autocomplete="off"
                  />
                </el-form-item>
                <el-form-item label="通通锁密码">
                  <el-input
                    v-model="auth.password"
                    type="password"
                    placeholder="请输入 App 登录密码"
                    autocomplete="new-password"
                  />
                </el-form-item>
                <p class="authorization-privacy">
                  <i class="el-icon-lock" aria-hidden="true"></i
                  >账号密码仅用于本次授权；应用密钥和令牌加密保存，不回显。
                </p>
              </section>
            </div>
            <div class="authorization-footer">
              <div>
                <strong>连接前准备</strong>
                <p>
                  需通过 HTTPS
                  访问，并在服务器启用通通锁连接。授权成功后系统会提前续期，异常时请根据提示重新授权。
                </p>
              </div>
              <el-button type="primary" native-type="submit" :loading="saving"
                >授权并测试连接</el-button
              >
            </div>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="计费区域" name="areas">
          <el-button size="small" type="primary" @click="edit()"
            >新增区域</el-button
          >
          <el-table :data="areas" v-loading="loading">
            <el-table-column min-width="120" prop="name" label="区域" />
            <el-table-column min-width="120" label="状态"
              ><template slot-scope="x">{{
                x.row.enabled ? '启用' : '停用'
              }}</template></el-table-column
            >
            <el-table-column min-width="120" label="门锁"
              ><template slot-scope="x">{{
                x.row.lock_name || '尚未绑定'
              }}</template></el-table-column
            >
            <el-table-column
              min-width="280"
              class-name="table-actions"
              label="操作"
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
            <el-table-column min-width="120" prop="area_id" label="区域编号" />
            <el-table-column
              min-width="120"
              prop="operator_id"
              label="操作人编号"
            />
            <el-table-column
              min-width="120"
              prop="recipient_id"
              label="领取人编号"
            />
            <el-table-column min-width="120" label="来源"
              ><template slot-scope="x">{{
                x.row.source === 'manual'
                  ? '手动创建'
                  : x.row.source === 'switch'
                  ? '换区自动创建'
                  : '上机自动创建'
              }}</template></el-table-column
            >
            <el-table-column min-width="120" label="结果"
              ><template slot-scope="x">{{
                states[x.row.status] || '未知状态'
              }}</template></el-table-column
            >
            <el-table-column
              min-width="120"
              prop="created_at"
              label="创建时间"
            />
            <el-table-column
              min-width="120"
              prop="error"
              label="说明"
            /><el-table-column
              min-width="360"
              class-name="table-actions"
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
      width="min(960px, 94vw)"
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
      </el-form>
      <pricing-editor ref="pricingEditor" v-model="form.pricing" />
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
import PricingEditor from './PricingEditor.vue'
import { createPricing } from '../pricing-rules'
const fresh = () => ({
  name: '',
  enabled: true,
  pricing: createPricing(),
})
export default {
  name: 'AccessManagement',
  components: { PricingEditor },
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
      if (!this.auth.client_id.trim() || !this.auth.client_secret.trim()) {
        return this.$message.warning('请先填写开放平台应用编号和应用密钥')
      }
      if (!this.auth.username.trim() || !this.auth.password) {
        return this.$message.warning('请填写通通锁 App 账号和密码后再测试连接')
      }
      if (window.location.protocol !== 'https:') {
        return this.$message.warning('请通过 HTTPS 打开页面后再提交门锁授权')
      }
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
      if (!this.$refs.pricingEditor.validate()) return
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
        this.$emit('pricing-updated')
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
.authorization-summary {
  margin: 12px 0 24px;
  padding: 22px 24px;
  border: 1px solid #dce5ef;
  border-radius: 12px;
  background: #f7faff;
}
.authorization-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.authorization-heading h3 {
  margin: 0 0 8px;
  font-size: 18px;
  color: #24354b;
}
.authorization-heading p,
.authorization-guide p {
  margin: 0;
  color: #606f82;
  font-size: 13px;
  line-height: 1.8;
}
.authorization-badge {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  flex-shrink: 0;
  padding: 6px 12px;
  border-radius: 20px;
  background: #fff1d9;
  color: #8c5b0c;
  font-size: 12px;
  font-weight: 600;
}
.authorization-badge.configured {
  background: #e3f4eb;
  color: #267448;
}
.authorization-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}
.authorization-guide {
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px solid #e0e8f2;
}
.authorization-guide strong {
  display: block;
  margin-bottom: 5px;
  color: #384c65;
  font-size: 13px;
}
.authorization-details {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 24px;
  margin-top: 20px;
}
.authorization-details div {
  display: grid;
  gap: 6px;
  font-size: 13px;
}
.authorization-details span {
  color: #68788b;
}
.authorization-details strong {
  color: #34465e;
  font-weight: 500;
}
.authorization-form {
  margin-top: 20px;
}
.authorization-columns {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr));
  gap: 24px;
}
.authorization-group {
  min-width: 0;
  padding: 22px 24px 6px;
  border: 1px solid #e6eaf0;
  border-radius: 12px;
}
.authorization-group h4 {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0 0 10px;
  color: #2c3e56;
  font-size: 15px;
}
.authorization-group h4 span {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 7px;
  background: #edf3ff;
  color: #4677c8;
  font-size: 12px;
}
.authorization-help {
  min-height: 40px;
  margin: 0 0 14px;
  color: #68788b;
  font-size: 13px;
  line-height: 1.6;
}
.authorization-group .el-select {
  width: 100%;
}
.authorization-group ::v-deep .el-form-item__label {
  padding-bottom: 6px;
  line-height: 22px;
  color: #45556b;
}
.authorization-privacy {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 12px;
  margin: 0 0 16px;
  background: #f7f9fb;
  border-radius: 8px;
  color: #68788b;
  font-size: 12px;
  line-height: 1.8;
}
.authorization-privacy i {
  margin-top: 4px;
}
.authorization-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 24px;
  margin-top: 24px;
  padding: 18px 0 4px;
  border-top: 1px solid #e8edf3;
}
.authorization-footer strong {
  color: #45556b;
  font-size: 13px;
}
.authorization-footer p {
  max-width: 640px;
  margin: 6px 0 0;
  color: #68788b;
  font-size: 12px;
  line-height: 1.8;
}
.authorization-footer .el-button {
  flex-shrink: 0;
}
.dark-mode .authorization-summary,
.dark-mode .authorization-privacy {
  background: #202d40;
}
.dark-mode .authorization-summary,
.dark-mode .authorization-group,
.dark-mode .authorization-guide,
.dark-mode .authorization-footer {
  border-color: #38465a;
}
.dark-mode .authorization-heading h3,
.dark-mode .authorization-group h4,
.dark-mode .authorization-guide strong,
.dark-mode .authorization-details strong,
.dark-mode .authorization-footer strong {
  color: #e2e8f0;
}
.dark-mode .authorization-heading p,
.dark-mode .authorization-guide p,
.dark-mode .authorization-help,
.dark-mode .authorization-privacy,
.dark-mode .authorization-details span,
.dark-mode .authorization-footer p {
  color: #b5c1d2;
}
@media (max-width: 760px) {
  .authorization-columns {
    grid-template-columns: 1fr;
    gap: 16px;
  }
  .authorization-summary,
  .authorization-group {
    padding: 18px 16px;
  }
  .authorization-help {
    min-height: 0;
  }
  .authorization-footer {
    flex-direction: column;
    align-items: stretch;
    gap: 16px;
  }
}
</style>
