import os
import base64
import tempfile
import streamlit as st
from markitdown import MarkItDown
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter
from pdf2image import convert_from_path

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

try:
    from pix2tex.cli import LatexOCR
    PIX2TEX_AVAILABLE = True
except ImportError:
    PIX2TEX_AVAILABLE = False

# ─────────────────────────────────────────────
# 页面配置
# ─────────────────────────────────────────────
st.set_page_config(page_title="手写公式转 Markdown", page_icon="📐", layout="wide")
st.title("📐 手写物理 / 数学公式 → Markdown（LaTeX）")
st.markdown("专为**手写笔记**优化，支持向量符号、求和、倒格矢、Kronecker δ 等物理符号。")

# ─────────────────────────────────────────────
# 侧边栏
# ─────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 设置")

    st.markdown("### 🤖 识别引擎")
    engine = st.radio(
        "选择识别引擎",
        [
            "Claude Vision（推荐，最准确）",
            "GOT-OCR 2.0（本地，需 GPU）",
            "pix2tex + Tesseract（本地，印刷体）",
        ],
        index=0,
    )

    # Claude API Key
    if "Claude" in engine:
        st.markdown("### 🔑 Anthropic API Key")
        api_key_input = st.text_input(
            "API Key",
            type="password",
            value=os.environ.get("ANTHROPIC_API_KEY", ""),
            help="从 console.anthropic.com 获取。也可设置环境变量 ANTHROPIC_API_KEY。",
        )
        claude_model = st.selectbox(
            "模型",
            ["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5-20251001"],
            index=1,
            help="Sonnet 性价比最高；Opus 最准确；Haiku 最快最省。",
        )

    # GOT-OCR 设置
    if "GOT-OCR" in engine:
        st.info(
            "GOT-OCR 2.0 需要本地安装：\n"
            "```\npip install transformers torch\n"
            "# 模型会在首次运行时自动下载（约 1.4GB）\n```"
        )

    # Tesseract 设置
    if "pix2tex" in engine:
        ocr_lang = st.selectbox("Tesseract 语言", ["chi_sim+eng", "eng"], index=0)

    st.markdown("### 📐 物理/数学上下文")
    subject_hint = st.selectbox(
        "学科提示（提升识别精度）",
        [
            "固体物理 / 晶格理论",
            "量子力学",
            "电动力学",
            "热统计力学",
            "数学分析",
            "线性代数",
            "通用（不指定）",
        ],
        index=0,
    )

    extra_hint = st.text_area(
        "补充说明（可选）",
        placeholder="例如：这是布洛赫定理的推导，包含倒格矢和 Kronecker delta",
        height=80,
    )

    st.markdown("### 🖼️ 图像预处理")
    enhance_contrast = st.checkbox("增强对比度", value=True)
    denoise = st.checkbox("降噪处理", value=True)
    upscale = st.checkbox("放大图像（低分辨率手机拍照）", value=False)

# ─────────────────────────────────────────────
# 图像预处理
# ─────────────────────────────────────────────

def preprocess_image(img: Image.Image) -> Image.Image:
    """增强手写图片质量"""
    if upscale and max(img.size) < 1500:
        scale = 2
        img = img.resize(
            (img.width * scale, img.height * scale), Image.LANCZOS
        )

    # 转灰度后再增强
    gray = img.convert("L")

    if denoise:
        gray = gray.filter(ImageFilter.MedianFilter(size=3))

    if enhance_contrast:
        enhancer = ImageEnhance.Contrast(gray)
        gray = enhancer.enhance(2.0)
        enhancer = ImageEnhance.Sharpness(gray)
        gray = enhancer.enhance(1.5)

    return gray.convert("RGB")

# ─────────────────────────────────────────────
# 引擎 1：Claude Vision（核心）
# ─────────────────────────────────────────────

# 学科专属提示词
SUBJECT_PROMPTS = {
    "固体物理 / 晶格理论": """这是固体物理的手写推导，可能包含：
- 倒格矢 $\\vec{G}_h = h_1\\vec{b}_1 + h_2\\vec{b}_2 + h_3\\vec{b}_3$
- 布拉菲格矢 $\\vec{R}_n = n_1\\vec{a}_1 + n_2\\vec{a}_2 + n_3\\vec{a}_3$
- 正交关系 $\\vec{a}_i \\cdot \\vec{b}_j = 2\\pi\\delta_{ij}$
- Kronecker delta $\\delta_{\\vec{k},\\vec{G}_h}$
- 布洛赫定理相关求和""",
    "量子力学": """这是量子力学手写推导，可能包含：
- 算符 $\\hat{H}$、$\\hat{p}$、$\\hat{x}$
- 狄拉克符号 $\\langle\\psi|$、$|\\phi\\rangle$、$\\langle\\psi|\\hat{A}|\\phi\\rangle$
- 薛定谔方程、本征值问题""",
    "电动力学": """电动力学推导，可能包含 Maxwell 方程组、场张量等。""",
    "热统计力学": """热统计力学，可能包含配分函数、玻尔兹曼因子、系综平均等。""",
    "数学分析": """数学分析，可能包含极限、级数、积分变换等。""",
    "线性代数": """线性代数，可能包含矩阵运算、特征值分解、张量等。""",
    "通用（不指定）": "",
}

