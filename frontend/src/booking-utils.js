const money = (value) => Number(value || 0).toFixed(2)
const beijingInput = (value = new Date()) =>
  new Date(new Date(value).getTime() + 8 * 3600000).toISOString().slice(0, 16)
const beijingDate = () => beijingInput().slice(0, 10)
const toUTC = (value) => new Date(value + '+08:00').toISOString()
const displayTime = (value) =>
  value
    ? new Date(
        /(?:Z|[+-]\d\d:\d\d)$/.test(value) ? value : value + 'Z'
      ).toLocaleString('zh-CN', {
        timeZone: 'Asia/Shanghai',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      })
    : '-'
const deposit = (price, percent) =>
  Math.ceil((Math.round(Number(price) * 100) * Number(percent)) / 100) / 100
const phase = (value) =>
  ({
    awaiting_deposit: '待付订金',
    expired: '支付超时',
    scheduled: '待开始',
    in_progress: '包场中',
    ended: '已结束',
    cancelled: '已取消',
  }[value] || value)
const invitation = (value) =>
  ({ pending: '待同意', accepted: '已同意', declined: '已拒绝' }[value] ||
  value)
const message = (error) => {
  const detail = error.response && error.response.data.detail
  return typeof detail === 'string' ? detail : '操作失败，请检查输入后重试'
}
const requestKey = () =>
  `booking-${Date.now()}-${Math.random().toString(36).slice(2)}`
module.exports = {
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
}
