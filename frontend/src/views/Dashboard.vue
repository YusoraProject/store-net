<template>
  <div class="shell" :class="{ 'dark-mode': darkMode }">
    <header class="topbar">
      <span class="mobile-logo">StoreNet 控制台</span>
      <div class="header-user">
        <el-button
          circle
          size="small"
          :icon="darkMode ? 'el-icon-sunny' : 'el-icon-moon'"
          aria-label="切换主题"
          @click="toggleTheme"
        /><el-avatar :src="profile.avatar" icon="el-icon-user" />
        <div>
          <div class="name">{{ label(profile.name) }}</div>
          <div class="role">{{ label(profile.role_name) }}</div>
        </div>
        <el-button type="text" @click="logout">退出登录</el-button>
      </div>
    </header>
    <div class="mobile-nav" role="navigation" aria-label="主导航">
      <el-button
        v-for="item in menus"
        :key="item.key"
        :type="active === item.key ? 'primary' : 'default'"
        :aria-current="active === item.key ? 'page' : null"
        size="mini"
        @click="active = item.key"
        ><i :class="item.icon" aria-hidden="true" /><span>{{
          item.label
        }}</span></el-button
      >
    </div>
    <div class="layout">
      <aside class="nav">
        <div class="logo">StoreNet 控制台</div>
        <el-menu
          :default-active="active"
          :default-openeds="['common', 'management']"
          @select="active = $event"
          ><el-submenu index="common"
            ><template slot="title"><i class="el-icon-s-home" />常用</template
            ><el-menu-item
              v-for="item in menus.filter((x) =>
                ['home', 'profile', 'stores', 'bookings', 'venue'].includes(
                  x.key
                )
              )"
              :key="item.key"
              :index="item.key"
              ><i :class="item.icon" />{{ item.label }}</el-menu-item
            ></el-submenu
          ><el-submenu v-if="menus.length > 5" index="management"
            ><template slot="title"><i class="el-icon-setting" />管理</template
            ><el-menu-item
              v-for="item in menus.filter(
                (x) =>
                  !['home', 'profile', 'stores', 'bookings', 'venue'].includes(
                    x.key
                  )
              )"
              :key="item.key"
              :index="item.key"
              ><i :class="item.icon" />{{ item.label }}</el-menu-item
            ></el-submenu
          ></el-menu
        >
        <div class="logout">
          <el-button type="text" @click="logout">退出登录</el-button>
        </div>
      </aside>
      <main class="content">
        <registration-stats v-if="active === 'stats' && can('users.manage')" />
        <venue-status
          v-if="active === 'venue'"
          :stores="stores"
          :initial-store-id="selectedStore"
        />
        <section v-if="active === 'home'">
          <div class="hero">
            <h2>你好，{{ label(profile.name) }}</h2>
            <p>查看当前计时、门店权益并完成自助结账。</p>
          </div>
          <el-alert
            v-if="accessWaiting"
            type="warning"
            :closable="false"
            :title="
              accessPending.message ||
              (current
                ? '正在确认新区密码，仍按原区域计费。请不要重复换区。'
                : '正在确认入场密码，尚未开始计费。请不要重复上机。')
            "
          />
          <el-button v-if="accessWaiting" @click="resumeAccess"
            >核对发码结果</el-button
          >
          <el-button v-if="current" @click="showPassword"
            >查看本次入场密码</el-button
          >
          <div class="grid">
            <el-card class="panel"
              ><div class="muted">当前状态</div>
              <div class="metric">
                {{
                  current
                    ? current.booking_id
                      ? '包场免费上机'
                      : '计时中'
                    : '未上机'
                }}
              </div>
              <p v-if="current">
                区域：{{ current.area_name || '默认区域' }}；开始于
                {{ format(current.started_at) }}
              </p></el-card
            ><el-card class="panel"
              ><div class="muted">已加入门店</div>
              <div class="metric">{{ stores.length }}</div></el-card
            >
          </div>
          <el-card class="panel" style="margin-top: 16px"
            ><div slot="header">自助上机</div>
            <template v-if="current"
              ><p>
                门店编号：{{ current.store_id }} 已计时：{{
                  quote.duration_minutes || 0
                }}
                分钟
              </p>
              <h3>当前费用：¥{{ Number(quote.amount_due || 0).toFixed(2) }}</h3>
              <p v-if="current.booking_id">
                包场免费上机至
                {{ format(current.free_until) }}，到时自动结束，不扣余额或次卡。
              </p>
              <p v-else>换区不结账，各区费用累计后统一结算。</p>
              <el-select v-model="selectedArea" placeholder="选择要切换的区域">
                <el-option
                  v-for="a in areaChoices"
                  :key="a.id"
                  :value="a.id"
                  :label="a.name"
                  :disabled="
                    a.id === current.area_id || (a.booking && a.booking.blocked)
                  "
                />
              </el-select>
              <el-button
                :loading="starting"
                :disabled="
                  !selectedArea ||
                  selectedArea === current.area_id ||
                  accessWaiting ||
                  (selectedAreaInfo &&
                    selectedAreaInfo.booking &&
                    selectedAreaInfo.booking.blocked) ||
                  selectedStore !== current.store_id
                "
                @click="switchMine"
                >切换区域</el-button
              >
              <el-alert
                v-if="
                  selectedAreaInfo &&
                  selectedAreaInfo.booking &&
                  selectedAreaInfo.booking.message
                "
                :title="selectedAreaInfo.booking.message"
                :type="selectedAreaInfo.booking.blocked ? 'warning' : 'success'"
                :closable="false"
              />
              <pricing-summary
                v-if="
                  selectedAreaInfo &&
                  !(selectedAreaInfo.booking && selectedAreaInfo.booking.free)
                "
                :pricing="selectedAreaInfo.pricing"
              />
              <p v-if="selectedAreaInfo">
                {{
                  selectedAreaInfo.auto_issue
                    ? '发码成功后切换计时。'
                    : '此区域不自动发码。'
                }}
              </p>
              <el-table
                v-if="current.segments && current.segments.length"
                :data="current.segments"
              >
                <el-table-column
                  min-width="120"
                  prop="area_name"
                  label="停留区域"
                />
                <el-table-column min-width="120" label="进入时间"
                  ><template slot-scope="x">{{
                    format(x.row.started_at)
                  }}</template></el-table-column
                >
                <el-table-column min-width="120" label="离开时间"
                  ><template slot-scope="x">{{
                    x.row.ended_at ? format(x.row.ended_at) : '计时中'
                  }}</template></el-table-column
                >
              </el-table>
              <el-button @click="loadQuote">刷新费用</el-button
              ><el-button
                type="primary"
                :disabled="accessWaiting"
                @click="checkoutMine"
                >{{
                  current.booking_id ? '结束免费上机' : '余额/次卡结账'
                }}</el-button
              ></template
            ><template v-else
              ><el-select v-model="selectedStore" placeholder="选择门店"
                ><el-option
                  v-for="s in stores"
                  :key="s.id"
                  :label="s.name"
                  :value="s.id"
              /></el-select>
              <el-select v-model="selectedArea" placeholder="选择计费区域"
                ><el-option
                  v-for="a in areaChoices"
                  :key="a.id"
                  :label="a.name"
                  :value="a.id"
              /></el-select>
              <el-alert
                v-if="
                  selectedAreaInfo &&
                  selectedAreaInfo.booking &&
                  selectedAreaInfo.booking.message
                "
                :title="selectedAreaInfo.booking.message"
                :type="selectedAreaInfo.booking.blocked ? 'warning' : 'success'"
                :closable="false"
              />
              <pricing-summary
                v-if="
                  selectedAreaInfo &&
                  !(selectedAreaInfo.booking && selectedAreaInfo.booking.free)
                "
                :pricing="selectedAreaInfo.pricing"
              />
              <p v-if="selectedAreaInfo">
                {{
                  selectedAreaInfo.auto_issue
                    ? '入场门锁：' +
                      selectedAreaInfo.lock_name +
                      '；发码成功后开始计费。'
                    : '此区域不自动发码。'
                }}
              </p>
              <el-button
                type="primary"
                :loading="starting"
                :disabled="
                  !selectedStore ||
                  !selectedArea ||
                  !!accessPending ||
                  starting ||
                  (selectedAreaInfo &&
                    selectedAreaInfo.booking &&
                    selectedAreaInfo.booking.blocked)
                "
                @click="startMine"
                >{{
                  selectedAreaInfo &&
                  selectedAreaInfo.booking &&
                  selectedAreaInfo.booking.free
                    ? '包场免费上机'
                    : '开始计时'
                }}</el-button
              ></template
            ></el-card
          >
        </section>
        <section v-if="active === 'bookings'">
          <div class="toolbar">
            <h2>包场</h2>
            <el-select v-model="selectedStore" placeholder="选择门店"
              ><el-option
                v-for="s in stores"
                :key="s.id"
                :value="s.id"
                :label="s.name"
            /></el-select>
          </div>
          <member-bookings
            v-if="selectedStore && profile.id"
            :key="selectedStore"
            :store-id="selectedStore"
            :user-id="profile.id"
            @go-home="
              active = 'home'
              refreshAdmission()
            "
            @changed="refreshAdmission"
          />
        </section>
        <section v-if="active === 'profile'">
          <el-card class="panel"
            ><div slot="header">个人资料</div>
            <el-form label-width="90px" style="max-width: 520px"
              ><el-form-item label="用户名"
                ><el-input :value="profile.username" disabled /></el-form-item
              ><el-form-item label="邮箱"
                ><el-input :value="profile.email" disabled /></el-form-item
              ><el-form-item label="姓名"
                ><el-input v-model="profileForm.name" /></el-form-item
              ><el-form-item label="QQ"
                ><el-input v-model="profileForm.qq" /></el-form-item
              ><el-form-item
                ><el-button type="primary" @click="saveProfile"
                  >保存</el-button
                ></el-form-item
              ></el-form
            ></el-card
          >
        </section>
        <section v-if="active === 'stores'">
          <div class="toolbar">
            <h2>我的门店</h2>
            <el-button
              v-if="can('stores.manage')"
              type="primary"
              @click="createStore"
              >新建门店</el-button
            >
          </div>
          <div class="grid">
            <el-card v-for="s in stores" :key="s.id" class="panel"
              ><h3>{{ s.name }}</h3>
              <p class="muted">{{ s.address || '未设置地址' }}</p>
              <el-button @click="openStore(s)">进入管理</el-button></el-card
            >
          </div>
        </section>
        <section v-if="active === 'manage'">
          <div class="toolbar">
            <h2>{{ selected.name || '门店管理' }}</h2>
            <el-select v-model="selectedStore" @change="selectStore"
              ><el-option
                v-for="s in stores"
                :key="s.id"
                :label="s.name"
                :value="s.id"
            /></el-select>
          </div>
          <access-management
            ref="accessManagement"
            @pricing-updated="pricingUpdated"
            v-if="selectedStore && can('stores.manage')"
            :key="selectedStore"
            :store-id="selectedStore"
          />
          <el-tabs
            v-if="selectedStore"
            ref="storeManagementTabs"
            class="store-management-tabs"
            v-model="storeTab"
            @tab-click="loadStoreTab"
          >
            <el-tab-pane label="概览" name="report"
              ><div class="toolbar">
                <el-button type="primary" @click="editStore"
                  >编辑门店资料</el-button
                >
              </div>
              <div class="grid">
                <el-card class="panel"
                  ><div class="muted">会员</div>
                  <div class="metric">{{ report.members || 0 }}</div></el-card
                ><el-card class="panel"
                  ><div class="muted">当前上机</div>
                  <div class="metric">
                    {{ report.active_sessions || 0 }}
                  </div></el-card
                ><el-card class="panel"
                  ><div class="muted">累计营收</div>
                  <div class="metric">
                    ¥{{ Number(report.revenue || 0).toFixed(2) }}
                  </div>
                  <div class="muted">
                    含包场净收款 ¥{{
                      Number(report.booking_revenue || 0).toFixed(2)
                    }}
                  </div></el-card
                >
              </div></el-tab-pane
            >
            <el-tab-pane
              v-if="can('store.consumptions.manage')"
              label="包场"
              name="bookings"
            >
              <booking-management
                v-if="storeTab === 'bookings'"
                :key="selectedStore"
                :store-id="selectedStore"
              />
            </el-tab-pane>
            <el-tab-pane label="会员" name="members"
              ><div class="toolbar">
                <el-select v-model="newMember" filterable placeholder="选择用户"
                  ><el-option
                    v-for="u in users"
                    :key="u.id"
                    :label="`${u.name} (${u.username})`"
                    :value="u.id" /></el-select
                ><el-button type="primary" @click="addMember"
                  >添加会员</el-button
                >
              </div>
              <el-table :data="members"
                ><el-table-column
                  min-width="120"
                  prop="name"
                  label="姓名"
                /><el-table-column
                  min-width="120"
                  prop="username"
                  label="用户名"
                /><el-table-column min-width="120" label="身份"
                  ><template slot-scope="x">{{
                    label(x.row.store_role)
                  }}</template></el-table-column
                ><el-table-column min-width="120" label="本金"
                  ><template slot-scope="x"
                    >¥{{ x.row.paid.toFixed(2) }}</template
                  ></el-table-column
                ><el-table-column min-width="120" label="赠金"
                  ><template slot-scope="x"
                    >¥{{ x.row.bonus.toFixed(2) }}</template
                  ></el-table-column
                ><el-table-column
                  min-width="120"
                  prop="times_count"
                  label="次卡"
                /><el-table-column
                  min-width="210"
                  class-name="table-actions"
                  label="操作"
                  ><template slot-scope="x"
                    ><el-button size="mini" @click="adjust(x.row)"
                      >调整权益</el-button
                    ><el-button
                      size="mini"
                      type="primary"
                      @click="managerStart(x.row)"
                      >上机</el-button
                    >
                  </template></el-table-column
                ></el-table
              ></el-tab-pane
            >
            <el-tab-pane label="定价" name="pricing">
              <el-alert
                v-if="pricingError"
                :title="pricingError"
                type="info"
                :closable="false"
              />
              <template v-else-if="!pricingLoading">
                <pricing-editor ref="storePricingEditor" v-model="pricing" />
                <div class="pricing-save-panel">
                  <div>
                    <strong>保存计费规则</strong>
                    <p class="muted">
                      包含每日时段与特殊日期。保存后用于新计费段。
                    </p>
                  </div>
                  <el-button
                    type="primary"
                    :loading="pricingSaving"
                    @click="savePricing"
                    >保存计费规则</el-button
                  >
                </div>
              </template>
              <p v-else>正在加载计费规则…</p>
              <booking-pricing
                v-if="storeTab === 'pricing' && can('store.pricing.manage')"
                :key="selectedStore"
                :store-id="selectedStore"
              />
            </el-tab-pane>
            <el-tab-pane label="消费记录" name="consumptions"
              ><el-table :data="consumptions"
                ><el-table-column
                  min-width="120"
                  prop="user_id"
                  label="用户编号"
                /><el-table-column min-width="120" label="开始"
                  ><template slot-scope="x">{{
                    format(x.row.started_at)
                  }}</template></el-table-column
                ><el-table-column
                  min-width="120"
                  prop="duration_minutes"
                  label="分钟"
                /><el-table-column min-width="120" label="费用"
                  ><template slot-scope="x"
                    >¥{{ x.row.amount_due.toFixed(2) }}</template
                  ></el-table-column
                ><el-table-column min-width="120" label="状态"
                  ><template slot-scope="x">{{
                    label(x.row.status)
                  }}</template></el-table-column
                ><el-table-column
                  min-width="210"
                  class-name="table-actions"
                  label="操作"
                  ><template slot-scope="x"
                    ><el-button
                      v-if="x.row.status === 'open'"
                      size="mini"
                      type="primary"
                      @click="managerCheckout(x.row)"
                      >结账</el-button
                    ><el-button
                      v-if="x.row.status === 'open'"
                      size="mini"
                      @click="managerSwitch(x.row)"
                      >换区</el-button
                    ></template
                  ></el-table-column
                ></el-table
              ></el-tab-pane
            >
            <el-tab-pane label="资产流水" name="ledgers"
              ><el-table :data="ledgers"
                ><el-table-column
                  min-width="120"
                  prop="user_id"
                  label="用户编号" /><el-table-column
                  min-width="120"
                  label="类型"
                  ><template slot-scope="x">{{
                    label(x.row.action)
                  }}</template></el-table-column
                ><el-table-column
                  min-width="120"
                  prop="paid_delta"
                  label="本金变化" /><el-table-column
                  min-width="120"
                  prop="bonus_delta"
                  label="赠金变化" /><el-table-column
                  min-width="120"
                  prop="times_delta"
                  label="次卡变化" /><el-table-column
                  min-width="120"
                  prop="remark"
                  label="原因" /></el-table
            ></el-tab-pane>
          </el-tabs>
        </section>
        <section v-if="active === 'users'">
          <h2>用户管理</h2>
          <el-table :data="users"
            ><el-table-column
              min-width="120"
              prop="username"
              label="用户名"
            /><el-table-column
              min-width="120"
              prop="name"
              label="姓名"
            /><el-table-column
              min-width="120"
              prop="email"
              label="邮箱"
            /><el-table-column min-width="120" label="角色"
              ><template slot-scope="x">{{
                label(x.row.role_name)
              }}</template></el-table-column
            ><el-table-column min-width="120" label="状态"
              ><template slot-scope="x">{{
                x.row.is_active ? '已启用' : '已停用'
              }}</template></el-table-column
            ><el-table-column
              min-width="210"
              class-name="table-actions"
              label="操作"
              ><template slot-scope="x"
                ><el-button size="mini" @click="editUser(x.row)"
                  >角色/状态</el-button
                ></template
              ></el-table-column
            ></el-table
          >
        </section>
        <section v-if="active === 'roles'">
          <div class="toolbar">
            <h2>角色权限</h2>
            <el-button type="primary" @click="createRole">新建角色</el-button>
          </div>
          <el-table :data="roles"
            ><el-table-column min-width="120" label="名称"
              ><template slot-scope="x">{{
                label(x.row.name)
              }}</template></el-table-column
            ><el-table-column min-width="120" label="说明"
              ><template slot-scope="x">{{
                label(x.row.description)
              }}</template></el-table-column
            ><el-table-column min-width="120" label="权限"
              ><template slot-scope="x">{{
                x.row.permissions.map(label).join('、')
              }}</template></el-table-column
            ><el-table-column
              min-width="210"
              class-name="table-actions"
              label="操作"
              ><template slot-scope="x"
                ><el-button
                  size="mini"
                  :disabled="x.row.name === 'admin'"
                  @click="editRole(x.row)"
                  >编辑权限</el-button
                ></template
              ></el-table-column
            ></el-table
          >
        </section>
      </main>
    </div>
  </div>
