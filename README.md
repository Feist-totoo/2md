# 2md
## 1. 项目概述
2md 是一个基于 Streamlit 框架开发的轻量级 Web 工具类项目，聚焦于 Markdown 相关的可视化操作（如格式处理、内容编辑、批量转换等，可根据实际业务逻辑补充）。项目提供 Windows 平台一键启动脚本，无需复杂的命令行操作，即可快速拉起 Web 应用，降低非技术人员的使用门槛。

## 2. 核心特点
- 轻量化：基于 Streamlit 快速构建，依赖少、启动速度快，无冗余组件；
- 便捷启动：内置 `run.bat` 一键启动脚本（Windows 平台），无需手动输入命令；
- 可视化交互：通过 Web 界面完成操作，无需编写代码，交互友好；
- 跨平台兼容：核心代码 `streamlit_app.py` 可在 Windows/macOS/Linux 运行（仅需调整启动方式）。

## 3. # 手写公式转Markdown工具
```
项目核心
├── 前端交互：Streamlit Web界面
├── 图像处理：PIL/PDF2Image（预处理/裁剪/转换）
├── 智能识别：OpenAI兼容多模态模型（布局分析+公式识别）
└── 结果输出：LaTeX格式Markdown（渲染/下载）
```

## 4. 快速上手
### 4.1 环境前置要求
- 已安装 Python 3.8 及以上版本；
- 安装项目核心依赖 Streamlit：
```bash
pip install streamlit
```

### 4.2 启动方式
#### Windows 平台（推荐）
直接双击项目根目录下的 `run.bat` 文件，脚本会自动启动 Streamlit 应用，启动成功后：
- 控制台会输出 Web 访问地址（默认：`http://localhost:8501`）；
- 部分环境会自动唤起浏览器并打开该地址。

#### macOS/Linux 平台
在项目根目录的终端中执行以下命令：
```bash
streamlit run streamlit_app.py
```

### 4.3 基础使用
启动成功后，访问控制台输出的 Web 地址，即可在可视化界面中完成 Markdown 相关操作（如：在线编辑 MD 内容、预览效果、文件格式转换、批量处理 MD 文件等，具体功能以 `streamlit_app.py` 实际逻辑为准）。
#### 注意：本页面只适配"doubao-seed-2-0-pro-260215"，并需要提供火山引擎的api

## 5. 常见问题&注意事项
- 双击 `run.bat` 闪退：大概率是 Python 未配置到系统环境变量，需先将 Python 安装路径添加到 Windows 环境变量；
- 页面无法访问：检查 8501 端口是否被占用，可修改启动命令指定端口（示例：`streamlit run streamlit_app.py --server.port 8502`）；
- 功能异常：确认 Streamlit 版本与代码兼容，建议使用稳定版（如 1.28.0）：`pip install streamlit==1.28.0`。
