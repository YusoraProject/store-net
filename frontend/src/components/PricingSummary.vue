<template>
  <div v-if="pricing && pricing.periods" class="pricing-summary">
    <div
      v-for="period in pricing.periods"
      :key="period.id"
      class="pricing-summary-period"
    >
      <strong
        >{{ period.name }} · {{ period.start }}—{{ period.end
        }}{{
          period.start === period.end
            ? '（全天）'
            : period.start > period.end
            ? '（跨午夜）'
            : ''
        }}</strong
      >
      <span v-for="kind in kinds" :key="kind.key"
        >{{ kind.label }}：¥{{ period.rates[kind.key].hourly }}/小时，{{
          cap(period.rates[kind.key].cap)
        }}</span
      >
    </div>
    <details v-if="activeRules.length">
      <summary>查看特殊日期价格（{{ activeRules.length }}条）</summary>
      <div
        v-for="rule in activeRules"
        :key="rule.id"
        class="pricing-summary-rule"
      >
        <strong
          >{{ rule.name }} · {{ rule.start_date }}—{{ rule.end_date }}</strong
        >
        <template v-if="rule.kind === 'special'"
          ><span v-for="period in pricing.periods" :key="period.id"
            >{{ period.name }}：¥{{ rule.rates[period.id].hourly }}/小时，{{
              cap(rule.rates[period.id].cap)
            }}</span
          ></template
        >
        <span v-else
          >{{ labels[rule.kind]
          }}{{
            rule.kind === 'weekend' && !pricing.weekend_enabled
              ? '（周末计价关闭，使用基础价格）'
              : ''
          }}</span
        >
      </div>
    </details>
    <p class="pricing-summary-clock">
      按分钟向上取整，封顶按自然日内各时段分别计算。
    </p>
  </div>
</template>
<script>
export default {
  name: 'PricingSummary',
  props: { pricing: Object },
  data: () => ({
    labels: { workday: '基础价格', weekend: '周末价格', holiday: '节假日价格' },
  }),
  computed: {
    kinds() {
      return [
        { key: 'workday', label: '基础' },
        ...(this.pricing.weekend_enabled
          ? [{ key: 'weekend', label: '周末' }]
          : []),
        ...(this.pricing.holiday_enabled
          ? [{ key: 'holiday', label: '节假日' }]
          : []),
      ]
    },
    activeRules() {
      return this.pricing.date_rules.filter(
        (rule) =>
          this.pricing.holiday_enabled ||
          !['holiday', 'special'].includes(rule.kind)
      )
    },
  },
  methods: {
    cap(value) {
      return value > 0 ? `每日该时段封顶¥${value}` : '不封顶'
    },
  },
}
</script>
<style scoped>
.pricing-summary {
  margin-top: 14px;
  padding: 14px;
  background: #f5f8fc;
  border-radius: 10px;
  font-size: 13px;
  line-height: 1.8;
  overflow-wrap: anywhere;
}
.pricing-summary-period,
.pricing-summary-rule {
  display: flex;
  flex-direction: column;
  margin-bottom: 12px;
}
.pricing-summary-clock {
  color: #66758a;
  font-size: 12px;
  margin: 0 0 8px;
}
.pricing-summary summary {
  cursor: pointer;
  color: #2563eb;
  padding: 8px 0;
}
.dark-mode .pricing-summary {
  background: #202d40;
}
.dark-mode .pricing-summary-clock {
  color: #b5c1d2;
}
</style>
