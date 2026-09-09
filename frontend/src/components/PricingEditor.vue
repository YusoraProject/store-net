<template>
  <div class="pricing-editor">
    <div class="pricing-options">
      <div class="pricing-option">
        <div>
          <strong>周末单独计价</strong>
          <p>关闭后，周六和周日使用基础价格。</p>
        </div>
        <el-switch v-model="draft.weekend_enabled" aria-label="周末单独计价" />
      </div>
      <div class="pricing-option">
        <div>
          <strong>节假日单独计价</strong>
          <p>关闭后，节假日及特殊节假日规则暂停生效，配置会保留。</p>
        </div>
        <el-switch
          v-model="draft.holiday_enabled"
          aria-label="节假日单独计价"
        />
      </div>
    </div>
    <div class="pricing-heading">
      <div>
        <h4>每日计费时段</h4>
        <p>
          覆盖完整24小时，不重叠、不留空。结束早于开始表示跨午夜，相同表示全天。
        </p>
      </div>
      <el-button size="small" @click="add">添加时段</el-button>
    </div>
    <section
      v-for="period in draft.periods"
      :key="period.id"
      class="pricing-period"
    >
      <div class="pricing-period-header">
        <label
          >时段名称<el-input
            v-model="period.name"
            maxlength="30"
            placeholder="例如：午间、晚间"
            :aria-label="period.name + '时段名称'"
        /></label>
        <label
          >开始时间<input
            v-model="period.start"
            type="time"
            required
            :aria-label="period.name + '开始时间'"
        /></label>
        <label
          >结束时间<input
            v-model="period.end"
            type="time"
            required
            :aria-label="period.name + '结束时间'"
        /></label>
        <el-button
          type="text"
          class="pricing-remove"
          :disabled="draft.periods.length === 1"
          @click="remove(period.id)"
          >删除时段</el-button
        >
      </div>
      <div class="pricing-rates">
        <div v-for="kind in enabledKinds" :key="kind.key" class="pricing-rate">
          <strong>{{ kind.label }}</strong>
          <label
            >每小时 / 元<el-input-number
              v-model="period.rates[kind.key].hourly"
              :min="0"
              :max="100000"
              :precision="2"
              :aria-label="period.name + kind.label + '每小时价格'"
          /></label>
          <label
            >每日该时段封顶 / 元<el-input-number
              v-model="period.rates[kind.key].cap"
              :min="0"
              :max="100000"
              :precision="2"
              :aria-label="period.name + kind.label + '封顶价格'"
          /></label>
        </div>
      </div>
    </section>
    <p class="pricing-note">
      封顶填0表示不限额。跨午夜时段按自然日分别封顶；重返同一区域且规则未变时，共享当天该时段的封顶。添加时段会平分最长时段，删除会将时间合并到前一相邻时段。
    </p>
    <div class="pricing-calendar">
      <div class="pricing-heading">
        <div>
          <h4>节假日与特殊日期</h4>
          <p>按日期设置节假日、调休或专属价格，日期范围包含首尾两天。</p>
        </div>
        <el-button
          v-if="draft.date_rules.length"
          size="small"
          icon="el-icon-plus"
          @click="addDate"
          >添加规则</el-button
        >
      </div>
      <div v-if="!draft.date_rules.length" class="pricing-empty">
        <i class="el-icon-date" aria-hidden="true" />
        <strong>还没有特殊日期</strong>
        <p>目前按基础及周末价格计费。</p>
        <el-button plain icon="el-icon-plus" @click="addDate"
          >添加日期规则</el-button
        >
      </div>
      <section
        v-for="rule in draft.date_rules"
        :key="rule.id"
        :ref="'date-' + rule.id"
        class="pricing-date-rule"
      >
        <button
          type="button"
          class="pricing-rule-toggle"
          :aria-expanded="expandedDate === rule.id"
          @click="expandedDate = expandedDate === rule.id ? null : rule.id"
        >
          <span
            ><strong>{{ rule.name || '新日期规则' }}</strong
            ><small>{{ dateSummary(rule) }}</small></span
          >
          <i
            :class="
              expandedDate === rule.id
                ? 'el-icon-arrow-up'
                : 'el-icon-arrow-down'
            "
            aria-hidden="true"
          />
        </button>
        <div v-show="expandedDate === rule.id" class="pricing-date-body">
          <div class="pricing-date-fields">
            <label
              >规则名称<el-input
                v-model="rule.name"
                placeholder="例如：国庆、春节、调休"
                maxlength="60"
            /></label>
            <label
              >开始日期<input
                v-model="rule.start_date"
                type="date"
                required
                aria-label="规则开始日期"
            /></label>
            <label
              >结束日期<input
                v-model="rule.end_date"
                type="date"
                required
                aria-label="规则结束日期"
            /></label>
            <label
              >计价方式<el-select
                v-model="rule.kind"
                @change="prepareSpecial(rule)"
                ><el-option label="节假日价格" value="holiday" /><el-option
                  label="特殊节假日单独定价"
                  value="special" /><el-option
                  label="基础价格（调休工作日）"
                  value="workday" /><el-option
                  label="周末价格"
                  value="weekend" /></el-select
            ></label>
          </div>
          <p
            v-if="
              !draft.holiday_enabled &&
              ['holiday', 'special'].includes(rule.kind)
            "
            class="pricing-note"
          >
            节假日计价已关闭，此规则暂不生效。
          </p>
          <div v-if="rule.kind === 'special'" class="pricing-rates">
            <div
              v-for="period in draft.periods"
              :key="period.id"
              class="pricing-rate"
            >
              <strong>{{ period.name || '未命名时段' }}</strong>
              <label
                >每小时 / 元<el-input-number
                  v-model="rule.rates[period.id].hourly"
                  :min="0"
                  :max="100000"
                  :precision="2"
              /></label>
              <label
                >每日该时段封顶 / 元<el-input-number
                  v-model="rule.rates[period.id].cap"
                  :min="0"
                  :max="100000"
                  :precision="2"
              /></label>
            </div>
          </div>
          <div class="pricing-rule-actions">
            <el-button
              type="text"
              class="pricing-remove"
              icon="el-icon-delete"
              @click="removeDate(rule)"
              >删除规则</el-button
            >
            <el-button size="small" @click="expandedDate = null"
              >收起</el-button
            >
          </div>
        </div>
      </section>
      <div v-if="removedDate" class="pricing-undo" role="status">
        已移除“{{ removedDate.rule.name || '新日期规则' }}”<el-button
          type="text"
          @click="undoDate"
          >撤销</el-button
        >
      </div>
      <p class="pricing-note">
        日期需手动维护，不自动同步法定节假日。添加或修改后，请保存下方计费规则。
      </p>
    </div>
    <p v-if="validationMessage" class="pricing-validation" role="status">
      {{ validationMessage }}
    </p>
  </div>
