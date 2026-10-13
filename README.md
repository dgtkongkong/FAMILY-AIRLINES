# FAMILY AIRLINES · 王牌机长

适用于希沃 XT01E 学习机、爸爸妈妈安卓手机的家庭成长应用。

## GitHub Pages

公开入口：https://dgtkongkong.github.io/FAMILY-AIRLINES/

`docs/` 包含入口与只读界面预览。预览每次从全新空白合成账本生成，不包含真实家庭记录，不保存提交、审批和兑换。正式多人同步、认证、Excel 导出与定时报表由 Python 后端执行，不能只靠 Pages 运行。

在 Settings → Pages 选择 Source: GitHub Actions，工作流 `.github/workflows/pages.yml` 会在 main 更新时构建、检查并发布。

本地构建：`python build_pages.py`，再运行 `python test_pages.py`。

## 本地和云端服务

运行 `python server.py --setup` 交互设置三个独立账号，再运行 `python server.py`。仅体验可运行 `Start-demo.cmd`；生产不要使用体验密码。

云端使用 `deploy/` 中的 systemd 与 Caddy 配置，HTTPS 下启用 `CAPTAIN_SECURE_COOKIE=1`。本应用只需 Python 标准库和 SQLite。请阅读[使用说明](使用说明.md)与[验证记录](验证记录.md)。

业务包括：子项独立计分、7 天补录、批量审批、权益兑换与里程预留、周目标随机奖励、21/30/60 天连续飞机、六档年度机队、现金与梦想基金账本、周月报和日期范围 XLSX。

## Android

`android/` 是客户端源码。支持 Android 6.0 及以上，正式版需有效 HTTPS 后端地址。源码不包含签名密钥或真实数据。已在原开发环境构建签名 1.1.0 APK，但尚未进行 XT01E 真机验收。

## 验证

`python -m unittest -v test_server`：39 项业务测试。Pages 独立检查：`python test_pages.py`。源码、公开静态页面和正式数据库分离；不要将 data、私钥、Token 或密码提交仓库。
