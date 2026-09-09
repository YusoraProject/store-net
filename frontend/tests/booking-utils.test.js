const test = require('node:test')
const assert = require('node:assert/strict')
const { beijingInput, toUTC, displayTime, deposit } = require('../src/booking-utils')

test('包场时间固定北京时间，跨日和输入转换不依赖设备时区', () => {
  assert.equal(beijingInput('2026-09-08T18:30:00Z'), '2026-09-09T02:30')
  assert.equal(toUTC('2026-09-09T02:30'), '2026-09-08T18:30:00.000Z')
  assert.match(displayTime('2026-09-08T18:30:00'), /2026\/09\/09 02:30/)
  assert.equal(displayTime('2026-09-08T18:30:00'), displayTime('2026-09-08T18:30:00Z'))
})

test('订金按整数分向上取整，与后端金额一致', () => {
  assert.equal(deposit(100.01, 33), 33.01)
  assert.equal(deposit(0.01, 1), 0.01)
  assert.equal(deposit(199.99, 100), 199.99)
  assert.equal(deposit(0, 30), 0)
})
