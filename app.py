import json
import os
import re
import uuid
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    st.warning("OPENAI_API_KEY 未设置 —— 请在环境变量或 Secrets 中添加该值以启用 AI 生成。")

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

st.set_page_config(page_title="AI To-Do Builder", layout="centered")

st.title("📝 Smart To-Do Builder")
st.markdown(
    "粘贴任意文本摘要，自动生成可编辑的任务清单（含采购项 / 动作 / 负责人 / 紧急程度 / 截止日期），并根据历史编辑持续改进。"
)

with st.expander("使用说明", expanded=False):
    st.markdown(
        """
- 输入：文本总结、会议记录或规划想法。
- 输出：结构化任务（包含采购项、待执行动作、负责人、紧急程度、DDL）。
- 编辑：在表格中直接修改；保存后会作为训练样本，帮助后续生成更贴近真实需求的结果。
- API Key：请设置环境变量 `OPENAI_API_KEY`（在 Replit Secrets 或本地 .env 中配置）。
"""
    )

MEMORY_FILE = Path("feedback_memory.json")
MAX_MEMORY_ITEMS = 25


# --- Sidebar settings
st.sidebar.header("设置")
model = st.sidebar.selectbox("选择模型（若无权限请更换）", options=["gpt-4o-mini", "gpt-4o", "gpt-4"], index=0)
temperature = st.sidebar.slider("Temperature（稳健性越低越保守）", 0.0, 1.0, 0.1, 0.05)
max_tokens = st.sidebar.slider("Max tokens", 200, 2000, 900, 100)

# --- Input area
st.subheader("Step 1 — 粘贴文本 Summary")
summary = st.text_area("文本 summary（粘贴会议记录、规划想法或任务描述）", height=220)

tone = st.selectbox(
    "输出语气 / Tone",
    options=["温柔贴心", "专业简洁", "直接高效"],
    index=1,
)


# --- Memory helpers

def tokenize(text: str) -> set:
    return {token.lower() for token in re.findall(r"[\w']+", text)}


