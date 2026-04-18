import os
import base64
import io
import json
import tempfile
import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter, ImageDraw
from pdf2image import convert_from_path

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

# ─────────────────────────────────────────────
# 页面配置
# ─────────────────────────────────────────────
st.set_page_config(page_title="手写公式转 Markdown", page_icon="📐", layout="wide")
st.title("📐 手写物理 / 数学公式 → Markdown（LaTeX）")
st.markdown("专为**手写笔记**优化，支持向量符号、求和、倒格矢、Kronecker δ 等物理符号。")

# ─────────────────────────────────────────────
# 学科提示词
# ─────────────────────────────────────────────
SUBJECT_PROMPTS = {
    "固体物理 / 晶格理论": """这是固体物理的手写推导，可能包含：
- 倒格矢 $\\vec{G}_h = h_1\\vec{b}_1 + h_2\\vec{b}_2 + h_3\\vec{b}_3$
- 布拉菲格矢 $\\vec{R}_n = n_1\\vec{a}_1 + n_2\\vec{a}_2 + n_3\\vec{a}_3$
- 正交关系 $\\vec{a}_i \\cdot \\vec{b}_j = 2\\pi\\delta_{ij}$
- Kronecker delta $\\delta_{\\vec{k},\\vec{G}_h}$，布洛赫定理相关求和""",
    "量子力学": """这是量子力学手写推导，可能包含算符 $\\hat{H}$、$\\hat{p}$，狄拉克符号 $\\langle\\psi|\\hat{A}|\\phi\\rangle$，薛定谔方程等。""",
    "电动力学": """电动力学推导，可能包含 Maxwell 方程组、场张量、电磁势等。""",
    "热统计力学": """热统计力学，可能包含配分函数 $Z$、玻尔兹曼因子 $e^{-\\beta E}$、系综平均等。""",
    "数学分析": """数学分析，可能包含极限、泰勒展开、Fourier 级数、积分变换等。""",
    "线性代数": """线性代数，可能包含矩阵运算、行列式、特征值分解、张量等。""",
    "通用（不指定）": "",
}

# ─────────────────────────────────────────────
# Prompts
# ─────────────────────────────────────────────

LAYOUT_ANALYSIS_PROMPT = """分析这张手写笔记的**空间布局**，仅输出 JSON，不要任何解释。

识别以下布局模式并返回 JSON 结构：
{
  "layout_type": "single_column" | "two_column" | "main_with_margin" | "grid" | "mixed",
  "regions": [
    {
      "id": "region_1",
      "description": "左列主推导",
      "position": "left | right | top | bottom | full | margin_left | margin_right | margin_top",
      "read_order": 1,
      "approximate_bounds": {"x_pct": 0, "y_pct": 0, "w_pct": 50, "h_pct": 100},
      "content_type": "derivation | equation | diagram | text | label | footnote"
    }
  ],
  "notes": "任何重要的布局说明"
}

approximate_bounds 用百分比表示（0-100），(x_pct, y_pct) 是左上角，(w_pct, h_pct) 是宽高。
read_order 从 1 开始，按自然阅读顺序编号（通常从上到下，从左到右）。"""

SYSTEM_PROMPT_REGION = """你是专业的物理/数学手写公式识别专家。
将图片中这个区域的**全部手写内容**转换为规范的 Markdown 文档（LaTeX 公式）。

输出规则：
1. 数学公式：行内用 $...$，独立公式块用 $$...$$
2. 向量一律用 \\vec{}，如 $\\vec{k}$、$\\vec{R}_n$
3. 上下标要准确，如 $n_1, n_2, n_3$；$M_1, M_2, M_3$
4. Kronecker delta 写作 $\\delta_{ij}$ 或 $\\delta_{\\vec{k},\\vec{G}_h}$
5. 保留求和 $\\sum$、乘积 $\\prod$ 的完整上下限
6. 中文注释原样保留
7. 公式编号如 (1) 保留
8. 严格按图片中内容的**从上到下**顺序输出，不跳行不重排
9. 只输出识别结果，不添加任何解释"""

SYSTEM_PROMPT_SINGLE = """你是专业的物理/数学手写公式识别专家。
将图片中的**全部手写内容**转换为规范的 Markdown 文档（LaTeX 公式）。

布局保留规则（最重要）：
- 严格按照图片中内容的**视觉空间顺序**输出：先上后下，同一行先左后右
- 若存在左右两栏：用 HTML 表格或分隔符区分两栏内容
- 若存在旁注/边注：用 `> 旁注：...` 块引用格式标注
- 若存在多个独立推导块：每块用 `---` 水平线分隔
- 若内容对齐（如等式对齐）：尽量用 `align` 环境：$$\\begin{align}...\\end{align}$$

公式规则：
1. 数学公式：行内用 $...$，独立公式块用 $$...$$
2. 向量一律用 \\vec{}，如 $\\vec{k}$、$\\vec{R}_n$
3. 上下标要准确，如 $n_1, n_2, n_3$
4. Kronecker delta 写作 $\\delta_{ij}$
5. 保留求和 $\\sum$、乘积 $\\prod$ 的完整上下限
6. 中文注释原样保留
7. 公式编号如 (1) 保留
8. 只输出识别结果，不添加任何解释"""

# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────

def image_to_base64(img: Image.Image, quality: int = 95) -> str:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return base64.standard_b64encode(buf.getvalue()).decode()

def preprocess_image(img: Image.Image, enhance_contrast: bool, denoise: bool, upscale: bool) -> Image.Image:
    if upscale and max(img.size) < 1500:
        img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
    gray = img.convert("L")
    if denoise:
        gray = gray.filter(ImageFilter.MedianFilter(size=3))
    if enhance_contrast:
        gray = ImageEnhance.Contrast(gray).enhance(2.0)
        gray = ImageEnhance.Sharpness(gray).enhance(1.5)
    return gray.convert("RGB")

def crop_region(img: Image.Image, bounds: dict) -> Image.Image:
    """按百分比裁剪图像区域，并加少量 padding。"""
    W, H = img.size
    pad = 0.01  # 1% padding
    x = max(0, (bounds["x_pct"] / 100 - pad) * W)
    y = max(0, (bounds["y_pct"] / 100 - pad) * H)
    x2 = min(W, ((bounds["x_pct"] + bounds["w_pct"]) / 100 + pad) * W)
    y2 = min(H, ((bounds["y_pct"] + bounds["h_pct"]) / 100 + pad) * H)
    return img.crop((int(x), int(y), int(x2), int(y2)))

def draw_layout_preview(img: Image.Image, regions: list) -> Image.Image:
    """在图片上绘制识别出的布局区域（用于调试预览）。"""
    preview = img.copy().convert("RGB")
    draw = ImageDraw.Draw(preview)
    colors = ["red", "blue", "green", "orange", "purple", "brown"]
    W, H = preview.size
    for i, region in enumerate(regions):
        b = region.get("approximate_bounds", {})
        if not b:
            continue
        x = b["x_pct"] / 100 * W
        y = b["y_pct"] / 100 * H
        x2 = (b["x_pct"] + b["w_pct"]) / 100 * W
        y2 = (b["y_pct"] + b["h_pct"]) / 100 * H
        color = colors[i % len(colors)]
        draw.rectangle([x, y, x2, y2], outline=color, width=3)
        draw.text((x + 4, y + 4), f"#{region.get('read_order','?')} {region.get('description','')[:20]}", fill=color)
    return preview

def analyze_layout(img: Image.Image, client: OpenAI, model: str) -> dict | None:
    """Pass 1：分析图像布局，返回结构化 JSON 或 None（失败时降级）。"""
    img_b64 = image_to_base64(img, quality=85)
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                        {"type": "text", "text": LAYOUT_ANALYSIS_PROMPT},
                    ],
                }
            ],
            max_tokens=1024,
            temperature=0.0,
        )
        raw = response.choices[0].message.content.strip()
        # 去掉可能的 markdown 代码块包装
        raw = raw.strip("` \n")
        if raw.startswith("json"):
            raw = raw[4:]
        return json.loads(raw)
    except Exception as e:
        return None  # 布局分析失败，降级为单次识别

def call_api_region(img: Image.Image, client: OpenAI, model: str,
                    region_desc: str, subject_hint: str, extra_hint: str) -> str:
    """Pass 2a：识别单个裁剪区域。"""
    img_b64 = image_to_base64(img)
    subject_ctx = SUBJECT_PROMPTS.get(subject_hint, "")
    extra_ctx = f"\n用户补充说明：{extra_hint}" if extra_hint.strip() else ""
    user_msg = f"当前区域：{region_desc}\n\n{subject_ctx}{extra_ctx}\n\n请识别此区域中的所有内容，严格保持从上到下的顺序。"
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_REGION},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                    {"type": "text", "text": user_msg},
                ],
            },
        ],
        max_tokens=4096,
        temperature=0.1,
    )
    return response.choices[0].message.content.strip()

