# AstrBot Steam价格查询插件

## 访问统计
![访问统计](https://count.getloli.com/get/@astrbot_stprice?theme=rule34)

## 简介
本插件用于查询Steam游戏的国区价格、史低信息，并支持与其他区服价格对比。支持自动识别游戏名或Steam商店链接。

## 主要功能
- 查询Steam游戏国区价格、史低价、当前折扣
- 支持后台自定义选择对比区（如UA、US、JP等）
- 自动翻译中文游戏名为Steam官方英文名
- 支持自定义维护货币汇率，自动转换为人民币

## 快速上手
1. 将插件目录放入 `AstrBot/data/plugins/`
2. 在后台管理界面填写 ITAD_API_KEY 和 STEAMWEBAPI_KEY
3. 使用指令：
- `/史低 游戏名或Steam商店链接` 查询史低信息
- `/查找游戏 游戏名` 搜索Steam游戏

## 注意事项
- 出现“游戏名翻译失败”时，请检查astrbot设置项，是否没有设置默认大模型
- 如果开启了区域对比价格功能，汇率的计算取决于本地定义，若需要更新，请编辑插件目录下的 `price_convert.py` 文件

## 价格区与汇率说明
- 对比区可在后台下拉选择，自动查询对应区服价格
- 汇率转换由 `price_convert.py` 实现，支持自定义维护

## 演示截图
![查询示例](https://raw.githubusercontent.com/Maoer233/astrbot_plugin_steam_status_monitor/main/price.jpg)

欢迎加咱QQ 1912584909 来闲聊喵