</template>
<script>
import {
  createPricing,
  addPeriod,
  removePeriod,
  validatePricing,
  id,
  clone,
} from '../pricing-rules'
export default {
  name: 'PricingEditor',
  props: { value: { type: Object, required: true } },
  data() {
    return {
      expandedDate: null,
      removedDate: null,
      draft: {
        ...clone(this.value?.version === 2 ? this.value : createPricing()),
        timezone_offset_minutes: 480,
      },
    }
  },
  computed: {
    enabledKinds() {
      return [
        { key: 'workday', label: '基础价格' },
        ...(this.draft.weekend_enabled
          ? [{ key: 'weekend', label: '周末价格' }]
          : []),
        ...(this.draft.holiday_enabled
          ? [{ key: 'holiday', label: '节假日价格' }]
          : []),
      ]
    },
    validationMessage() {
      return validatePricing(this.draft)
    },
  },
  watch: {
    value(value) {
      if (value !== this.draft)
        this.draft = {
          ...clone(value?.version === 2 ? value : createPricing()),
          timezone_offset_minutes: 480,
        }
    },
    draft: {
      deep: true,
      handler(value) {
        this.$emit('input', value)
      },
    },
  },
  methods: {
    validate() {
      if (this.validationMessage) {
        this.$message.warning(this.validationMessage)
        return false
      }
      return true
    },
    add() {
      const message = addPeriod(this.draft)
      this.draft = clone(this.draft)
      if (message) this.$message.warning(message)
    },
    remove(pid) {
      const message = removePeriod(this.draft, pid)
      if (message) this.$message.warning(message)
    },
    addDate() {
      if (this.draft.date_rules.length >= 366)
        return this.$message.warning('最多可设置366条日期规则')
      const rule = {
        id: id(),
        name: '',
        start_date: '',
        end_date: '',
        kind: 'holiday',
      }
      this.draft.date_rules.push(rule)
      this.expandedDate = rule.id
      this.$nextTick(() => {
        const card = this.$refs['date-' + rule.id]?.[0]
        card?.scrollIntoView({ block: 'nearest' })
        card?.querySelector('input')?.focus({ preventScroll: true })
      })
    },
    dateSummary(rule) {
      const kind = {
        holiday: '节假日价格',
        special: '单独定价',
        workday: '基础价格',
        weekend: '周末价格',
      }[rule.kind]
      return `${
        rule.start_date && rule.end_date
          ? rule.start_date + ' 至 ' + rule.end_date
          : '待填写日期'
      } · ${kind}`
    },
    removeDate(rule) {
      const index = this.draft.date_rules.indexOf(rule)
      this.removedDate = { rule, index }
      this.draft.date_rules.splice(index, 1)
    },
    undoDate() {
      if (this.draft.date_rules.length >= 366)
        return this.$message.warning('最多可设置366条日期规则')
      const { rule, index } = this.removedDate
      this.draft.date_rules.splice(index, 0, rule)
      this.expandedDate = rule.id
      this.removedDate = null
    },
    prepareSpecial(rule) {
      if (rule.kind === 'special')
        this.$set(
          rule,
          'rates',
          Object.fromEntries(
            this.draft.periods.map((p) => [
              p.id,
              clone(rule.rates?.[p.id] || p.rates.holiday),
            ])
          )
        )
    },
  },
}
</script>
<style scoped>
.pricing-editor {
  --pricing-border: #e3e9f1;
  --pricing-muted: #69788d;
  --pricing-surface: #f7f9fc;
  color: inherit;
}
.pricing-options {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr));
  gap: 14px;
}
.pricing-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px;
  background: var(--pricing-surface);
  border-radius: 10px;
}
.pricing-option strong,
.pricing-rate strong {
  font-size: 14px;
}
.pricing-option p,
.pricing-heading p,
.pricing-note {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--pricing-muted);
  line-height: 1.8;
}
.pricing-timezone {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 18px 0 8px;
  font-size: 13px;
}
.pricing-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin: 26px 0 14px;
}
.pricing-heading h4 {
  margin: 0;
  font-size: 16px;
}
.pricing-heading .el-button {
  flex-shrink: 0;
}
.pricing-period,
.pricing-date-rule {
  padding: 18px;
  border: 1px solid var(--pricing-border);
  border-radius: 12px;
  margin-bottom: 14px;
}
.pricing-calendar {
  margin-top: 24px;
  padding: 20px;
  border: 1px solid var(--pricing-border);
  border-radius: 20px;
  background: linear-gradient(
    140deg,
    rgba(238, 247, 255, 0.8),
    rgba(255, 255, 255, 0.65)
  );
}
.pricing-calendar .pricing-heading {
  margin: 0 0 18px;
}
.pricing-calendar .pricing-date-rule {
  padding: 0;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.7);
  scroll-margin: 16px 0 120px;
}
.pricing-rule-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  padding: 16px;
  border: 0;
  background: transparent;
  color: inherit;
  text-align: left;
  font: inherit;
  cursor: pointer;
}
.pricing-rule-toggle span {
  min-width: 0;
}
.pricing-rule-toggle strong {
  display: block;
  overflow-wrap: anywhere;
  font-size: 14px;
}
.pricing-rule-toggle small {
  display: block;
  margin-top: 6px;
  color: var(--pricing-muted);
  line-height: 1.7;
  font-size: 12px;
}
.pricing-rule-toggle:focus-visible {
  outline: 2px solid #409eff;
  outline-offset: -3px;
}
.pricing-date-body {
  padding: 0 16px 12px;
}
.pricing-date-fields {
  border-top: 1px solid var(--pricing-border);
  padding-top: 16px;
}
.pricing-rule-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 16px;
  border-top: 1px solid var(--pricing-border);
  padding-top: 8px;
}
.pricing-undo {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 13px;
  color: var(--pricing-muted);
}
.pricing-period-header,
.pricing-date-fields {
  display: grid;
  grid-template-columns: minmax(120px, 1.4fr) repeat(2, minmax(110px, 1fr)) auto;
  align-items: end;
  gap: 12px;
}
.pricing-date-fields {
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 160px), 1fr));
}
.pricing-editor label {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: 8px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--pricing-muted);
}
.pricing-editor input[type='time'],
.pricing-editor input[type='date'] {
  appearance: none;
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  height: 40px;
  padding: 0 10px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  background: transparent;
  color: inherit;
  font: inherit;
}
.pricing-editor input:focus {
  outline: 2px solid #409eff;
  outline-offset: 1px;
}
.pricing-rates {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 170px), 1fr));
  gap: 16px;
  margin-top: 18px;
}
.pricing-rate {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px;
  background: var(--pricing-surface);
  border-radius: 8px;
  min-width: 0;
}
.pricing-rate .el-input-number {
  width: 100%;
}
.pricing-remove {
  color: #be4141;
}
.pricing-validation {
  color: #b45309;
  background: #fff7ed;
  padding: 12px;
  border-radius: 8px;
  font-size: 13px;
}
.pricing-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 26px 16px;
  text-align: center;
  color: var(--pricing-muted);
  background: rgba(255, 255, 255, 0.6);
  border: 1px dashed var(--pricing-border);
  border-radius: 16px;
  font-size: 13px;
}
.pricing-empty > i {
  font-size: 28px;
  margin-bottom: 12px;
  color: #6294bc;
}
.pricing-empty strong {
  color: #45627d;
  font-size: 14px;
}
.pricing-empty p {
  margin: 8px 0 18px;
}
.dark-mode .pricing-calendar {
  background: rgba(30, 50, 72, 0.65);
}
.dark-mode .pricing-calendar .pricing-date-rule,
.dark-mode .pricing-empty {
  background: rgba(31, 49, 68, 0.6);
}
.dark-mode .pricing-empty strong {
  color: #b5cce0;
}
.dark-mode .pricing-editor {
  --pricing-border: #334155;
  --pricing-muted: #b5c1d2;
  --pricing-surface: #202d40;
}
@media (max-width: 760px) {
  .pricing-calendar {
    padding: 16px 12px;
  }
  .pricing-date-body {
    padding: 0 12px 10px;
  }
  .pricing-rule-toggle {
    padding: 14px 12px;
  }
  .pricing-date-fields {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 14px 10px;
  }
  .pricing-date-fields > label:first-child,
  .pricing-date-fields > label:last-child {
    grid-column: 1 / -1;
  }
  .pricing-date-fields input[type='date'] {
    height: 44px;
    padding: 0 6px;
    border-radius: 10px;
    font-size: 16px;
  }
  .pricing-date-fields ::v-deep .el-input__inner {
    height: 44px;
    line-height: 44px;
    border-radius: 10px;
    font-size: 16px;
  }
  .pricing-period-header {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .pricing-period-header > label:first-child {
    grid-column: 1 / -1;
  }
  .pricing-period,
  .pricing-date-rule {
    padding: 14px;
  }
  .pricing-heading {
    align-items: flex-start;
    flex-wrap: wrap;
  }
  .pricing-rates {
    grid-template-columns: 1fr;
  }
  .pricing-timezone {
    align-items: flex-start;
    flex-direction: column;
  }
}
@media (max-width: 360px) {
  .pricing-date-fields {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
