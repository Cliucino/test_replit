# app.py
import os
import json
import uuid
from datetime import datetime
import streamlit as st
import pandas as pd
import openai
from dotenv import load_dotenv

# Load .env locally if present (Replit uses Secrets)
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    st.warning("OPENAI_API_KEY 未设置 —— 请在环境变量中添加 OPENAI_API_KEY（在 Replit Secrets 或本地 .env）")
openai.api_key = OPENAI_API_KEY

st.set_page_config(page_title="Wedding To-Do Generator MVP", layout="centered")

st.title("💍 Wedding To-Do Generator — MVP")
st.markdown(
    "温柔风格（中英双语）→ 粘贴会议 summary，自动生成结构化任务清单（采购 / 婚礼当天 / 负责人 / 紧急程度 / 截止日期）。"
)

with st.expander("说明（点击查看）", expanded=False):
    st.markdown(
        """
- 输入：会议 summary（纯文字） — 支持中文 / 英文或混合文本。  
- 输出：结构化任务（包含 `category`、`task_zh`、`task_en`、`assign_to`、`urgency`、`ddl`）。  
- 编辑：可在表格中直接修改任务、负责人、DDL 或紧急度；修改后可导出 CSV。  
- API Key：请设置环境变量 `OPENAI_API_KEY`（Replit 在 Secrets 中设置）。  
"""
    )

# --- Sidebar settings
st.sidebar.header("设置")
model = st.sidebar.selectbox("选择模型（若无权限请更换）", options=["gpt-4o-mini", "gpt-4o", "gpt-4"], index=0)
temperature = st.sidebar.slider("Temperature（稳健性越低越保守）", 0.0, 1.0, 0.0, 0.05)
max_tokens = st.sidebar.slider("Max tokens", 200, 2000, 800, 100)

# --- Input area
st.subheader("Step 1 — 粘贴会议 Summary / Paste meeting summary")
summary = st.text_area("会议 summary（粘贴 read.ai 的摘要或会议记录）", height=220)

col1, col2 = st.columns([1, 1])
with col1:
    tone = st.selectbox("生成语气 / Tone（用于任务描述风格）", options=["温柔贴心（婚礼风）", "专业简洁", "简洁直接"], index=0)
with col2:
    language_mode = st.selectbox("输出语言 / Output language", options=["中英文（Task_ZH + Task_EN）"], index=0)

# --- Utility: prompt builder
def build_prompt(summary_text: str, tone_choice: str):
    """
    Build a prompt that instructs the LLM to return ONLY JSON with the required schema.
    We request both Chinese and English task strings.
    """
    prompt = f"""
You are a gentle, professional wedding planning assistant. From the meeting summary below, extract all actionable tasks.
Return ONLY a JSON object (no extra text). Schema:

{{
  "todos": [
    {{
      "id": "<unique id>",
      "category": "purchase|wedding|logistics|paperwork|other",
      "task_zh": "<task description in Chinese, warm tone, 6-18 words>",
      "task_en": "<task description in English, concise, 6-18 words>",
      "assign_to": "<person or role, e.g., 'Flora', 'Bride & Groom', 'Planner', or empty>",
      "urgency": "critical|high|medium|low",
      "ddl": "<ISO date YYYY-MM-DD or short text like '1 week before'>",
      "source": "ai",
      "confidence": 0.0
    }}
  ]
}}

Use the meeting summary below. Infer reasonable urgency and ddl when temporal clues exist. For purchases (flowers, cake, favors, decor), set category to 'purchase'. For items explicitly about wedding day ops set 'wedding'. Keep task_zh warm and friendly. Keep task_en concise and actionable.

Meeting summary:
\"\"\"{summary_text}
\"\"\"

Produce valid JSON only.
"""
    return prompt

