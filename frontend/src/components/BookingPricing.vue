<template>
  <section class="booking-pricing" :aria-busy="loading || busy">
    <div class="booking-pricing-heading">
      <div>
        <h3>包场时段与价格</h3>
        <p class="muted">设置会员可以预约的时段及包场总价。</p>
      </div>
      <el-button
        v-if="slots.length"
        size="small"
        icon="el-icon-plus"
        :disabled="loading || busy || !loaded"
        @click="add"
        >添加时段</el-button
      >
    </div>
    <p v-if="error" role="alert" class="booking-error">{{ error }}</p>
    <p v-if="loading" class="muted">正在加载包场时段…</p>
    <el-button v-else-if="!loaded" size="small" @click="load"
      >重新加载</el-button
    >
    <template v-else>
      <div v-if="!slots.length" class="booking-empty">
        <i class="el-icon-time" aria-hidden="true" /><strong
          >添加第一个包场时段</strong
        >
        <p>配置后，会员就能按日期预约包场。</p>
        <el-button plain icon="el-icon-plus" :disabled="busy" @click="add"
          >添加包场时段</el-button
        >
      </div>
      <section
        v-for="(slot, index) in slots"
        :key="slot.id"
        :ref="'slot-' + slot.id"
        class="booking-slot"
      >
        <button
          type="button"
          class="booking-slot-toggle"
          :aria-expanded="expanded === slot.id"
          @click="expanded = expanded === slot.id ? null : slot.id"
        >
          <span class="booking-slot-title"
            ><strong>{{ slot.name || '新包场时段' }}</strong
            ><small
              >{{ areaName(slot.area_id) }} · {{ slot.start }}—{{ slot.end
              }}{{
                slot.start === slot.end
                  ? '（全天）'
                  : slot.start > slot.end
                  ? '（次日结束）'
                  : ''
              }}</small
            ></span
          >
          <span class="booking-slot-meta"
            ><strong>¥{{ money(slot.price) }}</strong
            ><small>{{ slot.enabled ? '开放预约' : '已停用' }}</small></span
          >
          <i
            :class="
              expanded === slot.id ? 'el-icon-arrow-up' : 'el-icon-arrow-down'
            "
            aria-hidden="true"
          />
        </button>
        <div v-show="expanded === slot.id" class="booking-slot-body">
          <fieldset :disabled="busy" class="booking-slot-grid">
            <label class="slot-wide"
              >时段名称<el-input
                v-model="slot.name"
                maxlength="60"
                placeholder="例如：周末下午场"
                :disabled="busy"
                :aria-label="`包场时段${index + 1}名称`"
            /></label>
            <label class="slot-wide"
              >包场范围<el-select v-model="slot.area_id" :disabled="busy"
                ><el-option :value="0" label="整店" /><el-option
                  v-for="a in areas"
                  :key="a.id"
                  :value="a.id"
                  :label="a.name" /></el-select
            ></label>
            <label
              >开始时间<input
                type="time"
                v-model="slot.start"
                :aria-label="`包场时段${index + 1}开始时间`"
            /></label>
            <label
              >结束时间<input
                type="time"
                v-model="slot.end"
                :aria-label="`包场时段${index + 1}结束时间`"
            /></label>
            <label class="slot-wide"
              >包场总价 / 元<el-input-number
                v-model="slot.price"
                :min="0.01"
                :max="1000000"
                :precision="2"
                :disabled="busy"
                :aria-label="`包场时段${index + 1}总价`"
            /></label>
          </fieldset>
          <p v-if="slot.start >= slot.end" class="booking-hint">
            {{
              slot.start === slot.end
                ? '相同起止时间表示全天。'
                : '此时段跨午夜，结束时间为次日。'
            }}
          </p>
          <div class="booking-availability">
            <span
              ><strong>开放预约</strong
              ><small>关闭后，会员不能新预约此时段。</small></span
            ><el-switch
              v-model="slot.enabled"
              :disabled="busy"
              :aria-label="`包场时段${index + 1}开放预约`"
            />
          </div>
          <div class="booking-slot-actions">
            <el-button
              type="text"
              class="booking-remove"
              icon="el-icon-delete"
              :disabled="busy"
              @click="remove(slot, index)"
              >删除时段</el-button
            ><el-button size="small" @click="expanded = null">收起</el-button>
          </div>
        </div>
      </section>
      <div v-if="removed" class="booking-undo" role="status">
        已移除“{{ removed.slot.name || '新包场时段' }}”<el-button
          type="text"
          :disabled="busy"
          @click="undo"
          >撤销</el-button
        >
      </div>
      <div class="booking-save">
        <div>
          <strong>{{ dirty ? '有修改待保存' : '包场时段已同步' }}</strong>
          <p>只影响之后创建的包场。订金比例在「包场配置」中设置。</p>
        </div>
        <el-button
          type="primary"
          :loading="busy"
          :disabled="!dirty"
          @click="save"
          >保存包场时段</el-button
        >
      </div>
    </template>
  </section>
