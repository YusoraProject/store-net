// Vue Loader 15 为普通样式生成默认导入，但样式转发模块只有副作用，没有默认导出。
// 只去掉未使用的变量绑定，保留样式请求；CSS Modules、服务端注入和样式内容都不改。
module.exports = function fixStyleImports(source, map) {
  if (this.resourceQuery) return this.callback(null, source, map)
  const result = source.replace(
    /^import (style\d+) from ("(?:[^"\\]|\\.)*")[;\t ]*$/gm,
    (statement, binding, quotedRequest) => {
      const request = JSON.parse(quotedRequest)
      const query = new URLSearchParams(request.slice(request.lastIndexOf('?') + 1))
      if (query.get('type') !== 'style' || query.has('module')) return statement
      const occurrences = source.match(new RegExp(`\\b${binding}\\b`, 'g')) || []
      return occurrences.length === 1 ? `import ${quotedRequest}` : statement
    }
  )
  this.callback(null, result, map)
}
