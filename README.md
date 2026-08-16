# HomeOS Deploy

面向 NAS / 服务器的 **SSH + Docker Compose** 一键部署向导（Windows 桌面端）。

通过图形界面完成：SSH 连接 → 登录 ghcr.io → `compose pull` / `up -d` → 查看状态与日志 / 重启 / 停止 / 下线。

仓库：[github.com/sfairy/HomeOS-Deploy](https://github.com/sfairy/HomeOS-Deploy)

## 功能

- **四步向导**：SSH → Registry → Deploy → Ops（左侧步进导航 + 深色科技风界面）
- **一键部署**：远程执行 `docker compose pull` + `up -d`，顶栏进度条 + 控制台拉取进度
- **部署前选项**：可先下线旧容器；删数据卷仅在该开关下生效（运维「下线」默认保留卷）
- **运维操作**：状态 / 日志 / 重启 / 停止 / 下线
- **CONSOLE**：过滤 Compose TUI 刷屏；相同行合并为 `（×N）`；启动失败只收集异常容器日志
- **状态短表**：服务 / 状态 / 对外端口（不含 COMMAND、完整镜像名）
- **配置管理**：本机 DPAPI 加密保存；支持 JSON 导入 / 导出
- **认证**：SSH 密码登录；远程命令经 `sudo`（密码与 SSH 相同）
- **安全细节**：首次运行表单为空；敏感字段可清除；导出可选是否含密码

## 环境要求

- Windows 10/11
- Python 3.10+（开发运行）
- 远端：可通过 SSH 登录，且具备 `sudo docker` / `docker compose` 权限  
  （使用 SSH 密码作为 sudo 密码）

工作目录须为远端**绝对路径**，例如 `/vol1/1000/docker/homeos`，且其中含 `compose.yaml` / `docker-compose.yml`。

## 快速开始

```powershell
# 克隆
git clone https://github.com/sfairy/HomeOS-Deploy.git
cd HomeOS-Deploy

# 虚拟环境与依赖
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 启动
python homeos_deploy\main.py
```

也可直接运行打包产物：`dist\HomeOS-Deploy.exe`。

## 打包 exe

```powershell
.\build.ps1
```

会从 `homeos_deploy/assets/app.png` 生成多尺寸 `app.ico`，写入 exe 与窗口图标。

产物：`dist\HomeOS-Deploy.exe`

若资源管理器仍显示旧图标，刷新或把 exe 拷到其他目录后再看（Windows 会缓存图标）。

## 使用流程

1. **SSH**：填写 Host / Port / User / Password / Workdir → 底栏「测试连接」
2. **Registry**：填写 ghcr 用户名与 Token → 「docker login」
3. **Deploy**：确认检查项后「开始部署」（会校验目录与编排文件）  
   可选「部署前先下线旧容器」；「删除数据卷」仅在该项开启时可用
4. **Ops**：刷新服务列表，查看状态 / 日志，或重启、停止、下线

进入 Deploy / Ops 前须已建立 SSH 连接（未连接时会自动尝试连接）。

本机配置路径：`%APPDATA%\HomeOSDeploy\config.json`  
（密码与 Token 使用 Windows DPAPI 加密存储）

部署失败时，控制台会追加「启动失败诊断」：容器状态 + **异常容器**最近日志（例如健康检查未通过、入口脚本缺失）。拉取成功但容器不健康，通常是远端镜像或编排问题，不是本工具的 SSH/Compose 命令写错。

## 项目结构

```
homeos_deploy/
  main.py             # 入口
  app_ui.py           # 兼容入口 → ui.app
  app_controller.py   # 业务编排 / 门禁 / 里程碑
  theme.py            # Aether Dock 深色科技主题
  ssh_session.py      # Paramiko SSH
  deploy_ops.py       # docker / compose 远程操作
  config_store.py     # 配置读写与导入导出
  progress.py         # 拉取 / 启动进度解析
  log_filter.py       # 控制台过滤与去重
  compose_view.py     # compose ps 短表
  paths.py            # 资源路径（源码 / 打包）
  defaults.py         # 应用常量
  assets/             # 应用图标（app.png / app.ico）
  ui/
    app.py            # 主窗口
    sidebar.py        # 左侧栏 + 纵向步进器
    action_bar.py     # 统一底栏 CTA
    console.py        # 终端风格 CONSOLE
    steps.py          # 四步表单
    components.py     # 共享控件
scripts/
  make_icon.py        # PNG → ICO
requirements.txt
build.ps1             # PyInstaller 一键打包
```

## 依赖

见 [requirements.txt](requirements.txt)：

- customtkinter
- paramiko
- pywin32
- Pillow

## 说明与限制

- SSH 仅支持密码登录；Registry 固定为 **ghcr.io**
- 运维「下线」执行 `compose down`，**不加** `-v`
- 控制台会隐藏 Compose 拉取 TUI、Waiting/Starting 等瞬时态；「查看日志」仍显示服务自身输出
- 当前面向 Windows；非 Windows 环境密钥保护会回退为简单编码，不推荐跨平台直接使用本机配置

## License

MIT