# --- Call OpenAI
def call_openai_generate(summary_text: str) -> list:
    prompt = build_prompt(summary_text, tone)
    try:
        response = openai.ChatCompletion.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as e:
        st.error(f"OpenAI 调用失败：{e}")
        return []

    # find response text
    text = response.choices[0].message.get("content") if response.choices else ""
    if not text:
        text = response.choices[0].get("text", "") if response.choices else ""

    # try to parse JSON
    try:
        parsed = json.loads(text)
    except Exception:
        # try to extract json substring
        try:
            start = text.index("{")
            end = text.rindex("}")
            sub = text[start:end+1]
            parsed = json.loads(sub)
        except Exception as e:
            st.error("无法解析模型输出为 JSON。输出片段预览已在下方。")
            st.code(text[:2000])
            return []

    todos = parsed.get("todos", [])
    cleaned = []
    for i, t in enumerate(todos):
        item = {
            "id": t.get("id") or str(uuid.uuid4()),
            "category": t.get("category", "other"),
            "task_zh": t.get("task_zh", ""),
            "task_en": t.get("task_en", ""),
            "assign_to": t.get("assign_to", ""),
            "urgency": t.get("urgency", "medium"),
            "ddl": t.get("ddl", ""),
            "done": False,
            "source": t.get("source", "ai"),
            "confidence": float(t.get("confidence", 0.8))
        }
        cleaned.append(item)
    return cleaned

# --- Generate button
if st.button("生成 To-Do（Generate To-Do）"):
    if not summary or len(summary.strip()) < 10:
        st.warning("请输入至少一段会议摘要文本。")
    else:
        with st.spinner("正在调用 AI 生成任务，请稍候..."):
            items = call_openai_generate(summary)
            if items:
                st.session_state["todos"] = items
                st.success(f"已生成 {len(items)} 项任务（请在表格中核对并编辑）")
            else:
                st.error("未能生成任务，请检查 summary 内容或稍后重试。")

# --- Show editable table if exists
if "todos" in st.session_state and st.session_state["todos"]:
    st.subheader("📋 生成并可编辑的任务清单 / Editable To-Do List")
    df = pd.DataFrame(st.session_state["todos"])
    # reorder & display columns bilingual headers
    display_df = df[["id", "category", "task_zh", "task_en", "assign_to", "urgency", "ddl", "done"]].copy()
    display_df.rename(columns={
        "id": "ID",
        "category": "类别 / Category",
        "task_zh": "任务（中文）",
        "task_en": "Task (EN)",
        "assign_to": "负责人 / Assign To",
        "urgency": "紧急程度 / Urgency",
        "ddl": "DDL (截止时间)",
        "done": "完成 / Done"
    }, inplace=True)

    edited = st.experimental_data_editor(display_df, num_rows="dynamic")
    # Save back to session_state normalized list
    if st.button("保存修改"):
        # normalize edited back to todos
        new_list = []
        for _, row in edited.iterrows():
            new_item = {
                "id": row["ID"],
                "category": row["类别 / Category"],
                "task_zh": row["任务（中文）"],
                "task_en": row["Task (EN)"],
                "assign_to": row["负责人 / Assign To"],
                "urgency": row["紧急程度 / Urgency"],
                "ddl": row["DDL (截止时间)"],
                "done": bool(row["完成 / Done"]),
            }
            new_list.append(new_item)
        st.session_state["todos"] = new_list
        st.success("已保存修改到会话（session）。")

    # Export CSV
    to_export = pd.DataFrame(st.session_state["todos"]).loc[:, ["category","task_zh","task_en","assign_to","urgency","ddl","done"]]
    csv_bytes = to_export.to_csv(index=False).encode("utf-8")
    st.download_button("导出 CSV / Download CSV", data=csv_bytes, file_name="wedding_todos.csv", mime="text/csv")

    # Quick actions
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("清空当前任务（Clear）"):
            st.session_state["todos"] = []
            st.success("任务已清空。")
    with col_b:
        if st.button("追加空任务（Add blank task）"):
            new = {
                "id": str(uuid.uuid4()),
                "category": "other",
                "task_zh": "",
                "task_en": "",
                "assign_to": "",
                "urgency": "medium",
                "ddl": "",
                "done": False
            }
            st.session_state["todos"].append(new)
            st.experimental_rerun()

else:
    st.info("生成的 To-Do 会在此处显示。粘贴 summary 并点击“生成 To-Do”。")
