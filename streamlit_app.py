import os
import base64
import io
import tempfile
import requests
import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter, ImageDraw
from pdf2image import convert_from_path

# ─────────────────────────────────────────────
# PaddleOCR-VL-1.5 API 配置
# ─────────────────────────────────────────────
PADDLEOCR_API_URL = "https://z8t5weoff78et3d2.aistudio-app.com/layout-parsing"
DEFAULT_TOKEN = "d46b18fed8ee6704eacbf91c022cc549e0c7515c"

# ─────────────────────────────────────────────
# 页面配置
# ─────────────────────────────────────────────
st.set_page_config(page_title="手写公式转 Markdown", page_icon="📐", layout="wide")
st.title("📐 手写物理 / 数学公式 → Markdown（LaTeX）")
st.markdown(
    "由 **PaddleOCR-VL-1.5** 驱动，专为**手写笔记**优化，"
    "支持数学公式、物理推导、中英文混排识别。"
)

# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────

def image_to_base64(img: Image.Image, quality: int = 95) -> str:
    """将 PIL Image 编码为 base64 JPEG 字符串。"""
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def bytes_to_base64(raw_bytes: bytes) -> str:
    """将原始字节编码为 base64 字符串。"""
    return base64.b64encode(raw_bytes).decode("ascii")


def preprocess_image(img: Image.Image, enhance_contrast: bool,
                     denoise: bool, upscale: bool) -> Image.Image:
    """可选图像预处理（对比度增强、降噪、放大）。"""
    if upscale and max(img.size) < 1500:
        img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
    gray = img.convert("L")
    if denoise:
        gray = gray.filter(ImageFilter.MedianFilter(size=3))
    if enhance_contrast:
        gray = ImageEnhance.Contrast(gray).enhance(2.0)
        gray = ImageEnhance.Sharpness(gray).enhance(1.5)
    return gray.convert("RGB")


# ─────────────────────────────────────────────
# PaddleOCR-VL-1.5 核心调用
# ─────────────────────────────────────────────

