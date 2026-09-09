let sequence = 0
const id = () => `rule-${Date.now().toString(36)}-${sequence++}`
const clone = (value) => JSON.parse(JSON.stringify(value))
const kinds = ['workday', 'weekend', 'holiday']
const rate = () => ({ hourly: 8, cap: 40 })
const minutes = (value) => {
  if (!/^(?:[01][0-9]|2[0-3]):[0-5][0-9]$/.test(value || '')) return NaN
  const [h, m] = value.split(':').map(Number)
  return h * 60 + m
}
const timeText = (value) =>
  `${String(Math.floor((value % 1440) / 60)).padStart(2, '0')}:${String(
    value % 60
  ).padStart(2, '0')}`
const duration = (period) =>
  (minutes(period.end) - minutes(period.start) + 1440) % 1440 || 1440
const createPricing = () => ({
  version: 2,
  timezone_offset_minutes: 480,
  weekend_enabled: true,
  holiday_enabled: false,
  periods: [
    {
      id: 'day',
      name: '日间',
      start: '08:00',
      end: '18:00',
      rates: Object.fromEntries(kinds.map((k) => [k, rate()])),
    },
    {
      id: 'night',
      name: '夜间',
      start: '18:00',
      end: '08:00',
      rates: Object.fromEntries(kinds.map((k) => [k, rate()])),
    },
  ],
  date_rules: [],
})
const addPeriod = (rules) => {
  if (rules.periods.length >= 24) return '最多可设置24个时段'
  const candidates = rules.periods.filter(
    (p) =>
      Number.isFinite(minutes(p.start)) &&
      Number.isFinite(minutes(p.end)) &&
      duration(p) >= 2
  )
  const source = candidates.sort((a, b) => duration(b) - duration(a))[0]
  if (!source) return '请先填写有效的起止时间'
  const next = clone(source)
  next.id = id()
  let number = rules.periods.length + 1
  while (rules.periods.some((p) => p.name === `时段${number}`)) number++
  next.name = `时段${number}`
  next.start = timeText(
    minutes(source.start) + Math.floor(duration(source) / 2)
  )
  source.end = next.start
  rules.periods.splice(rules.periods.indexOf(source) + 1, 0, next)
  for (const rule of rules.date_rules) {
    if (rule.kind === 'special')
      rule.rates[next.id] = clone(rule.rates[source.id] || source.rates.holiday)
  }
  return ''
}
const removePeriod = (rules, pid) => {
  if (rules.periods.length <= 1) return '至少保留一个计费时段'
  const target = rules.periods.find((p) => p.id === pid)
  const previous = rules.periods.find(
    (p) => p.id !== pid && p.end === target.start
  )
  if (!previous) return '请先修正时段的空档或重叠，再删除时段'
  previous.end = target.end
  rules.periods.splice(rules.periods.indexOf(target), 1)
  for (const rule of rules.date_rules) if (rule.rates) delete rule.rates[pid]
  return ''
}
const validRate = (value) =>
  value &&
  ['hourly', 'cap'].every(
    (k) =>
      typeof value[k] === 'number' &&
      Number.isFinite(value[k]) &&
      value[k] >= 0 &&
      value[k] <= 100000 &&
      Math.abs(value[k] * 100 - Math.round(value[k] * 100)) < 0.000001
  )
const validatePricing = (rules) => {
  if (!rules?.periods?.length) return '至少配置一个时段'
  const occupied = new Set(),
    names = new Set()
  for (const period of rules.periods) {
    if (!period.name?.trim()) return '请填写每个时段的名称'
    if (names.has(period.name.trim())) return '时段名称不能重复'
    names.add(period.name.trim())
    if (
      !Number.isFinite(minutes(period.start)) ||
      !Number.isFinite(minutes(period.end))
    )
      return '请填写有效的时段起止时间'
    for (let i = 0; i < duration(period); i++) {
      const point = (minutes(period.start) + i) % 1440
      if (occupied.has(point)) return '时段有重叠，请调整起止时间'
      occupied.add(point)
    }
    if (!kinds.every((k) => validRate(period.rates[k])))
      return '请填写有效价格（0至100000元，最多两位小数）'
  }
  if (occupied.size !== 1440) return '时段必须覆盖24小时，不能留有空档'
  const ranges = []
  const validDate = (value) =>
    /^\d{4}-\d{2}-\d{2}$/.test(value || '') &&
    Number.isFinite(Date.parse(value)) &&
    new Date(value).toISOString().slice(0, 10) === value
  for (const rule of rules.date_rules) {
    if (!rule.name?.trim()) return '请填写特殊日期的名称'
    if (
      !validDate(rule.start_date) ||
      !validDate(rule.end_date) ||
      rule.start_date > rule.end_date
    )
      return '请填写正确的起止日期'
    if (
      ranges.some(
        ([start, end]) => rule.start_date <= end && rule.end_date >= start
      )
    )
      return '特殊日期范围不能重叠'
    ranges.push([rule.start_date, rule.end_date])
    if (
      rule.kind === 'special' &&
      !rules.periods.every((p) => validRate(rule.rates?.[p.id]))
    )
      return '请填写特殊节假日的全部时段价格'
  }
  return ''
}
module.exports = {
  createPricing,
  addPeriod,
  removePeriod,
  validatePricing,
  id,
  clone,
}