def image_to_base64(img: Image.Image, fmt: str = "JPEG") -> str:
    import io
    buf = io.BytesIO()
    img.save(buf, format=fmt, quality=95)
    return base64.standard_b64encode(buf.getvalue()).decode()

def run_claude_vision(img: Image.Image, api_key: str, model: str) -> str:
    """调用 Claude Vision API 识别手写数学/物理公式"""
    if not ANTHROPIC_AVAILABLE:
        raise Exception("请先安装 anthropic SDK：pip install anthropic")
    if not api_key:
        raise Exception("请在侧边栏填入 Anthropic API Key")

    subject_ctx = SUBJECT_PROMPTS.get(subject_hint, "")
    extra_ctx = f"\n用户补充说明：{extra_hint}" if extra_hint.strip() else ""

    system_prompt = """你是专业的物理/数学手写公式识别专家。
你的任务：将图片中的**全部手写内容**转换为规范的 Markdown 文档（LaTeX 公式）。

输出规则：
1. 所有数学公式用 LaTeX 格式：行内用 $...$，独立公式块用 $$...$$
2. 向量一律用 \\vec{} 表示，如 $\\vec{k}$、$\\vec{R}_n$
3. 上下标要准确，如 $n_1, n_2, n_3$；$M_1, M_2, M_3$
4. Kronecker delta 写作 $\\delta_{ij}$ 或 $\\delta_{\\vec{k},\\vec{G}_h}$
5. 求和号 $\\sum$，乘积号 $\\prod$，保留上下限
6. 中文注释直接保留为中文文本
7. 编号如 (1) 保留在对应公式旁边
8. 不要添加任何额外解释，只输出识别结果的 Markdown"""

    user_content = f"""请识别并转换这张手写物理笔记图片中的所有内容。

{subject_ctx}{extra_ctx}

请按照图片中的顺序逐行输出，保持原有的公式结构和推导逻辑。"""

    client = anthropic.Anthropic(api_key=api_key)

    img_b64 = image_to_base64(img)

    message = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": img_b64,
                        },
                    },
                    {"type": "text", "text": user_content},
                ],
            }
        ],
    )
    return message.content[0].text

# ─────────────────────────────────────────────
# 引擎 2：GOT-OCR 2.0（本地备选）
# ─────────────────────────────────────────────

_got_model = None
_got_tokenizer = None

def run_got_ocr(image_path: str) -> str:
    """
    使用 GOT-OCR 2.0 进行本地识别。
    专为科学文档设计，支持手写数学（需 GPU，约 1.4GB 显存）。
    """
    global _got_model, _got_tokenizer
    try:
        from transformers import AutoTokenizer, AutoModelForCausalLM
        import torch
    except ImportError:
        raise Exception("请安装：pip install transformers torch")

    if _got_model is None:
        with st.spinner("首次加载 GOT-OCR 2.0 模型（约 1.4GB，请耐心等待）..."):
            model_name = "ucaslcl/GOT-OCR2_0"
            _got_tokenizer = AutoTokenizer.from_pretrained(
                model_name, trust_remote_code=True
            )
            _got_model = AutoModelForCausalLM.from_pretrained(
                model_name,
                trust_remote_code=True,
                device_map="auto",
                torch_dtype=torch.float16,
            ).eval()

    # GOT-OCR format 模式：直接输出 LaTeX
    result = _got_model.chat(
        _got_tokenizer,
        image_path,
        ocr_type="format",  # 输出 LaTeX 格式
    )
    return result

# ─────────────────────────────────────────────
# 引擎 3：pix2tex + Tesseract（印刷体兜底）
# ─────────────────────────────────────────────

_pix2tex_model = None

