// 随仪表盘路由一起加载，保留原来的组件样式与消息弹窗调用方式。
import Vue from 'vue'
import './base'
import Avatar from 'element-ui/lib/avatar'
import Dialog from 'element-ui/lib/dialog'
import InputNumber from 'element-ui/lib/input-number'
import Menu from 'element-ui/lib/menu'
import MenuItem from 'element-ui/lib/menu-item'
import Submenu from 'element-ui/lib/submenu'
import Option from 'element-ui/lib/option'
import Pagination from 'element-ui/lib/pagination'
import Select from 'element-ui/lib/select'
import Switch from 'element-ui/lib/switch'
import TabPane from 'element-ui/lib/tab-pane'
import Table from 'element-ui/lib/table'
import TableColumn from 'element-ui/lib/table-column'
import Tabs from 'element-ui/lib/tabs'
import Loading from 'element-ui/lib/loading'
import Message from 'element-ui/lib/message'
import MessageBox from 'element-ui/lib/message-box'

import 'element-ui/lib/theme-chalk/avatar.css'
import 'element-ui/lib/theme-chalk/dialog.css'
import 'element-ui/lib/theme-chalk/input-number.css'
import 'element-ui/lib/theme-chalk/menu.css'
import 'element-ui/lib/theme-chalk/menu-item.css'
import 'element-ui/lib/theme-chalk/submenu.css'
import 'element-ui/lib/theme-chalk/option.css'
import 'element-ui/lib/theme-chalk/pagination.css'
import 'element-ui/lib/theme-chalk/select.css'
import 'element-ui/lib/theme-chalk/switch.css'
import 'element-ui/lib/theme-chalk/tab-pane.css'
import 'element-ui/lib/theme-chalk/table.css'
import 'element-ui/lib/theme-chalk/table-column.css'
import 'element-ui/lib/theme-chalk/tabs.css'
import 'element-ui/lib/theme-chalk/loading.css'
import 'element-ui/lib/theme-chalk/message.css'
import 'element-ui/lib/theme-chalk/message-box.css'

const components = [
  Avatar,
  Dialog,
  InputNumber,
  Menu,
  MenuItem,
  Submenu,
  Option,
  Pagination,
  Select,
  Switch,
  TabPane,
  Table,
  TableColumn,
  Tabs,
]
components.forEach((component) => Vue.use(component))
Vue.use(Loading.directive)
Vue.prototype.$loading = Loading.service
Vue.prototype.$message = Message
Vue.prototype.$msgbox = MessageBox
Vue.prototype.$alert = MessageBox.alert
Vue.prototype.$confirm = MessageBox.confirm
Vue.prototype.$prompt = MessageBox.prompt