def load_memory() -> list:
    if MEMORY_FILE.exists():
        try:
            with MEMORY_FILE.open("r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []
    return []


def save_memory(memory: list):
    trimmed = memory[-MAX_MEMORY_ITEMS:]
    MEMORY_FILE.write_text(json.dumps(trimmed, ensure_ascii=False, indent=2), encoding="utf-8")


def record_feedback(summary_text: str, ai_todos: list, edited_todos: list):
    if not summary_text:
        return
    memory = load_memory()
    memory.append(
        {
            "summary": summary_text,
            "ai_todos": ai_todos,
            "approved_todos": edited_todos,
        }
    )
    save_memory(memory)


def find_similar_examples(summary_text: str, max_examples: int = 3) -> list:
    memory = load_memory()
    if not memory:
        return []

    target_tokens = tokenize(summary_text)
    if not target_tokens:
        return []

    scored = []
    for item in memory:
        candidate_summary = item.get("summary", "")
        candidate_tokens = tokenize(candidate_summary)
        if not candidate_tokens:
            continue
        intersection = len(target_tokens & candidate_tokens)
        union = len(target_tokens | candidate_tokens)
        score = intersection / union if union else 0
        if score > 0:
            scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [it for _, it in scored[:max_examples]]


# --- Prompt builder

def build_prompt(summary_text: str, tone_choice: str, examples: list) -> str:
    prompt_lines = [
        "You are an AI operations assistant. Convert the provided summary into actionable todos.",
        "Return ONLY valid JSON with this schema:",
        "{",
        "  \"todos\": [",
        "    {",
        "      \"id\": \"<unique id>\",",
        "      \"todo_type\": \"purchase|action\",",
        "      \"purchase_item\": \"<item to purchase or empty>\",",
        "      \"action\": \"<specific action steps, 6-24 words>\",",
        "      \"assign_to\": \"<responsible person or role>\",",
        "      \"urgency\": \"critical|high|medium|low\",",
        "      \"ddl\": \"<ISO date YYYY-MM-DD or relative deadline>\"",
        "    }",
        "  ]",
        "}",
        "Rules:",
        "- Every todo must include an action description.",
        "- If todo_type is 'purchase', describe the item in purchase_item and outline the follow-up action.",
        "- Infer urgency and deadlines when possible; otherwise provide a reasonable default.",
        "- Prioritize clarity and completeness while keeping the tone {}.".format(tone_choice),
    ]

    if examples:
        prompt_lines.append("Use the patterns from these previously approved todos when relevant:")
        for ex in examples:
            trimmed_summary = ex.get("summary", "")[:500]
            approved = ex.get("approved_todos", [])
            prompt_lines.append(
                json.dumps(
                    {
                        "summary": trimmed_summary,
                        "approved_todos": approved,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )

    prompt_lines.append("Meeting summary:")
    prompt_lines.append('"""' + summary_text + '"""')
    prompt_lines.append("Return valid JSON only.")

    return "\n".join(prompt_lines)


# --- OpenAI call

def call_openai_generate(summary_text: str) -> list:
    if not client:
        st.error("未检测到有效的 OPENAI_API_KEY，无法调用模型。")
        return []

    examples = find_similar_examples(summary_text)
    prompt = build_prompt(summary_text, tone, examples)
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as e:
        st.error(f"OpenAI 调用失败：{e}")
        return []

    text = response.choices[0].message.content if response.choices else ""
    if not text:
        st.error("模型未返回内容，请稍后重试。")
        return []

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        try:
            start = text.index("{")
            end = text.rindex("}")
            parsed = json.loads(text[start : end + 1])
        except Exception:
            st.error("无法解析模型输出为 JSON，以下为原始返回内容：")
            st.code(text[:2000])
            return []

    todos = parsed.get("todos", [])
    cleaned = []
    for todo in todos:
        cleaned.append(
            {
                "id": todo.get("id") or str(uuid.uuid4()),
                "todo_type": todo.get("todo_type", "action"),
                "purchase_item": todo.get("purchase_item", ""),
                "action": todo.get("action", ""),
                "assign_to": todo.get("assign_to", ""),
                "urgency": todo.get("urgency", "medium"),
                "ddl": todo.get("ddl", ""),
                "done": bool(todo.get("done", False)),
            }
        )

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
                st.session_state["ai_original_todos"] = items
                st.session_state["current_summary"] = summary
                st.success(f"已生成 {len(items)} 项任务（请在表格中核对并编辑）")
            else:
                st.error("未能生成任务，请检查 summary 内容或稍后重试。")


# --- Editable table
if "todos" in st.session_state and st.session_state["todos"]:
    st.subheader("📋 生成并可编辑的任务清单 / Editable To-Do List")
    df = pd.DataFrame(st.session_state["todos"])
    display_df = df[
        ["id", "todo_type", "purchase_item", "action", "assign_to", "urgency", "ddl", "done"]
    ].copy()
    display_df.rename(
        columns={
            "id": "ID",
            "todo_type": "类型 / Type",
            "purchase_item": "采购项 / Purchase Item",
            "action": "待执行动作 / Action",
            "assign_to": "负责人 / Assign To",
            "urgency": "紧急程度 / Urgency",
            "ddl": "DDL (截止时间)",
            "done": "完成 / Done",
        },
        inplace=True,
    )

    edited = st.experimental_data_editor(display_df, num_rows="dynamic", use_container_width=True)

    if st.button("保存修改"):
        new_list = []
        for _, row in edited.iterrows():
            new_list.append(
                {
                    "id": row["ID"],
                    "todo_type": row["类型 / Type"],
                    "purchase_item": row["采购项 / Purchase Item"],
                    "action": row["待执行动作 / Action"],
                    "assign_to": row["负责人 / Assign To"],
                    "urgency": row["紧急程度 / Urgency"],
                    "ddl": row["DDL (截止时间)"],
                    "done": bool(row["完成 / Done"]),
                }
            )

        st.session_state["todos"] = new_list
        if st.session_state.get("current_summary") and st.session_state.get("ai_original_todos"):
            record_feedback(
                st.session_state["current_summary"],
                st.session_state.get("ai_original_todos", []),
                new_list,
            )
        st.success("已保存修改并写入学习记录。")

    to_export = pd.DataFrame(st.session_state["todos"]).loc[
        :,
        ["todo_type", "purchase_item", "action", "assign_to", "urgency", "ddl", "done"],
    ]
    csv_bytes = to_export.to_csv(index=False).encode("utf-8")
    st.download_button(
        "导出 CSV / Download CSV",
        data=csv_bytes,
        file_name="smart_todos.csv",
        mime="text/csv",
    )

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("清空当前任务（Clear）"):
            st.session_state["todos"] = []
            st.success("任务已清空。")
    with col_b:
        if st.button("追加空任务（Add blank task）"):
            st.session_state["todos"].append(
                {
                    "id": str(uuid.uuid4()),
                    "todo_type": "action",
                    "purchase_item": "",
                    "action": "",
                    "assign_to": "",
                    "urgency": "medium",
                    "ddl": "",
                    "done": False,
                }
            )
            st.experimental_rerun()
else:
    st.info("生成的 To-Do 会在此处显示。粘贴 summary 并点击“生成 To-Do”。")