def run_pix2tex_tesseract(img: Image.Image, lang: str) -> str:
    global _pix2tex_model

    parts = []

    # Tesseract 文本
    try:
        text = pytesseract.image_to_string(img, lang=lang, config="--psm 6")
        if text.strip():
            parts.append(text.strip())
    except Exception as e:
        parts.append(f"*(Tesseract 失败: {e})*")

    # pix2tex 公式
    if PIX2TEX_AVAILABLE:
        if _pix2tex_model is None:
            with st.spinner("加载 pix2tex 模型..."):
                _pix2tex_model = LatexOCR()
        try:
            latex = _pix2tex_model(img)
            if latex and len(latex.strip()) > 3:
                parts.append(f"\n$$\n{latex.strip()}\n$$\n")
        except Exception:
            pass

    return "\n\n".join(parts) if parts else "*(未能识别)*"

# ─────────────────────────────────────────────
# PDF 多页处理
# ─────────────────────────────────────────────

def process_pdf(
    pdf_path: str, engine_fn, status_ph
) -> str:
    status_ph.write("🔄 PDF → 图像序列...")
    pages = convert_from_path(pdf_path, dpi=200)
    total = len(pages)
    progress = st.progress(0)
    results = []

    for i, page in enumerate(pages):
        status_ph.write(f"🔍 第 {i+1}/{total} 页...")
        processed = preprocess_image(page)
        text = engine_fn(processed)
        results.append(text)
        progress.progress((i + 1) / total)

    progress.empty()
    return "\n\n---\n\n".join(results)

# ─────────────────────────────────────────────
# 主界面
# ─────────────────────────────────────────────
st.subheader("📤 上传手写笔记图片")
uploaded = st.file_uploader(
    "支持 JPG / PNG / PDF（手机拍照或扫描件）",
    type=["jpg", "jpeg", "png", "pdf"],
)

if uploaded:
    file_ext = uploaded.name.rsplit(".", 1)[-1].lower()

    # 预览
    if file_ext != "pdf":
        col1, col2 = st.columns([1, 1])
        with col1:
            st.image(uploaded, caption="原图", use_container_width=True)

    if st.button("🚀 开始识别"):
        with st.status("🔍 识别中...", expanded=True) as status:
            result_md = ""
            try:
                with tempfile.NamedTemporaryFile(
                    delete=False, suffix=f".{file_ext}"
                ) as tmp:
                    tmp.write(uploaded.getvalue())
                    tmp_path = tmp.name

                # ── 路由到对应引擎 ──────────────────────────────────
                if "Claude" in engine:
                    status.write("🤖 调用 Claude Vision API...")
                    if file_ext == "pdf":
                        def _claude_fn(img):
                            return run_claude_vision(img, api_key_input, claude_model)
                        result_md = process_pdf(tmp_path, _claude_fn, status)
                    else:
                        img = Image.open(tmp_path)
                        img = preprocess_image(img)
                        result_md = run_claude_vision(img, api_key_input, claude_model)

                elif "GOT-OCR" in engine:
                    status.write("🖥️ 运行 GOT-OCR 2.0（本地）...")
                    if file_ext == "pdf":
                        def _got_fn(img):
                            with tempfile.NamedTemporaryFile(
                                delete=False, suffix=".jpg"
                            ) as t:
                                img.save(t.name, "JPEG")
                                return run_got_ocr(t.name)
                        result_md = process_pdf(tmp_path, _got_fn, status)
                    else:
                        img = Image.open(tmp_path)
                        img = preprocess_image(img)
                        with tempfile.NamedTemporaryFile(
                            delete=False, suffix=".jpg"
                        ) as t:
                            img.save(t.name, "JPEG")
                            result_md = run_got_ocr(t.name)

                else:  # pix2tex + Tesseract
                    status.write("📝 pix2tex + Tesseract（仅适合印刷体）...")
                    if file_ext == "pdf":
                        def _fallback_fn(img):
                            return run_pix2tex_tesseract(img, ocr_lang)
                        result_md = process_pdf(tmp_path, _fallback_fn, status)
                    else:
                        img = Image.open(tmp_path)
                        img = preprocess_image(img)
                        result_md = run_pix2tex_tesseract(img, ocr_lang)

                os.unlink(tmp_path)
                status.update(label="✅ 完成！", state="complete", expanded=False)

            except Exception as e:
                status.update(label="❌ 失败", state="error")
                st.error(f"错误：{e}")
                st.stop()

        # ── 展示结果 ────────────────────────────────────────────────
        tab_preview, tab_raw = st.tabs(["🖥 公式渲染预览", "📄 原始 Markdown"])

        with tab_preview:
            with st.container(border=True, height=560):
                st.markdown(result_md)

        with tab_raw:
            st.code(result_md, language="markdown")

        st.download_button(
            "📥 下载 .md 文件",
            data=result_md,
            file_name=f"{os.path.splitext(uploaded.name)[0]}.md",
            mime="text/markdown",
        )