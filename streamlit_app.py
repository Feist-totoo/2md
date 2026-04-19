import os
import base64
import io
import tempfile
import requests
import streamlit as st
import time
from PIL import Image
from pdf2image import convert_from_path

# ─────────────────────────────────────────────
# PaddleOCR-VL-1.5 API 配置
# ─────────────────────────────────────────────
PADDLEOCR_API_URL = "https://z8t5weoff78et3d2.aistudio-app.com/layout-parsing"
DEFAULT_TOKEN =""

# ─────────────────────────────────────────────
# 页面配置
# ─────────────────────────────────────────────
st.set_page_config(page_title="手写公式转 Markdown", page_icon="📐", layout="centered")
st.title("📐 手写物理 / 数学公式 → Markdown（LaTeX）")
st.markdown(
    "由 **PaddleOCR-VL-1.5** 驱动，专为**手写笔记**优化，支持数学公式、物理推导、中英文混排识别。"
)

# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────

def image_to_base64(img: Image.Image, quality: int = 95) -> str:
    """将 PIL Image 编码为 base64 JPEG 字符串。"""
    buf = io.BytesIO()
    # 转换为 RGB 以避免 PNG alpha 通道带来的保存报错
    if img.mode != 'RGB':
        img = img.convert('RGB')
    img.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def bytes_to_base64(raw_bytes: bytes) -> str:
    """将原始字节编码为 base64 字符串。"""
    return base64.b64encode(raw_bytes).decode("ascii")


# ─────────────────────────────────────────────
# PaddleOCR-VL-1.5 核心调用
# ─────────────────────────────────────────────

def call_paddleocr(
    file_data_b64: str,
    file_type: int,           # 0 = PDF, 1 = 图像
    token: str,
    timeout: int = 120,
) -> list[str]:
    """
    调用 PaddleOCR-VL-1.5 布局解析 API。
    返回每页/每结果对应的 Markdown 字符串列表。
    """
    headers = {
        "Authorization": f"token {token}",
        "Content-Type": "application/json",
    }
    # 默认保持关闭影响速度的选项，保持极简策略
    payload = {
        "file": file_data_b64,
        "fileType": file_type,
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useChartRecognition": False,
    }

    response = requests.post(
        PADDLEOCR_API_URL, json=payload, headers=headers, timeout=timeout
    )
    response.raise_for_status()

    result = response.json().get("result", {})
    parsing_results = result.get("layoutParsingResults", [])

    md_pages: list[str] = []
    for res in parsing_results:
        md_text = res.get("markdown", {}).get("text", "")
        md_pages.append(md_text)

    return md_pages


def recognize_image_paddleocr(img: Image.Image, token: str, prog_bar) -> str:
    """
    对单张 PIL Image 调用 PaddleOCR，返回合并后的 Markdown 字符串。
    """
    prog_bar.progress(20, text="🔄 正在编码图像数据...")
    img_b64 = image_to_base64(img, quality=95)

    prog_bar.progress(50, text="🤖 PaddleOCR 引擎识别中（大概需要10~30秒）...")
    pages = call_paddleocr(
        file_data_b64=img_b64,
        file_type=1,
        token=token,
    )
    prog_bar.progress(90, text="✨ 正在解析排版结果...")

    return "\n\n".join(p for p in pages if p.strip()) or "（未识别到内容）"


def recognize_pdf_paddleocr(pdf_bytes: bytes, token: str, prog_bar) -> str:
    """
    直接将 PDF 原始字节发送给 PaddleOCR。
    """
    prog_bar.progress(20, text="🔄 正在编码原生 PDF 文件...")
    pdf_b64 = bytes_to_base64(pdf_bytes)

    prog_bar.progress(50, text="🤖 PaddleOCR 引擎识别中（多页PDF可能会消耗较长时间）...")
    pages = call_paddleocr(
        file_data_b64=pdf_b64,
        file_type=0,
        token=token,
    )
    prog_bar.progress(90, text="✨ 正在合并 PDF 多页结果...")

    if not pages:
        return "（未识别到内容）"

    parts = []
    for i, md in enumerate(pages):
        if md.strip():
            parts.append(f"\n\n{md}")
    return "\n\n---\n\n".join(parts) or "（未识别到内容）"


