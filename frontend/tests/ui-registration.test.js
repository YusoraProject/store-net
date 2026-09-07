const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')

test('页面使用的 Element UI 组件全部按需注册，并带有对应样式', () => {
  const root = path.resolve(__dirname, '../src')
  const registrations = fs.readFileSync(path.join(root, 'ui/base.js'), 'utf8') +
    fs.readFileSync(path.join(root, 'ui/dashboard.js'), 'utf8')
  const walk = (directory) => fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const file = path.join(directory, entry.name)
    return entry.isDirectory() ? walk(file) : file.endsWith('.vue') ? [file] : []
  })
  const used = new Set(walk(root).flatMap((file) =>
    [...fs.readFileSync(file, 'utf8').matchAll(/<el-([a-z-]+)/g)].map((match) => match[1])))
  for (const name of used) {
    assert.ok(registrations.includes(`'element-ui/lib/${name}'`), `缺少组件：${name}`)
    assert.ok(registrations.includes(`'element-ui/lib/theme-chalk/${name}.css'`), `缺少样式：${name}`)
  }
  for (const service of ['$message', '$alert', '$confirm', '$prompt']) {
    assert.ok(registrations.includes(`Vue.prototype.${service} =`), `缺少消息服务：${service}`)
  }
  assert.ok(registrations.includes('Vue.use(Loading.directive)'))
})
