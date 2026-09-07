// 登录、注册与其他页面共用的基础组件，首屏不加载后台表格和弹窗。
import Vue from 'vue'
import Alert from 'element-ui/lib/alert'
import Button from 'element-ui/lib/button'
import Card from 'element-ui/lib/card'
import Form from 'element-ui/lib/form'
import FormItem from 'element-ui/lib/form-item'
import Input from 'element-ui/lib/input'
import Link from 'element-ui/lib/link'

import 'element-ui/lib/theme-chalk/base.css'
import 'element-ui/lib/theme-chalk/alert.css'
import 'element-ui/lib/theme-chalk/button.css'
import 'element-ui/lib/theme-chalk/card.css'
import 'element-ui/lib/theme-chalk/form.css'
import 'element-ui/lib/theme-chalk/form-item.css'
import 'element-ui/lib/theme-chalk/input.css'
import 'element-ui/lib/theme-chalk/link.css'
;[Alert, Button, Card, Form, FormItem, Input, Link].forEach((component) => {
  Vue.use(component)
})