# ─────────────────────────────────────────────
# 侧边栏
# ─────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 设置")

    # ── API 鉴权 ──────────────────────────────
    st.markdown("### 🔑 API 鉴权")
    api_token = st.text_input(
        "PaddleOCR API Token",
        type="password",
        value=os.environ.get("PADDLEOCR_TOKEN", DEFAULT_TOKEN),
        help="AIStudio 部署的 PaddleOCR-VL-1.5 访问令牌",
    )

    st.markdown("---")

    # ── 连接测试 ──────────────────────────────
    if st.button("🔌 测试 API 连接", use_container_width=True):
        if not api_token:
            st.error("请先填写 API Token")
        else:
            with st.spinner("测试中..."):
                try:
                    test_img = Image.new("RGB", (1, 1), color=(255, 255, 255))
                    test_b64 = image_to_base64(test_img, quality=50)
                    call_paddleocr(
                        file_data_b64=test_b64,
                        file_type=1,
                        token=api_token,
                        timeout=20,
                    )
                    st.success("✅ 连接成功！服务正常。")
                except Exception as e:
                    st.error(f"❌ 连接失败：{e}")

    st.markdown("---")

    # ── PDF 处理模式 ──────────────────────────
    st.markdown("### 📄 PDF 处理模式")
    pdf_mode = st.radio(
        "PDF 发送方式",
        ["原生 PDF（推荐）", "逐页转图像（兼容模式）"],
        index=0,
        help="推荐使用原生PDF以获得更快的速度。如遇到异常编码文件可选兼容模式。",
    )


# ─────────────────────────────────────────────
# 主界面
# ─────────────────────────────────────────────
uploaded = st.file_uploader(
    "📤 上传手写笔记（JPG / PNG / PDF）",
    type=["jpg", "jpeg", "png", "pdf"],
)

if uploaded:
    file_ext = uploaded.name.rsplit(".", 1)[-1].lower()
    
    # 去除预览，居中摆放识别按钮
    st.markdown("<br/>", unsafe_allow_html=True)
    run = st.button("🚀 开始识别", use_container_width=True, type="primary")

    if run:
        if not api_token:
            st.error("请在左侧侧边栏填写 API Token")
            st.stop()

        # 进度条占位
        prog_bar = st.progress(5, text="准备数据...")
        result_md = ""
        
        try:
            raw_bytes = uploaded.getvalue()

            # ── PDF 处理 ──────────────────────────────────
            if file_ext == "pdf":
                if pdf_mode == "原生 PDF（推荐）":
                    result_md = recognize_pdf_paddleocr(raw_bytes, api_token, prog_bar)
                else:
                    # 逐页转图像兼容模式
                    prog_bar.progress(10, text="🔄 正在将 PDF 转换为图像序列...")
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        tmp.write(raw_bytes)
                        tmp_path = tmp.name

                    pages = convert_from_path(tmp_path, dpi=200)
                    os.unlink(tmp_path)
                    total = len(pages)
                    
                    page_results = []
                    for i, page in enumerate(pages):
                        prog_bar.progress(int(10 + 80 * (i / total)), text=f"📄 正在识别第 {i + 1}/{total} 页...")
                        
                        # 每页识别
                        img_b64 = image_to_base64(page, quality=95)
                        pages_md = call_paddleocr(img_b64, 1, api_token)
                        
                        page_md = "\n\n".join(p for p in pages_md if p.strip())
                        page_results.append(f"\n\n{page_md}")

                    prog_bar.progress(95, text="✨ 正在合并全卷结果...")
                    result_md = "\n\n---\n\n".join(page_results)

            # ── 图像处理 ──────────────────────────────────
            else:
                img = Image.open(io.BytesIO(raw_bytes))
                result_md = recognize_image_paddleocr(img, api_token, prog_bar)

            prog_bar.progress(100, text="✅ 识别完成！")
            time.sleep(0.5) # 给一点停顿时间让用户看清完成进度
            prog_bar.empty() # 完成后可以清空进度条区域保持整洁

            # ── 结果展示 ──────────────────────────────────
            tab_preview, tab_raw = st.tabs(["🖥 公式渲染预览", "📄 原始 Markdown"])
            with tab_preview:
                with st.container(border=True, height=560):
                    st.markdown(result_md, unsafe_allow_html=True)
            with tab_raw:
                st.code(result_md, language="markdown")

            # 提供纯文本 md 下载按钮
            st.download_button(
                "📥 下载 Markdown 文件 (.md)",
                data=result_md,
                file_name=f"{os.path.splitext(uploaded.name)[0]}.md",
                mime="text/markdown",
                use_container_width=True
            )

        except requests.exceptions.HTTPError as e:
            prog_bar.empty()
            st.error(f"❌ API 请求失败 (HTTP {e.response.status_code}): {e.response.text[:400]}")
            st.stop()
        except Exception as e:
            prog_bar.empty()
            st.error(f"❌ 处理过程中发生错误：{e}")
            st.stop()