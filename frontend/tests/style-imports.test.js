const assert = require('node:assert/strict')
const test = require('node:test')
const loader = require('../build/vue2-style-imports')

function transform(source, resourceQuery = '') {
  let result
  loader.call({ resourceQuery, callback(error, code) { assert.equal(error, null); result = code } }, source)
  return result
}

test('普通及 scoped 样式保留加载请求，不再读取不存在的默认导出', () => {
  const source = 'import style0 from "./Login.vue?vue&type=style&index=0&scoped=true&lang=css"\nexport default component'
  assert.equal(transform(source), 'import "./Login.vue?vue&type=style&index=0&scoped=true&lang=css"\nexport default component')
})
test('CSS Modules 仍保留默认导入和变量映射', () => {
  const source = 'import style0 from "./Page.vue?vue&type=style&index=0&module=true"'
  assert.equal(transform(source), source)
})
test('被使用的样式变量不被改写', () => {
  const source = 'import style0 from "./Page.vue?vue&type=style&index=0"\nconsume(style0)'
  assert.equal(transform(source), source)
})
test('脚本、样式子请求及服务端注入不处理', () => {
  const source = 'import style0 from "./Page.vue?vue&type=style&index=0"'
  assert.equal(transform(source, '?vue&type=script'), source)
  const script = 'import style0 from "./example.js"'
  assert.equal(transform(script), script)
  const server = 'var style0 = require("./Page.vue?vue&type=style")'
  assert.equal(transform(server), server)
})
