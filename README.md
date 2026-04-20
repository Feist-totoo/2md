# 2md

> 手写物理 / 数学笔记 → Markdown（LaTeX）转换工具。

---

## ✨ 特性

- 📐 **公式识别** — 深度理解手写数学推导、物理方程，输出标准 LaTeX 语法
- 🌐 **中英文混排** — 正文与公式混合排版一并识别，保留文档结构
- 📄 **PDF 原生支持** — 直接发送 PDF 字节流，无需逐页转图，多页文档快速处理
- 🔀 **兼容模式** — PDF 逐页转图像兜底方案，应对异常编码文件
- 🖥 **渲染预览** — 识别结果即时渲染为 LaTeX 公式，所见即所得
- 📥 **一键下载** — 导出标准 `.md` 文件，直接粘入 Obsidian / Typora / Notion

---

## 🛠 技术栈

| 层次 | 技术 |
|------|------|
| UI 框架 | [Streamlit](https://streamlit.io) |
| OCR 引擎 | [PaddleOCR-VL-1.5](https://aistudio.baidu.com)（云端 API） |
| PDF 处理 | pdf2image · Pillow |
| 运行环境 | Python 3.10+ |

---

## 🚀 快速开始

```bash
# 1. 克隆仓库
git clone https://github.com/Feist-totoo/2md.git
cd 2md

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动
streamlit run streamlit_app.py
```

> **注意**：需要在侧边栏填写 AIStudio 部署的 PaddleOCR API Token 才能使用识别功能。

---

## 📖 使用说明

1. 在左侧侧边栏填入 **API Token**，可点击「测试 API 连接」验证
2. 上传手写笔记图片（JPG / PNG）或 PDF 文件
3. 按需选择 PDF 处理模式（原生 / 兼容）
4. 点击「🚀 开始识别」
5. 在「公式渲染预览」tab 查看效果，或在「原始 Markdown」tab 复制文本
6. 点击「📥 下载 Markdown 文件」导出

---

## 📁 项目结构

```
2md/
├── streamlit_app.py   # 主程序
└── requirements.txt
```