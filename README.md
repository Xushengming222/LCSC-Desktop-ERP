# LCSC Desktop ERP

立创商城物料管理的非官方 Windows 桌面移植版，基于 [BrokenClient/LCSC_android_erp](https://github.com/BrokenClient/LCSC_android_erp) 改写。上游 Android 项目采用 GPL-3.0；本移植版也按 GPL-3.0-only 发布，并保留上游来源说明。它与立创商城没有官方关联。

## 功能

- 物料搜索、入库和库存管理
- 库位管理、BOM 导入和库存备份
- GitHub/Gitee 远程备份：多仓库账号、手动上传与拉取、变更触发和按天补传、自动保留最新 5 份或手动多选删除
- 物料二维码与标签导出、打印
- 中文和英文界面
- 库存、偏好设置和图片缓存保存在本机

联网功能会向立创商城查询物料信息并下载图片。应用默认把本地数据放在 `%APPDATA%\LCSC_ERP`；可用 `LCSC_ERP_DATA_DIR` 环境变量指定其他目录。

## 远程备份

在「设置 → 远程备份」添加 GitHub 或 Gitee 仓库账号。填写仓库所有者、仓库名称、备份目录（默认 `backups`）和有该仓库读写权限的访问令牌；分支留空时使用仓库默认分支。GitHub 精细令牌需要所选仓库的 Contents 读写权限。建议使用**私有仓库**，因为库存备份可能包含物料信息、图片和业务数据。令牌由 Windows 当前用户的 DPAPI 加密保存在本机数据目录 `remote_backup.json`，不会进入发行包或源码仓库。

「立即备份」上传与手机端兼容的 `lcsc_inventory_backup_YYYYMMDD_HHMM.xlsx`；「拉取备份列表」列出当前账号目录中的备份，可选中一份恢复。恢复会替换当前桌面库存，执行前在本地数据目录的 `before-remote-restore` 下保存一份保护备份。启用自动备份后，程序运行期间检测库存变化并在短暂间隔后上传，同时每天至少补传一次。启用多账号时上传到所有账号；拉取和恢复始终使用当前选中的账号。程序关闭时不会运行自动备份。

「自动保留最新 5 份备份」默认关闭。开启时需确认，程序立即清理当前账号目录中更旧的备份；之后每次成功上传，会在相应账号目录中只保留最新 5 份。也可以在备份列表中用 Ctrl/Shift 多选，再点击「删除选中备份」手动管理。删除是远程仓库文件删除，会产生提交，不能在应用中撤销；其他文件不会被清理。

如果本机代理在建立 TLS 连接时意外断开，远程备份的读取请求会尝试绕过本机代理直连。只读请求遇到 TLS EOF、读取超时或传输中断时最多尝试 3 次。GitHub 恢复直接读取原始 Excel，减少大文件所需的请求次数。上传和删除不会在结果不明时自动重发。

桌面版可读取手机新版 schema 2 工作簿的库位、物料和库存字段。手机端新增的流水、物理容器和部分设置目前不属于桌面数据模型，因此不会写入桌面数据库；桌面上传仍采用手机兼容的 schema 1 格式。跨端使用时请保留原始手机备份。

## 下载使用

前往 [Releases](https://github.com/Xushengming222/LCSC-Desktop-ERP/releases)，下载并完整解压 `LCSC-Desktop-ERP-windows-x64.zip`，然后双击 `LCSC-Desktop-ERP` 文件夹中的 `LCSC-Desktop-ERP.exe`。请保留同目录的 `_internal` 文件夹。无需另行安装 Python。`SHA256SUMS.txt` 提供下载文件校验值。

## 从源码运行

需要 Windows 10/11 x64、Python 3.10 或更高版本，以及可用的网络连接来安装 Python 依赖。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
python main.py
```

安装后也可以用 `lcsc-erp` 命令启动图形界面。

也可以不安装成可编辑包，直接执行 `python main.py`；依赖仍需先安装：

```powershell
python -m pip install -r requirements.txt
```

## 构建 Windows 发行包

```powershell
python -m pip install -r requirements-build.txt
python -m pip install --no-deps .
python scripts/build_release.py
```

构建使用 Python 3.12 和固定版本的依赖。可执行文件目录会生成在 `dist/`，完整发行压缩包和校验文件会生成在 `release/`。构建脚本还会检查打包程序能否初始化 SSL。创建形如 `v1.2.3` 的 GitHub Release 后，GitHub Actions 会构建 Windows x64 发行包并附加到该 Release；GitHub 同时提供该标签对应的源码压缩包。

可运行 `python scripts/smoke_check.py` 检查程序启动、五个页面、中英文资源和打包程序的配置路径；`python -m unittest discover -s tests` 检查远程传输、加密存储及手机新版工作簿导入。检查使用独立临时目录，不读取现有库存数据。

## 许可与来源

本项目是上游 Android 应用的衍生移植。上游作者及其许可证声明保留；移植始于 2026-10-14，远程备份修改于 2026-11-19。按 GPLv3 发布修改版本，并随源码附上完整许可证。详情见 [LICENSE](LICENSE) 和 [NOTICE](NOTICE)。

第三方 Python 和 Qt 依赖仍各自受其许可证约束。发行压缩包随附其许可证文件和来源链接。
