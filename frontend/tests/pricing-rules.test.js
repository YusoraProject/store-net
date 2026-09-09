const test = require('node:test')
const assert = require('node:assert/strict')
const {createPricing, addPeriod, removePeriod, validatePricing} = require('../src/pricing-rules')

test('添加和删除跨午夜时段仍完整覆盖24小时，特殊价格同步', () => {
  const rules = createPricing()
  rules.date_rules.push({id:'holiday',name:'国庆',start_date:'2026-10-01',end_date:'2026-10-07',kind:'special',rates:{day:{hourly:20,cap:80},night:{hourly:30,cap:90}}})
  assert.equal(addPeriod(rules), '')
  assert.equal(rules.periods.length,3)
  assert.equal(validatePricing(rules),'')
  const added = rules.periods.find(p => !['day','night'].includes(p.id))
  assert.deepEqual(rules.date_rules[0].rates[added.id], {hourly:30,cap:90})
  assert.equal(removePeriod(rules,added.id),'')
  assert.equal(validatePricing(rules),'')
  assert.equal(rules.date_rules[0].rates[added.id],undefined)
})
test('可合并为全天，且不能删除最后一个时段', () => {
  const rules = createPricing()
  assert.equal(removePeriod(rules,'night'),'')
  assert.equal(rules.periods[0].start,rules.periods[0].end)
  assert.equal(validatePricing(rules),'')
  assert.match(removePeriod(rules,'day'),/至少/)
})
test('时段重叠和空档、无效日期和特殊价格不能保存', () => {
  const rules = createPricing()
  rules.periods[0].end = '19:00'
  assert.match(validatePricing(rules),/重叠/)
  rules.periods[0].end = '17:00'
  assert.match(validatePricing(rules),/空档/)
  rules.periods[0].end = '18:00'
  rules.date_rules.push({id:'bad',name:'无效日期',start_date:'2026-02-30',end_date:'2026-03-01',kind:'holiday'})
  assert.match(validatePricing(rules),/日期/)
  rules.date_rules[0] = {id:'a',name:'春节',start_date:'2026-02-16',end_date:'2026-02-20',kind:'special',rates:{}}
  assert.match(validatePricing(rules),/全部时段/)
})
