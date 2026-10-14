# LCSC Desktop ERP

立创商城物料管理的非官方 Windows 桌面移植版，基于 [BrokenClient/LCSC_android_erp](https://github.com/BrokenClient/LCSC_android_erp) 改写。上游 Android 项目采用 GPL-3.0；本移植版也按 GPL-3.0-only 发布，并保留上游来源说明。它与立创商城没有官方关联。

## 功能

- 物料搜索、入库和库存管理
- 库位管理、BOM 导入和库存备份
- 物料二维码与标签导出、打印
- 中文和英文界面
- 库存、偏好设置和图片缓存保存在本机

联网功能会向立创商城查询物料信息并下载图片。应用默认把本地数据放在 `%APPDATA%\LCSC_ERP`；可用 `LCSC_ERP_DATA_DIR` 环境变量指定其他目录。

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

构建使用 Python 3.12 和固定版本的依赖。可执行文件目录会生成在 `dist/`，完整发行压缩包和校验文件会生成在 `release/`。创建形如 `v1.0.0` 的 GitHub Release 后，GitHub Actions 会构建 Windows x64 发行包并附加到该 Release；GitHub 同时提供该标签对应的源码压缩包。

可运行 `python scripts/smoke_check.py` 检查程序启动、五个页面、中英文资源和打包程序的配置路径。检查使用独立临时目录，不读取现有库存数据。

## 许可与来源

本项目是上游 Android 应用的衍生移植。上游作者及其许可证声明保留；移植和修改部分标记为 2026-10-14。按 GPLv3 发布修改版本，并随源码附上完整许可证。详情见 [LICENSE](LICENSE) 和 [NOTICE](NOTICE)。

第三方 Python 和 Qt 依赖仍各自受其许可证约束。发行压缩包随附其许可证文件和来源链接。
