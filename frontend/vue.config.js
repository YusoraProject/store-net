module.exports = {
  devServer: {
    port: 8081,
    proxy: { '/api': { target: 'http://127.0.0.1:8010', changeOrigin: true } },
  },
  productionSourceMap: false,
  chainWebpack(config) {
    // 在 Vue 编译后修正普通样式导入，不修改依赖源码，也不屏蔽构建警告。
    config.module
      .rule('vue')
      .use('store-style-imports')
      .loader(require.resolve('./build/vue2-style-imports'))
      .before('vue-loader')
    // 运行时单独缓存，页面变化时不连带更新入口中的运行时代码。
    config.optimization.runtimeChunk('single')
    // 公共依赖保持可缓存的小块，后台组件只在进入仪表盘时下载。
    config.optimization.splitChunks({
      chunks: 'all',
      maxSize: 200 * 1024,
    })
  },
}