def call_api_single(img: Image.Image, client: OpenAI, model: str,
                    subject_hint: str, extra_hint: str) -> str:
    """Pass 2b（降级）：单次识别整张图，但注入了更强的布局保留指令。"""
    img_b64 = image_to_base64(img)
    subject_ctx = SUBJECT_PROMPTS.get(subject_hint, "")
    extra_ctx = f"\n用户补充说明：{extra_hint}" if extra_hint.strip() else ""
    user_msg = f"""请识别并转换这张手写物理笔记图片中的所有内容。

{subject_ctx}{extra_ctx}

**布局要求**：
- 若图片有左右两栏，请用以下格式输出：
  <LEFT_COLUMN>左栏内容</LEFT_COLUMN>
  <RIGHT_COLUMN>右栏内容</RIGHT_COLUMN>
- 若有边注，用 > 引用块标注
- 若有多个独立推导块，用 --- 分隔
- 严格按视觉顺序（上→下，左→右）逐行输出"""
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_SINGLE},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                    {"type": "text", "text": user_msg},
                ],
            },
        ],
        max_tokens=4096,
        temperature=0.1,
    )
    return response.choices[0].message.content.strip()

def format_multi_region_output(region_results: list[tuple[dict, str]]) -> str:
    """将多区域结果按 read_order 合并为带结构的 Markdown。"""
    sorted_results = sorted(region_results, key=lambda x: x[0].get("read_order", 99))

    layout_types_with_columns = {"two_column", "main_with_margin"}

    # 检测是否有并排的左右区域（同一 read_order 层）
    # 简单策略：如果有 left/right position 的区域，用表格并排
    left_regions = [r for r in sorted_results if "left" in r[0].get("position", "")]
    right_regions = [r for r in sorted_results if "right" in r[0].get("position", "")]
    margin_regions = [r for r in sorted_results if "margin" in r[0].get("position", "")]
    other_regions = [r for r in sorted_results
                     if r not in left_regions and r not in right_regions and r not in margin_regions]

    parts = []

    # 先输出 top/full 区域
    for region, content in other_regions:
        if region.get("position") in ("top", "full"):
            desc = region.get("description", "")
            if desc:
                parts.append(f"<!-- {desc} -->")
            parts.append(content)

    # 左右并排
    if left_regions and right_regions:
        left_content = "\n\n".join(c for _, c in left_regions)
        right_content = "\n\n".join(c for _, c in right_regions)
        parts.append(
            '<div style="display:flex;gap:2em">\n'
            f'<div style="flex:1">\n\n{left_content}\n\n</div>\n'
            f'<div style="flex:1">\n\n{right_content}\n\n</div>\n'
            '</div>'
        )
    elif left_regions:
        for region, content in left_regions:
            parts.append(content)
    elif right_regions:
        for region, content in right_regions:
            parts.append(content)

    # 边注
    for region, content in margin_regions:
        desc = region.get("description", "边注")
        parts.append(f"> **{desc}**\n>\n> " + content.replace("\n", "\n> "))

    # bottom/other 区域
    for region, content in other_regions:
        if region.get("position") not in ("top", "full"):
            desc = region.get("description", "")
            if desc:
                parts.append(f"<!-- {desc} -->")
            parts.append(content)

    return "\n\n---\n\n".join(p for p in parts if p.strip())

def recognize_image(img: Image.Image, client: OpenAI, model: str,
                    subject_hint: str, extra_hint: str,
                    use_two_pass: bool, status) -> tuple[str, Image.Image | None]:
    """
    主识别函数。
    返回 (markdown_result, layout_preview_image_or_None)
    """
    layout_preview = None

    if not use_two_pass:
        status.write("🤖 单次识别模式...")
        return call_api_single(img, client, model, subject_hint, extra_hint), None

    # ── Pass 1：布局分析 ──────────────────────────────
    status.write("🗺️ Pass 1：分析页面布局...")
    layout = analyze_layout(img, client, model)

    if layout is None:
        status.write("⚠️ 布局分析失败，降级为增强单次识别...")
        return call_api_single(img, client, model, subject_hint, extra_hint), None

    regions = layout.get("regions", [])
    layout_type = layout.get("layout_type", "single_column")

    status.write(f"✅ 检测到布局类型：**{layout_type}**，共 {len(regions)} 个区域")

    # 生成布局预览
    layout_preview = draw_layout_preview(img, regions)

    # 如果只有 1 个区域或是 single_column，直接单次识别（避免浪费 API 调用）
    if layout_type == "single_column" or len(regions) <= 1:
        status.write("📄 单列/单区域，使用强化版单次识别...")
        result = call_api_single(img, client, model, subject_hint, extra_hint)
        return result, layout_preview

    # ── Pass 2：逐区域识别 ────────────────────────────
    region_results = []
    for i, region in enumerate(sorted(regions, key=lambda r: r.get("read_order", 99))):
        bounds = region.get("approximate_bounds")
        desc = region.get("description", f"区域 {i+1}")
        status.write(f"🔍 Pass 2 [{i+1}/{len(regions)}]：识别「{desc}」...")

        if bounds and (bounds.get("w_pct", 100) < 95 or bounds.get("h_pct", 100) < 95):
            # 有意义的子区域：裁剪后识别
            region_img = crop_region(img, bounds)
            content = call_api_region(region_img, client, model, desc, subject_hint, extra_hint)
        else:
            # 全图区域：用单次识别
            content = call_api_single(img, client, model, subject_hint, extra_hint)

        region_results.append((region, content))

    return format_multi_region_output(region_results), layout_preview