</template>
<script>
import '../ui/dashboard'
const labels = {
  Administrator: '管理员',
  'System administrator': '系统管理员',
  'Store member': '门店会员',
  consume: '消费扣款',
  booking_deposit: '包场订金',
  booking_refund: '包场退款',
  booking: '包场免费',
  admin: '管理员',
  member: '会员',
  manager: '店长',
  open: '计时中',
  paid: '已结账',
  adjust: '权益调整',
  checkout: '消费结账',
  'users.manage': '用户管理',
  'roles.manage': '角色管理',
  'stores.manage': '门店管理',
  'store.members.manage': '会员管理',
  'store.pricing.manage': '定价管理',
  'store.consumptions.manage': '消费管理',
  'store.ledgers.view': '查看流水',
  'store.reports.view': '查看报表',
}
const RegistrationStats = () => import('./RegistrationStats.vue')
import PricingEditor from '../components/PricingEditor.vue'
import PricingSummary from '../components/PricingSummary.vue'
import { createPricing } from '../pricing-rules'
import { displayTime } from '../booking-utils'
export default {
  name: 'DashboardView',
  components: {
    RegistrationStats,
    PricingEditor,
    PricingSummary,
    BookingManagement: () => import('../components/BookingManagement.vue'),
    BookingPricing: () => import('../components/BookingPricing.vue'),
    MemberBookings: () => import('../components/MemberBookings.vue'),
    VenueStatus: () => import('../components/VenueStatus.vue'),
    AccessManagement: () => import('../components/AccessManagement.vue'),
  },
  data: () => ({
    darkMode: localStorage.getItem('store_net_dark') === 'true',
    active: 'home',
    profile: { name: '' },
    permissions: [],
    stores: [],
    selectedStore: null,
    selectedArea: null,
    areaChoices: [],
    accessPending: null,
    starting: false,
    accessTimer: null,
    selected: {},
    current: null,
    quote: {},
    profileForm: { name: '', qq: '' },
    storeTab: 'report',
    report: {},
    members: [],
    users: [],
    roles: [],
    newMember: null,
    pricing: createPricing(),
    pricingLoading: false,
    pricingSaving: false,
    pricingError: '',
    consumptions: [],
    ledgers: [],
  }),
  watch: {
    storeTab() {
      this.$nextTick(() => {
        if (!window.matchMedia('(max-width: 760px)').matches) return
        const root = this.$refs.storeManagementTabs?.$el
        const nav = root?.querySelector('.el-tabs__nav-scroll')
        const tab = nav?.querySelector('.el-tabs__item.is-active')
        if (!nav || !tab) return
        const frame = nav.getBoundingClientRect()
        const item = tab.getBoundingClientRect()
        if (item.left < frame.left || item.right > frame.right)
          nav.scrollLeft +=
            item.left - frame.left - (frame.width - item.width) / 2
      })
    },
    active(value) {
      if (value === 'home') this.loadCurrent().catch(this.error)
    },
    selectedStore() {
      this.loadAreas()
    },
  },
  beforeDestroy() {
    clearInterval(this.accessTimer)
  },
  computed: {
    accessWaiting() {
      return (
        !!this.accessPending &&
        ['pending', 'issuing', 'unknown', 'review'].includes(
          this.accessPending.status
        )
      )
    },
    selectedAreaInfo() {
      return this.areaChoices.find((a) => a.id === this.selectedArea)
    },
    menus() {
      const items = [
        { key: 'home', label: '首页', icon: 'el-icon-house' },
        { key: 'venue', label: '场况', icon: 'el-icon-monitor' },
        { key: 'profile', label: '个人资料', icon: 'el-icon-user' },
        { key: 'stores', label: '我的门店', icon: 'el-icon-office-building' },
        { key: 'bookings', label: '包场', icon: 'el-icon-date' },
      ]
      if (
        this.permissions.some(
          (x) => x.startsWith('store.') || x === 'stores.manage'
        )
      )
        items.push({
          key: 'manage',
          label: '门店管理',
          icon: 'el-icon-s-management',
        })
      if (this.can('users.manage'))
        items.push({
          key: 'stats',
          label: '注册统计',
          icon: 'el-icon-data-analysis',
        })
      if (this.can('users.manage'))
        items.push({
          key: 'users',
          label: '用户管理',
          icon: 'el-icon-user-solid',
        })
      if (this.can('roles.manage'))
        items.push({ key: 'roles', label: '角色权限', icon: 'el-icon-lock' })
      return items
    },
  },
  async created() {
    await this.bootstrap()
    this.accessTimer = setInterval(() => {
      if (this.accessWaiting) this.loadCurrent().catch(this.error)
      else if (this.active === 'home') this.refreshAdmission().catch(this.error)
    }, 15000)
  },
  methods: {
    label(v) {
      return labels[v] || v
    },
    toggleTheme() {
      this.darkMode = !this.darkMode
      localStorage.setItem('store_net_dark', String(this.darkMode))
    },
    can(p) {
      return this.permissions.includes(p)
    },
    key() {
      return `${Date.now()}-${Math.random()
        .toString(36)
        .slice(2)}-${Math.random().toString(36).slice(2)}`
    },
    error(e) {
      this.$message.error(e.response?.data?.detail || '操作失败')
    },
    format(v) {
      return displayTime(v)
    },
    async bootstrap() {
      try {
        const [me, perms, stores] = await Promise.all([
          this.$api.get('/users/me'),
          this.$api.get('/users/me/permissions'),
          this.$api.get('/me/stores'),
        ])
        this.profile = me.data
        this.profileForm = { name: me.data.name, qq: me.data.qq || '' }
        this.permissions = perms.data.permissions
        this.stores = stores.data
        if (this.stores[0]) this.selectedStore = this.stores[0].id
        await this.loadCurrent()
        if (this.can('users.manage'))
          this.users = (await this.$api.get('/admin/users')).data
        if (this.can('roles.manage'))
          this.roles = (await this.$api.get('/admin/roles')).data
      } catch (e) {
        this.error(e)
      }
    },
    async loadAreas() {
      const id = this.selectedStore
      this.selectedArea = null
      this.areaChoices = []
      if (!id) return
      try {
        const { data } = await this.$api.get('/me/stores/' + id + '/areas')
        if (id !== this.selectedStore) return
        this.areaChoices = data
        if (data.length === 1) this.selectedArea = data[0].id
      } catch (e) {
        this.error(e)
      }
    },
    async refreshAdmission() {
      const storeId = this.selectedStore
      if (storeId) {
        const { data } = await this.$api.get(`/me/stores/${storeId}/areas`)
        if (storeId === this.selectedStore) this.areaChoices = data
      }
      await this.loadCurrent()
    },
    async resumeAccess() {
      try {
        await this.$api.post('/me/consumption/access/resume')
        await this.loadCurrent()
      } catch (e) {
        this.error(e)
      }
    },
    async showPassword() {
      try {
        const { data } = await this.$api.post('/me/consumption/password')
        await this.$alert(
          '密码：' +
            data.password +
            '；有效至 ' +
            new Date(Number(data.end_ms)).toLocaleString() +
            '。仅可使用一次。',
          '本次入场密码'
        )
      } catch (e) {
        if (e !== 'cancel' && e !== 'close') this.error(e)
      }
    },
    async loadCurrent() {
      this.current = (await this.$api.get('/me/consumption/current')).data
      if (
        this.current &&
        this.active === 'home' &&
        this.selectedStore !== this.current.store_id
      )
        this.selectedStore = this.current.store_id
      this.accessPending = (await this.$api.get('/me/consumption/access')).data
      if (this.current) await this.loadQuote()
    },
    async loadQuote() {
      this.quote = (await this.$api.post('/me/consumption/quote', {})).data
    },
    async submitSwitch(row, areaId, manager = false) {
      const lastSegment = row.segments && row.segments[row.segments.length - 1]
      const slot =
        'store_net_switch_' +
        row.id +
        '_' +
        (lastSegment ? lastSegment.started_at : row.started_at) +
        '_' +
        areaId
      let key = sessionStorage.getItem(slot)
      if (!key) {
        key = this.key()
        sessionStorage.setItem(slot, key)
      }
      const path = manager
        ? `/stores/${row.store_id}/consumptions/${row.id}/switch`
        : '/me/consumption/switch'
      const response = await this.$api.post(path, {
        area_id: areaId,
        idempotency_key: key,
      })
      if (
        response.status === 200 ||
        ['failed', 'cancelled'].includes(response.data.status)
      )
        sessionStorage.removeItem(slot)
      if (response.status === 202) this.$message.warning(response.data.message)
      else this.$message.success('已换区，费用继续累计，尚未结账')
    },
    async switchMine() {
      this.starting = true
      try {
        await this.submitSwitch(this.current, this.selectedArea)
        await this.loadCurrent()
        this.selectedArea = null
      } catch (e) {
        this.error(e)
      } finally {
        this.starting = false
      }
    },
    async managerSwitch(row) {
      try {
        const areas = (
          await this.$api.get(`/access/stores/${row.store_id}/areas`)
        ).data.filter((a) => a.enabled && a.id !== row.area_id)
        if (!areas.length) return this.$message.info('没有其他可用区域')
        const pick = await this.$prompt(
          '输入目标区域编号：' +
            areas.map((a) => a.id + ' ' + a.name).join('；'),
          '换区，不结账'
        )
        const areaId = Number(pick.value)
        if (!areas.some((a) => a.id === areaId))
          return this.$message.warning('请选择列表中的区域')
        await this.submitSwitch(row, areaId, true)
        await this.loadStoreTab()
      } catch (e) {
        if (e !== 'cancel' && e !== 'close') this.error(e)
      }
    },
    async startMine() {
      this.starting = true
      try {
        const slot =
          'store_net_start_' + this.selectedStore + '_' + this.selectedArea
        let key = sessionStorage.getItem(slot)
        if (!key) {
          key = this.key()
          sessionStorage.setItem(slot, key)
        }
        const response = await this.$api.post('/me/consumption/start', {
          store_id: this.selectedStore,
          area_id: this.selectedArea,
          idempotency_key: key,
        })
        if (
          response.status === 200 ||
          ['failed', 'cancelled'].includes(response.data.status)
        )
          sessionStorage.removeItem(slot)
        await this.loadCurrent()
        if (response.status === 202)
          this.$message.warning(
            response.data.message || '正在确认密码，尚未计费'
          )
        else this.$message.success('已开始计时')
      } catch (e) {
        this.error(e)
      } finally {
        this.starting = false
      }
    },
    async checkoutMine() {
      try {
        await this.$api.post('/me/consumption/checkout', {
          idempotency_key: this.key(),
          payment_method: 'auto',
        })
        await this.loadCurrent()
        this.$message.success('结账成功')
      } catch (e) {
        this.error(e)
      }
    },
    async saveProfile() {
      try {
        this.profile = (await this.$api.put('/users/me', this.profileForm)).data
        this.$message.success('已保存')
      } catch (e) {
        this.error(e)
      }
    },
    openStore(s) {
      this.selectedStore = s.id
      this.active = 'manage'
      this.selectStore()
    },
    selectStore() {
      this.selected = this.stores.find((x) => x.id === this.selectedStore) || {}
      this.loadStoreTab()
    },
    async loadStoreTab() {
      try {
        if (this.storeTab === 'report')
          this.report = (
            await this.$api.get(`/stores/${this.selectedStore}/reports`)
          ).data
        if (this.storeTab === 'members') {
          const [members, candidates] = await Promise.all([
            this.$api.get(`/stores/${this.selectedStore}/members`),
            this.$api.get(`/stores/${this.selectedStore}/member-candidates`),
          ])
          this.members = members.data
          this.users = candidates.data
        }
        if (this.storeTab === 'pricing') await this.loadPricing()
        if (this.storeTab === 'consumptions')
          this.consumptions = (
            await this.$api.get(`/stores/${this.selectedStore}/consumptions`)
          ).data
        if (this.storeTab === 'ledgers')
          this.ledgers = (
            await this.$api.get(`/stores/${this.selectedStore}/ledgers`)
          ).data
      } catch (e) {
        this.error(e)
      }
    },
    async createStore() {
      try {
        const name = await this.$prompt('门店名称', '新建门店', {
          inputValidator: (v) => !!v || '请输入名称',
        })
        const row = (
          await this.$api.post('/stores', { name: name.value, is_active: true })
        ).data
        this.stores.push(row)
        this.$message.success('门店已创建')
      } catch (e) {
        if (e !== 'cancel' && e !== 'close') this.error(e)
      }
    },
    async editStore() {
      try {
        const name = await this.$prompt('门店名称', '编辑门店', {
          inputValue: this.selected.name,
        })
        const address = await this.$prompt('门店地址', '编辑门店', {
          inputValue: this.selected.address || '',
        })
        const updated = (
          await this.$api.put(`/stores/${this.selectedStore}`, {
            name: name.value,
            address: address.value,
            remark: this.selected.remark,
            is_active: this.selected.is_active,
          })
        ).data
        this.selected = updated
        this.stores = this.stores.map((x) =>
          x.id === updated.id ? updated : x
        )
        this.$message.success('门店资料已保存')
      } catch (e) {
        if (e !== 'cancel' && e !== 'close') this.error(e)
      }
    },
    async addMember() {
      if (!this.newMember) return
      try {
        await this.$api.post(`/stores/${this.selectedStore}/members`, {
          user_id: this.newMember,
          store_role: 'member',
        })
        await this.loadStoreTab()
      } catch (e) {
        this.error(e)
      }
    },
    async adjust(row) {
      try {
        const value = await this.$prompt(
          '格式：本金,赠金,次卡，例如 100,20,1',
          '调整权益',
          {
            inputPattern: /^-?\d+(\.\d{1,2})?,-?\d+(\.\d{1,2})?,-?\d+$/,
            inputErrorMessage: '格式不正确',
          }
        )
        const x = value.value.split(',').map(Number)
        await this.$api.post(
          `/stores/${this.selectedStore}/benefits/${row.user_id}`,
          {
            paid_delta: x[0],
            bonus_delta: x[1],
            times_delta: x[2],
            remark: '后台调整',
          }
        )
        await this.loadStoreTab()
      } catch (e) {
        if (e !== 'cancel' && e !== 'close') this.error(e)
      }
    },
    async managerStart(row) {
      try {
        const areas = (
          await this.$api.get('/access/stores/' + this.selectedStore + '/areas')
        ).data.filter((a) => a.enabled)
        let areaId = areas.length === 1 ? areas[0].id : null
        if (!areaId) {
          const pick = await this.$prompt(
            '输入区域编号：' + areas.map((a) => a.id + ' ' + a.name).join('；'),
            '选择上机区域'
          )
          areaId = Number(pick.value)
        }
        const slot =
          'manager_start_' +
          this.selectedStore +
          '_' +
          areaId +
          '_' +
          row.user_id
        let key = sessionStorage.getItem(slot)
        if (!key) {
          key = this.key()
          sessionStorage.setItem(slot, key)
        }
        const result = await this.$api.post(
          '/stores/' + this.selectedStore + '/consumptions/start',
          {
            store_id: this.selectedStore,
            user_id: row.user_id,
            area_id: areaId,
            idempotency_key: key,
          }
        )
        if (
          result.status === 200 ||
          ['failed', 'cancelled'].includes(result.data.status)
        )
          sessionStorage.removeItem(slot)
        if (result.status === 202) {
          this.$message.warning(result.data.message || '正在确认密码，尚未计费')
          return
        }
        this.storeTab = 'consumptions'
        await this.loadStoreTab()
        this.$message.success('已开始计时')
      } catch (e) {
        this.error(e)
      }
    },
    async loadPricing() {
      const storeId = this.selectedStore
      this.pricingLoading = true
      this.pricingError = ''
      try {
        const { data } = await this.$api.get(`/stores/${storeId}/pricing`)
        if (storeId === this.selectedStore) this.pricing = data
      } catch (e) {
        if (storeId === this.selectedStore)
          this.pricingError =
            e.response?.data?.detail || '计费规则加载失败，请重新选择门店'
      } finally {
        if (storeId === this.selectedStore) this.pricingLoading = false
      }
    },
    async pricingUpdated() {
      await this.loadAreas()
      if (this.storeTab === 'pricing') await this.loadPricing()
    },
    async savePricing() {
      if (!this.$refs.storePricingEditor.validate()) return
      const storeId = this.selectedStore
      this.pricingSaving = true
      try {
        const { data } = await this.$api.put(
          `/stores/${storeId}/pricing`,
          this.pricing
        )
        if (storeId !== this.selectedStore) return
        this.pricing = data
        this.$message.success('定价已保存')
        await this.loadAreas()
        if (this.$refs.accessManagement)
          await this.$refs.accessManagement.load()
      } catch (e) {
        this.error(e)
      } finally {
        this.pricingSaving = false
      }
    },
    async managerCheckout(row) {
      try {
        const value = await this.$prompt(
          '输入结账方式：现金、余额、次卡',
          '店长结账',
          {
            inputValue: '现金',
            inputPattern: /^(现金|余额|次卡)$/,
            inputErrorMessage: '请输入支持的方式',
          }
        )
        await this.$api.post(
          `/stores/${this.selectedStore}/consumptions/${row.id}/checkout`,
          {
            payment_method: {
              现金: 'cash',
              余额: 'balance',
              次卡: 'times_card',
            }[value.value],
            idempotency_key: this.key(),
          }
        )
        await this.loadStoreTab()
        this.$message.success('结账成功')
      } catch (e) {
        if (e !== 'cancel' && e !== 'close') this.error(e)
      }
    },
    async createRole() {
      try {
        const name = await this.$prompt('角色名称', '新建角色')
        await this.$api.post('/admin/roles', {
          name: name.value,
          description: '',
          permissions: [],
        })
        this.roles = (await this.$api.get('/admin/roles')).data
      } catch (e) {
        if (e !== 'cancel' && e !== 'close') this.error(e)
      }
    },
    async editRole(row) {
      try {
        const value = await this.$prompt(
          '输入权限名称，用逗号分隔：用户管理、角色管理、门店管理、会员管理、定价管理、消费管理、查看流水、查看报表',
          '编辑角色权限',
          { inputValue: row.permissions.map(this.label).join(',') }
        )
        const permissions = value.value
          .split(/[,，]/)
          .map((x) => x.trim())
          .filter(Boolean)
          .map((x) => Object.keys(labels).find((k) => labels[k] === x) || x)
        await this.$api.put(`/admin/roles/${row.id}`, {
          name: row.name,
          description: row.description,
          permissions,
        })
        this.roles = (await this.$api.get('/admin/roles')).data
        this.$message.success('角色已保存')
      } catch (e) {
        if (e !== 'cancel' && e !== 'close') this.error(e)
      }
    },
    async editUser(row) {
      try {
        const role = await this.$prompt('输入角色编号', '修改用户', {
          inputValue: String(row.role_id),
          inputPattern: /^\d+$/,
        })
        const state = await this.$confirm(
          row.is_active ? '同时停用该账号吗？' : '同时启用该账号吗？',
          '账号状态',
          {
            confirmButtonText: row.is_active ? '停用' : '启用',
            cancelButtonText: '只修改角色',
            type: 'warning',
          }
        )
          .then(() => !row.is_active)
          .catch(() => row.is_active)
        const updated = (
          await this.$api.put(`/admin/users/${row.id}`, {
            role_id: Number(role.value),
            is_active: state,
          })
        ).data
        this.users = this.users.map((x) => (x.id === updated.id ? updated : x))
      } catch (e) {
        if (e !== 'cancel' && e !== 'close') this.error(e)
      }
    },
    logout() {
      localStorage.removeItem('store_net_token')
      this.$router.push('/login')
    },
  },
}
</script>