</template>
<script>
import { message, requestKey, money } from '../booking-utils'
export default {
  name: 'BookingPricing',
  props: { storeId: { type: Number, required: true } },
  data: () => ({
    slots: [],
    areas: [],
    loading: true,
    loaded: false,
    busy: false,
    error: '',
    expanded: null,
    removed: null,
    saved: '[]',
  }),
  computed: {
    dirty() {
      return JSON.stringify(this.slots) !== this.saved
    },
  },
  mounted() {
    this.load()
  },
  methods: {
    money,
    async load() {
      this.loading = true
      this.error = ''
      try {
        const { data } = await this.$api.get(
          `/stores/${this.storeId}/booking-slots`
        )
        this.slots = data.slots.map((s) => ({
          id: s.id,
          name: s.name,
          area_id: s.area_id || 0,
          start: s.start,
          end: s.end,
          price: s.price,
          enabled: s.enabled,
        }))
        this.areas = data.areas
        this.saved = JSON.stringify(this.slots)
        this.loaded = true
      } catch (e) {
        this.error = message(e)
      } finally {
        this.loading = false
      }
    },
    areaName(id) {
      return id
        ? this.areas.find((a) => a.id === id)?.name || '原计费区域'
        : '整店'
    },
    open(slot) {
      this.expanded = slot.id
      this.$nextTick(() => {
        const card = this.$refs['slot-' + slot.id]?.[0]
        card?.scrollIntoView({ block: 'nearest' })
        card?.querySelector('input')?.focus({ preventScroll: true })
      })
    },
    add() {
      if (this.busy || !this.loaded) return
      if (this.slots.length >= 48) {
        this.error = '最多配置48个包场时段'
        return
      }
      const slot = {
        id: requestKey(),
        name: `包场时段${this.slots.length + 1}`,
        area_id: this.areas.length === 1 ? this.areas[0].id : 0,
        start: '08:00',
        end: '18:00',
        price: 100,
        enabled: true,
      }
      this.slots.push(slot)
      this.error = ''
      this.open(slot)
    },
    remove(slot, index) {
      this.error = ''
      this.removed = { slot, index }
      this.slots.splice(index, 1)
    },
    undo() {
      if (this.slots.length >= 48) {
        this.error = '最多配置48个包场时段'
        return
      }
      this.slots.splice(this.removed.index, 0, this.removed.slot)
      this.error = ''
      this.open(this.removed.slot)
      this.removed = null
    },
    async save() {
      if (this.busy || !this.loaded || !this.dirty) return
      const invalid = this.slots.find(
        (s) =>
          !s.name.trim() ||
          !s.start ||
          !s.end ||
          !Number.isFinite(s.price) ||
          s.price <= 0
      )
      if (invalid) {
        this.error = '请完整填写时段名称、时间及大于0的总价'
        this.open(invalid)
        return
      }
      this.busy = true
      this.error = ''
      const saved = JSON.stringify(this.slots)
      try {
        await this.$api.put(`/stores/${this.storeId}/booking-slots`, {
          slots: JSON.parse(saved).map((s) => ({
            ...s,
            area_id: s.area_id || null,
          })),
        })
        this.saved = saved
        this.removed = null
        this.$message.success('包场时段已保存')
      } catch (e) {
        this.error = message(e)
      } finally {
        this.busy = false
      }
    },
  },
}
</script>
<style scoped>
.booking-pricing {
  margin-top: 28px;
  padding: 22px;
  border: 1px solid #dce9f5;
  border-radius: 20px;
  background: linear-gradient(
    140deg,
    rgba(238, 247, 255, 0.8),
    rgba(255, 255, 255, 0.65)
  );
}
.booking-pricing h3 {
  margin: 0;
  font-size: 17px;
}
.booking-pricing-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 18px;
}
.booking-pricing-heading > div {
  min-width: 0;
}
.booking-pricing-heading > .el-button {
  flex-shrink: 0;
}
.booking-pricing-heading p,
.booking-save p {
  font-size: 12px;
  margin: 7px 0 0;
  line-height: 1.7;
  color: #627991;
}
.booking-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 26px 16px;
  text-align: center;
  background: rgba(255, 255, 255, 0.6);
  border: 1px dashed #c9ddeb;
  border-radius: 16px;
  color: #45627d;
}
.booking-empty > i {
  font-size: 28px;
  color: #6294bc;
  margin-bottom: 12px;
}
.booking-empty p {
  font-size: 13px;
  margin: 8px 0 18px;
  color: #627991;
}
.booking-slot {
  overflow: hidden;
  border: 1px solid #dce5ef;
  background: rgba(255, 255, 255, 0.72);
  border-radius: 16px;
  margin: 12px 0;
  scroll-margin: 16px 0 120px;
}
.booking-slot-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 18px;
  border: 0;
  background: transparent;
  text-align: left;
  color: inherit;
  font: inherit;
  cursor: pointer;
}
.booking-slot-toggle:focus-visible {
  outline: 2px solid #409eff;
  outline-offset: -3px;
}
.booking-slot-title {
  flex: 1;
  min-width: 0;
}
.booking-slot-title strong {
  display: block;
  overflow-wrap: anywhere;
  font-size: 14px;
}
.booking-slot-toggle small {
  display: block;
  font-size: 12px;
  color: #627991;
  line-height: 1.7;
  margin-top: 5px;
}
.booking-slot-meta {
  text-align: right;
  flex-shrink: 0;
}
.booking-slot-meta strong {
  font-size: 15px;
  color: #316b99;
}
.booking-slot-body {
  padding: 0 18px 12px;
}
.booking-slot-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  padding: 18px 0 0;
  margin: 0;
  border: 0;
  border-top: 1px solid #e5edf5;
  min-width: 0;
}
.slot-wide {
  grid-column: 1 / -1;
}
.booking-slot-grid label {
  display: grid;
  gap: 8px;
  min-width: 0;
  color: #586d82;
  font-size: 13px;
}
.booking-slot-grid input[type='time'] {
  height: 44px;
  padding: 0 10px;
  min-width: 0;
  box-sizing: border-box;
  width: 100%;
  border: 1px solid #dcdfe6;
  border-radius: 10px;
  color: inherit;
  background: transparent;
  font: inherit;
}
.booking-slot-grid input:focus {
  outline: 2px solid #409eff;
  outline-offset: 1px;
}
.booking-slot-grid .el-input-number {
  width: 100%;
}
.booking-slot-grid ::v-deep .el-input__inner {
  height: 44px;
  line-height: 44px;
  border-radius: 10px;
}
.booking-slot-grid ::v-deep .el-input-number {
  line-height: 42px;
}
.booking-availability {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 0;
}
.booking-availability strong {
  font-size: 13px;
}
.booking-availability small {
  display: block;
  font-size: 12px;
  color: #627991;
  margin-top: 5px;
  line-height: 1.6;
}
.booking-slot-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-top: 1px solid #e5edf5;
  padding-top: 8px;
}
.booking-remove {
  color: #b94949;
}
.booking-hint {
  font-size: 12px;
  color: #627991;
}
.booking-error {
  color: #a65012;
  background: #fff4e7;
  padding: 12px;
  border-radius: 12px;
  font-size: 13px;
}
.booking-undo {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 13px;
  color: #627991;
}
.booking-save {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  margin-top: 20px;
  padding-top: 18px;
  border-top: 1px solid #dce5ef;
}
.booking-save strong {
  font-size: 13px;
  color: #45627d;
}
.booking-save > .el-button {
  flex-shrink: 0;
}
.dark-mode .booking-pricing {
  background: rgba(30, 50, 72, 0.65);
  border-color: #354d65;
}
.dark-mode .booking-slot,
.dark-mode .booking-empty {
  background: rgba(31, 49, 68, 0.6);
  border-color: #354d65;
}
.dark-mode .booking-slot-grid,
.dark-mode .booking-slot-actions,
.dark-mode .booking-save {
  border-color: #354d65;
}
.dark-mode .booking-pricing p,
.dark-mode .booking-pricing small,
.dark-mode .booking-slot-grid label,
.dark-mode .booking-save strong,
.dark-mode .booking-empty {
  color: #b5cce0;
}
.dark-mode .booking-slot-meta strong {
  color: #a5d4fb;
}
.dark-mode .booking-error {
  background: #423723;
  color: #f3cd94;
}
@media (max-width: 760px) {
  .booking-slot-grid input[type='time'],
  .booking-slot-grid ::v-deep .el-input__inner {
    font-size: 16px;
  }
  .booking-pricing {
    padding: 16px 12px;
    margin-top: 22px;
  }
  .booking-pricing-heading {
    align-items: flex-start;
    flex-wrap: wrap;
    gap: 12px;
  }
  .booking-slot-toggle {
    gap: 8px;
    padding: 14px 12px;
  }
  .booking-slot-body {
    padding: 0 12px 10px;
  }
  .booking-slot-grid {
    gap: 14px 10px;
  }
  .booking-save {
    align-items: stretch;
    flex-direction: column;
    gap: 14px;
  }
  .booking-save > .el-button {
    width: 100%;
    min-height: 44px;
    border-radius: 12px;
  }
}
</style>