# ─────────────────────────────────────────────
# 侧边栏
# ─────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 设置")

    st.markdown("### 🔑 API 配置")
    api_key_input = st.text_input(
        "API Key",
        type="password",
        value=os.environ.get("VOLC_API_KEY", ""),
        help="火山引擎 API Key，也可设置环境变量 VOLC_API_KEY",
    )
    api_endpoint = st.text_input(
        "API Endpoint",
        value="https://ark.cn-beijing.volces.com/api/v3",
    )
    model_name = st.text_input(
        "模型名称",
        value="doubao-seed-2-0-pro-260215",
        help="支持任意兼容 OpenAI 格式的多模态模型",
    )

    st.markdown("---")
    if st.button("🔌 测试 API 连接", use_container_width=True):
        if not api_key_input:
            st.error("请先填写 API Key")
        elif not OPENAI_AVAILABLE:
            st.error("请先安装：pip install openai")
        else:
            with st.spinner("测试中..."):
                try:
                    test_client = OpenAI(api_key=api_key_input, base_url=api_endpoint)
                    test_resp = test_client.chat.completions.create(
                        model=model_name,
                        messages=[{"role": "user", "content": "你好，请回复 OK"}],
                        max_tokens=10,
                    )
                    reply = test_resp.choices[0].message.content.strip()
                    st.success(f"✅ 连接成功！模型回复：{reply}")
                except Exception as e:
                    st.error(f"❌ 连接失败：{e}")

    st.markdown("---")
    st.markdown("### 📐 学科提示")
    subject_hint = st.selectbox(
        "学科（提升识别精度）",
        list(SUBJECT_PROMPTS.keys()),
        index=0,
    )
    extra_hint = st.text_area(
        "补充说明（可选）",
        placeholder="例如：这是布洛赫定理的推导，包含倒格矢和 Kronecker delta",
        height=80,
    )

    st.markdown("### 🗺️ 布局识别")
    use_two_pass = st.toggle(
        "两阶段识别（推荐）",
        value=True,
        help="Pass 1 分析布局结构，Pass 2 逐区域识别。\n对多列、边注、复杂排版效果显著；单列内容可关闭以节省 API 调用。",
    )
    show_layout_preview = st.toggle("显示布局分析预览", value=True)

    st.markdown("### 🖼️ 图像预处理")
    enhance_contrast = st.checkbox("增强对比度", value=True)
    denoise = st.checkbox("降噪处理", value=True)
    upscale = st.checkbox("放大图像（低分辨率拍照）", value=False)

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
        if not api_key_input:
            st.error("请在左侧侧边栏填写 API Key")
            st.stop()
        if not OPENAI_AVAILABLE:
            st.error("请先安装：pip install openai")
            st.stop()

        client = OpenAI(api_key=api_key_input, base_url=api_endpoint)

        with st.status("🔍 识别中...", expanded=True) as status:
            result_md = ""
            layout_preview_img = None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_ext}") as tmp:
                    tmp.write(uploaded.getvalue())
                    tmp_path = tmp.name

                if file_ext == "pdf":
                    status.write("🔄 PDF → 图像序列...")
                    pages = convert_from_path(tmp_path, dpi=200)
                    total = len(pages)
                    progress = st.progress(0)
                    page_results = []
                    for i, page in enumerate(pages):
                        status.write(f"📄 第 {i+1}/{total} 页...")
                        processed = preprocess_image(page, enhance_contrast, denoise, upscale)
                        page_md, _ = recognize_image(
                            processed, client, model_name,
                            subject_hint, extra_hint, use_two_pass, status
                        )
                        page_results.append(page_md)
                        progress.progress((i + 1) / total)
                    progress.empty()
                    result_md = "\n\n---\n\n".join(page_results)
                else:
                    img = Image.open(tmp_path)
                    processed = preprocess_image(img, enhance_contrast, denoise, upscale)
                    result_md, layout_preview_img = recognize_image(
                        processed, client, model_name,
                        subject_hint, extra_hint, use_two_pass, status
                    )

                os.unlink(tmp_path)
                status.update(label="✅ 识别完成！", state="complete", expanded=False)

            except Exception as e:
                status.update(label="❌ 识别失败", state="error")
                st.error(f"错误：{e}")
                st.stop()

        # ── 布局分析预览 ─────────────────────────────────
        if layout_preview_img is not None and show_layout_preview:
            with st.expander("🗺️ 布局分析预览（各色框为识别区域）", expanded=False):
                st.image(layout_preview_img, use_container_width=True)

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