def call_paddleocr(
    file_data_b64: str,
    file_type: int,           # 0 = PDF, 1 = 图像
    token: str,
    use_orientation: bool,
    use_unwarp: bool,
    use_chart: bool,
    timeout: int = 120,
) -> list[str]:
    """
    调用 PaddleOCR-VL-1.5 布局解析 API。

    返回每页/每结果对应的 Markdown 字符串列表。
    file_type: 0 = PDF 文档, 1 = 图像
    """
    headers = {
        "Authorization": f"token {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "file": file_data_b64,
        "fileType": file_type,
        "useDocOrientationClassify": use_orientation,
        "useDocUnwarping": use_unwarp,
        "useChartRecognition": use_chart,
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


def recognize_image_paddleocr(
    img: Image.Image,
    token: str,
    use_orientation: bool,
    use_unwarp: bool,
    use_chart: bool,
    status,
) -> str:
    """
    对单张 PIL Image 调用 PaddleOCR，返回合并后的 Markdown 字符串。
    """
    status.write("🔄 编码图像...")
    img_b64 = image_to_base64(img, quality=95)

    status.write("🤖 PaddleOCR-VL-1.5 识别中（图像）...")
    pages = call_paddleocr(
        file_data_b64=img_b64,
        file_type=1,
        token=token,
        use_orientation=use_orientation,
        use_unwarp=use_unwarp,
        use_chart=use_chart,
    )

    return "\n\n".join(p for p in pages if p.strip()) or "（未识别到内容）"


def recognize_pdf_paddleocr(
    pdf_bytes: bytes,
    token: str,
    use_orientation: bool,
    use_unwarp: bool,
    use_chart: bool,
    status,
) -> str:
    """
    直接将 PDF 原始字节发送给 PaddleOCR（fileType=0），
    返回所有页面合并后的 Markdown 字符串。
    """
    status.write("🔄 编码 PDF 文件...")
    pdf_b64 = bytes_to_base64(pdf_bytes)

    status.write("🤖 PaddleOCR-VL-1.5 识别中（PDF，原生多页）...")
    pages = call_paddleocr(
        file_data_b64=pdf_b64,
        file_type=0,
        token=token,
        use_orientation=use_orientation,
        use_unwarp=use_unwarp,
        use_chart=use_chart,
    )

    if not pages:
        return "（未识别到内容）"

    # 多页用分隔线区分
    parts = []
    for i, md in enumerate(pages):
        if md.strip():
            parts.append(f"<!-- 第 {i + 1} 页 -->\n\n{md}")
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
                    # 生成一张 1×1 白色测试图
                    test_img = Image.new("RGB", (1, 1), color=(255, 255, 255))
                    test_b64 = image_to_base64(test_img, quality=50)
                    call_paddleocr(
                        file_data_b64=test_b64,
                        file_type=1,
                        token=api_token,
                        use_orientation=False,
                        use_unwarp=False,
                        use_chart=False,
                        timeout=20,
                    )
                    st.success("✅ 连接成功！PaddleOCR-VL-1.5 服务正常。")
                except requests.exceptions.HTTPError as e:
                    st.error(f"❌ HTTP 错误：{e.response.status_code} — {e.response.text[:200]}")
                except Exception as e:
                    st.error(f"❌ 连接失败：{e}")

    st.markdown("---")

    # ── PDF 处理模式 ──────────────────────────
    st.markdown("### 📄 PDF 处理模式")
    pdf_mode = st.radio(
        "PDF 发送方式",
        ["原生 PDF（推荐）", "逐页转图像（兼容模式）"],
        index=0,
        help=(
            "**原生 PDF**：直接将 PDF 发给 PaddleOCR，速度更快，支持矢量文字。\n\n"
            "**逐页转图像**：将每页转为图像后分别识别，适合扫描件 / 特殊编码 PDF。"
        ),
    )

    st.markdown("---")

    # ── OCR 选项 ─────────────────────────────
    st.markdown("### 🧠 OCR 选项")
    use_orientation = st.toggle(
        "自动校正文档方向",
        value=False,
        help="对旋转/倒置的扫描件有帮助，但会略微增加耗时",
    )
    use_unwarp = st.toggle(
        "文档展平（拍照去畸变）",
        value=False,
        help="适合手机拍照、页面弯曲的情况",
    )
    use_chart = st.toggle(
        "图表识别",
        value=False,
        help="识别图片中的图表内容（公式笔记一般不需要）",
    )

    st.markdown("---")

    # ── 图像预处理 ────────────────────────────
    st.markdown("### 🖼️ 图像预处理（仅对图像有效）")
    enhance_contrast = st.checkbox("增强对比度 / 锐化", value=False,
                                   help="浅色铅笔、褪色墨水可开启；深色钢笔建议关闭")
    denoise = st.checkbox("中值滤波降噪", value=False,
                          help="扫描件有噪点时开启；拍照清晰时建议关闭")
    upscale = st.checkbox("放大图像（低分辨率）", value=False,
                          help="长边 < 1500 px 时自动 2× 放大")

# ─────────────────────────────────────────────
# 主界面
# ─────────────────────────────────────────────
uploaded = st.file_uploader(
    "📤 上传手写笔记（JPG / PNG / PDF）",
    type=["jpg", "jpeg", "png", "pdf"],
)

if uploaded:
    file_ext = uploaded.name.rsplit(".", 1)[-1].lower()

    col_img, col_btn = st.columns([3, 1])
    with col_img:
        if file_ext != "pdf":
            st.image(uploaded, caption="原图预览", use_container_width=True)
        else:
            st.info(f"📄 已上传 PDF：{uploaded.name}")

    with col_btn:
        st.markdown("<div style='height:32px'></div>", unsafe_allow_html=True)
        run = st.button("🚀 开始识别", use_container_width=True, type="primary")

    if run:
        if not api_token:
            st.error("请在左侧侧边栏填写 API Token")
            st.stop()

        with st.status("🔍 PaddleOCR 识别中...", expanded=True) as status:
            result_md = ""
            try:
                raw_bytes = uploaded.getvalue()

                # ── PDF ───────────────────────────────────────
                if file_ext == "pdf":
                    if pdf_mode == "原生 PDF（推荐）":
                        result_md = recognize_pdf_paddleocr(
                            pdf_bytes=raw_bytes,
                            token=api_token,
                            use_orientation=use_orientation,
                            use_unwarp=use_unwarp,
                            use_chart=use_chart,
                            status=status,
                        )
                    else:
                        # 逐页转图像模式
                        status.write("🔄 PDF → 图像序列（兼容模式）...")
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                            tmp.write(raw_bytes)
                            tmp_path = tmp.name

                        pages = convert_from_path(tmp_path, dpi=200)
                        os.unlink(tmp_path)
                        total = len(pages)
                        progress = st.progress(0)
                        page_results = []

                        for i, page in enumerate(pages):
                            status.write(f"📄 第 {i + 1}/{total} 页...")
                            processed = preprocess_image(page, enhance_contrast, denoise, upscale)
                            page_md = recognize_image_paddleocr(
                                img=processed,
                                token=api_token,
                                use_orientation=use_orientation,
                                use_unwarp=use_unwarp,
                                use_chart=use_chart,
                                status=status,
                            )
                            page_results.append(f"<!-- 第 {i + 1} 页 -->\n\n{page_md}")
                            progress.progress((i + 1) / total)

                        progress.empty()
                        result_md = "\n\n---\n\n".join(page_results)

                # ── 图像 ──────────────────────────────────────
                else:
                    img = Image.open(io.BytesIO(raw_bytes))
                    # 仅在用户开启预处理时才处理
                    if enhance_contrast or denoise or upscale:
                        status.write("🖼️ 预处理图像...")
                        img = preprocess_image(img, enhance_contrast, denoise, upscale)

                    result_md = recognize_image_paddleocr(
                        img=img,
                        token=api_token,
                        use_orientation=use_orientation,
                        use_unwarp=use_unwarp,
                        use_chart=use_chart,
                        status=status,
                    )

                status.update(label="✅ 识别完成！", state="complete", expanded=False)

            except requests.exceptions.HTTPError as e:
                status.update(label="❌ API 请求失败", state="error")
                st.error(f"HTTP {e.response.status_code}：{e.response.text[:400]}")
                st.stop()
            except Exception as e:
                status.update(label="❌ 识别失败", state="error")
                st.error(f"错误：{e}")
                st.stop()

        # ── 结果展示 ─────────────────────────────────────
        tab_preview, tab_raw = st.tabs(["🖥 公式渲染预览", "📄 原始 Markdown"])
        with tab_preview:
            with st.container(border=True, height=560):
                st.markdown(result_md, unsafe_allow_html=True)
        with tab_raw:
            st.code(result_md, language="markdown")

        st.download_button(
            "📥 下载 .md 文件",
            data=result_md,
            file_name=f"{os.path.splitext(uploaded.name)[0]}.md",
            mime="text/markdown",
        )