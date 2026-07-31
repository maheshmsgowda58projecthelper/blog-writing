from __future__ import annotations

import json
import re
import zipfile
from datetime import date
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional, List, Iterator, Tuple

import pandas as pd
import streamlit as st
from datetime import datetime
from generation_settings import GenerationSettings
from generation_settings_panel import (
    render_generation_settings_panel,
)

# -----------------------------
# Import your compiled LangGraph app
# -----------------------------
from bwa_backend import (
    blog_writer_agent,
    generate_pdf_bytes
)

from database import *

import plotly.express as px

init_db()

IMAGES_DIR = Path("images")


# -----------------------------
# Helpers
# -----------------------------
def safe_slug(title: str) -> str:
    s = title.strip().lower()
    s = re.sub(r"[^a-z0-9 _-]+", "", s)
    s = re.sub(r"\s+", "_", s).strip("_")
    return s or "blog"


def bundle_zip_from_specs(
    md_text: str,
    md_filename: str,
    specs,
    images_dir: Path
) -> bytes:

    buf = BytesIO()

    with zipfile.ZipFile(
        buf,
        "w",
        compression=zipfile.ZIP_DEFLATED
    ) as z:

        z.writestr(
            md_filename,
            md_text.encode("utf-8")
        )

        for spec in specs:

            filename = spec.get(
                "filename"
            )

            if not filename:
                continue

            img_path = (
                images_dir /
                filename
            )

            if img_path.exists():

                z.write(
                    img_path,
                    arcname=filename
                )
    buf.seek(0)
    return buf.getvalue()


def images_zip_from_specs(
    specs,
    images_dir: Path
) -> Optional[bytes]:

    if not specs:
        return None

    buf = BytesIO()

    with zipfile.ZipFile(
        buf,
        "w",
        compression=zipfile.ZIP_DEFLATED
    ) as z:

        for spec in specs:

            filename = spec.get(
                "filename"
            )

            if not filename:
                continue

            img_path = (
                images_dir /
                filename
            )

            if img_path.exists():

                z.write(
                    img_path,
                    arcname=filename
                )

    buf.seek(0)
    return buf.getvalue()


def try_stream(
    graph_app,
    inputs: Dict[str, Any]
) -> Iterator[Tuple[str, Any]]:
    """
    Stream the complete graph state.

    If streaming fails, execute the graph once with invoke().
    """

    try:

        final_state = None

        for state in graph_app.stream(
            inputs,
            stream_mode="values"
        ):

            final_state = state

            yield (
                "values",
                state
            )

        if final_state is not None:

            yield (
                "final",
                final_state
            )

        return

    except Exception as e:

        print(
            f"Streaming failed: {e}"
        )

        out = graph_app.invoke(
            inputs
        )

        yield (
            "final",
            out
        )


def extract_latest_state(current_state: Dict[str, Any], step_payload: Any) -> Dict[str, Any]:
    if isinstance(step_payload, dict):
        if len(step_payload) == 1 and isinstance(next(iter(step_payload.values())), dict):
            inner = next(iter(step_payload.values()))
            current_state.update(inner)
        else:
            current_state.update(step_payload)
    return current_state


def enrich_loaded_blog_data(
    loaded_data
):

    if loaded_data is None:
        return None

    final_md = loaded_data.get(
        "final",
        ""
    )

    loaded_data["pdf_bytes"] = (
        generate_pdf_bytes(
            final_md
        )
    )

    return loaded_data
# -----------------------------
# Markdown rest.session_state[nderer that supports local images
# -----------------------------
_MD_IMG_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<src>[^)]+)\)")
_CAPTION_LINE_RE = re.compile(r"^\*(?P<cap>.+)\*$")


def _resolve_image_path(src: str) -> Path:
    src = src.strip().lstrip("./")
    return Path(src).resolve()


def render_markdown_with_local_images(md: str):
    matches = list(_MD_IMG_RE.finditer(md))
    if not matches:
        st.markdown(md, unsafe_allow_html=False)
        return

    parts: List[Tuple[str, str]] = []
    last = 0
    for m in matches:
        before = md[last : m.start()]
        if before:
            parts.append(("md", before))

        alt = (m.group("alt") or "").strip()
        src = (m.group("src") or "").strip()
        parts.append(("img", f"{alt}|||{src}"))
        last = m.end()

    tail = md[last:]
    if tail:
        parts.append(("md", tail))

    i = 0
    while i < len(parts):
        kind, payload = parts[i]

        if kind == "md":
            st.markdown(payload, unsafe_allow_html=False)
            i += 1
            continue

        alt, src = payload.split("|||", 1)

        caption = None
        if i + 1 < len(parts) and parts[i + 1][0] == "md":
            nxt = parts[i + 1][1].lstrip()
            if nxt.strip():
                first_line = nxt.splitlines()[0].strip()
                mcap = _CAPTION_LINE_RE.match(first_line)
                if mcap:
                    caption = mcap.group("cap").strip()
                    rest = "\n".join(nxt.splitlines()[1:])
                    parts[i + 1] = ("md", rest)

        if src.startswith("http://") or src.startswith("https://"):
            st.image(src, caption=caption or (alt or None), width="stretch")
        else:
            img_path = _resolve_image_path(src)
            if img_path.exists():
                st.image(str(img_path), caption=caption or (alt or None), width="stretch")
            else:
                st.warning(f"Image not found: `{src}` (looked for `{img_path}`)")

        i += 1


# -----------------------------
# ✅ NEW: Past blogs helpers
# -----------------------------
def list_past_blogs() -> List[Path]:
    """
    Returns all blog markdown files from blogs/ folder,
    newest first.
    """

    blogs_dir = Path("blogs")

    if not blogs_dir.exists():
        return []

    files = [
        p
        for p in blogs_dir.glob("*.md")
        if p.is_file()
        and p.name.lower() != "readme.md"
    ]

    files.sort(
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )

    return files


def read_md_file(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def extract_title_from_md(md: str, fallback: str) -> str:
    """
    Use first '# ' heading as title if present.
    """
    for line in md.splitlines():
        if line.startswith("# "):
            t = line[2:].strip()
            return t or fallback
    return fallback

def load_blog_data(
    filename
):

    json_file = (
        Path("blog_data")
        / filename.replace(
            ".md",
            ".json"
        )
    )

    if not json_file.exists():

        return None

    

    try:
        return json.loads(
            json_file.read_text(
                encoding="utf-8"
            )
        )
    except Exception:
        return None

# ==========================================
# Count Successfully Generated Images
# ==========================================

def count_generated_images(
    image_specs,
    images_dir: Path,
) -> int:
    """
    Count only images that belong to the current blog
    and were successfully generated.
    """

    if not image_specs:
        return 0

    count = 0

    for spec in image_specs:

        filename = spec.get("filename")

        if not filename:
            continue

        img_path = images_dir / filename

        if img_path.exists():
            count += 1

    return count

# -----------------------------
# Streamlit UI
# -----------------------------
st.set_page_config(page_title="LangGraph Blog Writer", layout="wide")

st.title("Blog Writing Agent")

#Slidebar

with st.sidebar:

    st.header("🤖 Blog Writing Agent")

    topic = st.text_area(
        "📝 Blog Topic",
        height=120,
        placeholder="Enter your topic..."
    )

    generation_settings = render_generation_settings_panel()
    
    st.session_state[
        "generation_settings"
    ] = generation_settings

    run_btn = st.button(
        "🚀 Generate Blog",
        type="primary",
        width="stretch"
    )

    # ==========================================
    # Search
    # ==========================================

    st.divider()

    search_query = st.text_input(
        "🔍 Search Blog"
    )

    if search_query:

        blogs = search_blogs(
            search_query
        )

    else:

        blogs = get_all_blogs()

    # ==========================================
    # Pinned Blogs
    # ==========================================

    st.markdown(
        "### 📌 Pinned Blogs"
    )

    pinned = get_pinned_blogs()

    if pinned:

        for blog in pinned:

            label = (
                f"⭐ {blog['display_title']}"
            )

            if st.button(
                label,
                key=f"pinned_{blog['id']}"
            ):

                blog_file = (
                    Path("blogs")
                    / blog["filename"]
                )

                if blog_file.exists():

                    
                    
                    loaded_data = enrich_loaded_blog_data(
                        load_blog_data(
                            blog["filename"]
                        )
                    )


                    st.session_state[
                        "selected_blog_id"
                    ] = blog["id"]
                    
                    
                    
                    if loaded_data is not None:

                        st.session_state[
                            "last_out"
                        ] = loaded_data

                    else:
                        md_text = read_md_file(blog_file)
                        st.session_state[
                            "last_out"
                        ] = {
                            "plan": None,
                            "evidence": [],
                            "image_specs": [],
                            "image_errors": [],
                            "timeline": [],
                            "seo": {},
                            "pdf_bytes": None,
                            "final": md_text,
                        }

                    st.rerun()
                else:

                    st.error(
                        f"Missing blog file: {blog['filename']}"
                    )
                    st.stop()

                  

    else:

        st.caption(
            "No pinned blogs"
        )

    # ==========================================
    # Categories
    # ==========================================

    st.markdown(
        "### 📂 Categories"
    )

    categories = get_categories()

    for category in categories:

        with st.expander(
            category["name"]
        ):

            cat_blogs = get_blogs_by_category(
                category["id"]
            )

            for blog in cat_blogs:

                if st.button(
                    f"📄 {blog['display_title']}",
                    key=f"cat_blog_{category['id']}_{blog['id']}"
                ):
                    st.session_state["selected_blog_id"] = blog["id"]
                    
                    blog_file = (
                        Path("blogs")
                        / blog["filename"]
                    )

                    if not blog_file.exists():

                        st.error(
                            f"Missing blog file: {blog['filename']}"
                        )
                        st.stop()  
                        
                      
                

                    loaded_data = enrich_loaded_blog_data(load_blog_data(blog["filename"]))
                    
                    if loaded_data is not None:
                    
                        st.session_state["last_out"] = loaded_data
                    
                    else:
                        md_text = read_md_file(blog_file)

                        st.session_state[
                            "last_out"
                        ] = {
                            "plan": None,
                            "evidence": [],
                            "image_specs": [],
                            "image_errors": [],
                            "timeline": [],
                            "seo": {},
                            "pdf_bytes": None,
                            "final": md_text,
                        }
                    
                    today = datetime.now()

                    st.session_state["analytics_filter"] = False
                    st.session_state["analytics_month"] = today.month
                    st.session_state["analytics_year"] = today.year

                        
                    st.rerun()

            st.divider()

            new_name = st.text_input(
                "Rename Category",
                value=category["name"],
                key=f"rename_cat_{category['id']}"
            )

            if st.button(
                "💾 Save",
                key=f"save_cat_{category['id']}"
            ):

                if new_name.strip():
                    success = rename_category(
                        category["id"],
                        new_name.strip()
                    )
                    if not success:
                        st.error("Category name already exists")

                    st.rerun()

            if st.button(
                "🗑 Delete Category",
                key=f"delete_cat_{category['id']}"
            ):

                delete_category(
                    category["id"]
                )
                
                today = datetime.now()

                st.session_state["analytics_filter"] = False
                st.session_state["analytics_month"] = today.month
                st.session_state["analytics_year"] = today.year

                st.rerun()

    new_category = st.text_input(
        "New Category"
    )

    if st.button(
        "➕ Create Category"
    ):

        if new_category.strip():

            success = create_category(
                new_category.strip()
            )
            if not success:
                st.error(
                    "Category already exists"
                )

            st.rerun()

    # ==========================================
    # Past Blogs
    # ==========================================

    st.markdown(
        "### 📚 Past Blogs"
    )

    for blog in blogs:

        created = blog.get(
            "created_at",
            ""
        )

        words = blog.get(
            "word_count",
            0
        )

        label = (
            f"{blog['display_title']}\n"
            f"{created} • {words} words"
        )

        col1, col2 = st.columns(
            [6, 1]
        )

        # -------------------------
        # Open Blog
        # -------------------------

        with col1:

            if st.button(
                label,
                key=f"open_{blog['id']}"
            ):
                st.session_state[
                    "selected_blog_id"
                ] = blog["id"]
                
                blog_file = (
                    Path("blogs")
                    / blog["filename"]
                )

                if blog_file.exists():
                    
                    loaded_data=enrich_loaded_blog_data(load_blog_data(blog["filename"]))
                    
                    if loaded_data is not None:
                        st.session_state["last_out"] = loaded_data
                
                    else:
                        md_text = read_md_file(blog_file)
                        st.session_state[
                            "last_out"
                        ] = {
                            "plan": None,
                            "evidence": [],
                            "image_specs": [],
                            "image_errors": [],
                            "timeline": [],
                            "seo": {},
                            "pdf_bytes": None,
                            "final": md_text,
                        }

                    st.rerun()
                else:

                    st.error(
                        f"Missing blog file: {blog['filename']}"
                    )
                    st.stop()



        # -------------------------
        # Menu
        # -------------------------

        with col2:

            with st.popover(
                "⋮"
            ):

                # -----------------
                # Pin
                # -----------------

                if blog["pinned"]:

                    if st.button(
                        "📌 Unpin",
                        key=f"unpin_{blog['id']}"
                    ):

                        set_pin_status(
                            blog["id"],
                            0
                        )

                        st.rerun()

                else:

                    if st.button(
                        "⭐ Pin",
                        key=f"pin_{blog['id']}"
                    ):

                        set_pin_status(
                            blog["id"],
                            1
                        )

                        st.rerun()

                # -----------------
                # Edit Title
                # -----------------

                new_title = st.text_input(
                    "Edit Title",
                    value=blog["display_title"],
                    key=f"title_{blog['id']}"
                )

                if st.button(
                    "💾 Save Title",
                    key=f"save_title_{blog['id']}"
                ):

                    clean_title = new_title.strip()
                    if clean_title:
                        update_display_title(
                            blog["id"],
                            clean_title
                        )
                    else:
                        st.warning(
                            "Title cannot be empty"
                        )
                    st.rerun()
                #Add Blog To Category
                
                st.divider()
                st.write("📂 Categories")
                
                all_categories = get_categories()
                 
                if all_categories:
                
                    current_categories = set(
                        get_blog_category_ids(
                        blog["id"]
                        )
                    )

                    for cat in all_categories:
                        checked = (
                            cat["id"]
                            in current_categories
                        )
                    
                        new_checked = st.checkbox(
                            cat["name"],
                            value=checked,
                            key=f"cat_{blog['id']}_{cat['id']}"
                        )
                
                        if new_checked and not checked:

                            add_blog_to_category(
                                blog["id"],
                                cat["id"]
                            )

                            st.rerun()
                    
                        elif checked and not new_checked:

                            remove_blog_from_category(
                                blog["id"],
                                cat["id"]
                            )

                            st.rerun()
                else:
                    
                    st.caption("No categories created yet.")
                
                # -----------------
                # Delete Blog
                # -----------------

                if st.button(
                    "🗑 Delete Blog",
                    key=f"delete_{blog['id']}"
                ):

                    delete_blog(
                        blog["id"]
                    )

                    st.rerun()
    

# Keep your topic input as-is; optionally prefill for next run after loading a blog
if "topic_prefill" in st.session_state and isinstance(st.session_state["topic_prefill"], str):
    # Do not mutate widgets; just keep as a hint.
    pass

# Storage for latest run
if "last_out" not in st.session_state:
    st.session_state["last_out"] = None

# Layout
tab_plan, tab_evidence, tab_preview, tab_images, tab_seo, tab_timeline, tab_details,tab_analytics, tab_logs = st.tabs(
    [
        "🧩 Plan",
        "🔎 Evidence",
        "📝 Markdown Preview",
        "🖼️ Images",
        "🎯 SEO",
        "⏱️ Timeline",
        "📄 Details",
        "📊 Analytics",
        "🧾 Logs",
    ]
)

if "logs" not in st.session_state:
    st.session_state["logs"] = []

    
# ==========================================
# Analytics State
# ==========================================

if "analytics_filter" not in st.session_state:

    st.session_state["analytics_filter"] = False

if "analytics_start_date" not in st.session_state:

    st.session_state["analytics_start_date"] = None

if "analytics_end_date" not in st.session_state:

    st.session_state["analytics_end_date"] = None

if "generation_settings_expanded" not in st.session_state:
    st.session_state["generation_settings_expanded"] = False


def log(msg: str):

    logs = st.session_state["logs"]

    logs.append(msg)

    if len(logs) > 500:
        logs.pop(0)


# ==========================================
# Default Generation Settings
# (Temporary - will later come from the UI)
# ==========================================

generation_settings = (
    st.session_state[
        "generation_settings"
    ]
)

if run_btn:
    
    st.session_state["analytics_filter"] = False
    today = datetime.now()
    st.session_state["analytics_month"] = datetime.now().month
    st.session_state["analytics_year"] = datetime.now().year
    st.session_state["logs"] = []
    if not topic.strip():
        st.warning("Please enter a topic.")
        st.stop()
        

    inputs: Dict[str, Any] = {
        "topic": topic.strip(),
        "generation_settings": generation_settings,
        "mode": generation_settings["research_mode"],
        "needs_research": False,
        "queries": [],
        "evidence": [],
        "plan": None,
        "as_of": generation_settings["as_of_date"].isoformat(),
        "recency_days": 7,
        "sections": [],
        "merged_md": "",
        "md_with_placeholders": "",
        "image_specs": [],
        "image_errors": [],
        "final": "",
        "timeline": [],
        "seo": {},
        "worker_times": [],
    }

    status = st.status("Running graph…", expanded=True)
    progress_area = st.empty()

    current_state: Dict[str, Any] = {}
    last_node = None

    for kind, payload in try_stream(blog_writer_agent, inputs):
        if kind in ("updates", "values"):
            node_name = None
            if isinstance(payload, dict) and len(payload) == 1 and isinstance(next(iter(payload.values())), dict):
                node_name = next(iter(payload.keys()))
            if node_name and node_name != last_node:
                status.write(f"➡️ Node: `{node_name}`")
                last_node = node_name

            current_state = extract_latest_state(current_state, payload)
            
            plan = current_state.get("plan")
            if hasattr(plan, "tasks"):
               task_count = len(plan.tasks)
            elif isinstance(plan, dict):
                task_count = len(plan.get("tasks", []))
            else:
                task_count = 0


            summary = {
                "mode": current_state.get("mode"),
                "needs_research": current_state.get("needs_research"),
                "queries": current_state.get("queries", [])[:5] if isinstance(current_state.get("queries"), list) else [],
                "evidence_count": len(current_state.get("evidence", []) or []),
                "tasks": task_count,
                "images": len(current_state.get("image_specs", []) or []),
                "sections_done": len(current_state.get("sections", []) or []),
            }
            progress_area.json(summary)

            log(f"[{kind}] {json.dumps(payload, default=str)[:1200]}")

        elif kind == "final":

            out = payload

            st.session_state["last_out"] = out

            # ======================================
            # Save Blog Metadata To SQLite
            # ======================================

            try:

                plan = out.get("plan")

                if hasattr(plan, "blog_title"):

                    blog_title = plan.blog_title

                elif isinstance(plan, dict):

                    blog_title = plan.get(
                        "blog_title",
                        "blog"
                    )

                else:

                    blog_title = "blog"

                filename = f"{safe_slug(blog_title)}.md"

                final_md = out.get(
                    "final",
                    ""
                )

                word_count = len(
                    final_md.split()
                )

                image_count = count_generated_images(
                    out.get(
                        "image_specs",
                        []
                    ),
                    IMAGES_DIR,
                )

                evidence_count = len(
                    out.get(
                        "evidence",
                        []
                    )
                )

                runtime = sum(
                    item.get(
                        "duration",
                        0
                    )
                    for item in out.get(
                        "timeline",
                        []
                    )
                )

                add_blog(
                    filename=filename,
                    original_title=blog_title,
                    display_title=blog_title,
                    created_at=datetime.now().isoformat(timespec="seconds"),
                    word_count=word_count,
                    image_count=image_count,
                    evidence_count=evidence_count,
                    runtime=runtime
                )
                
                log(
                    f"Saved blog metadata: {blog_title}"
                )

            except Exception as e:

                log(
                    f"DB Save Error: {e}"
                )

            status.update(
                label="✅ Done",
                state="complete",
                expanded=False
            )

            log(
                "[final] received final state"
            )
            st.toast(
                "Blog saved successfully"
            )
            st.rerun()

# Render last result (if any)
out = st.session_state.get("last_out")
if out:
    # --- Plan tab ---
    with tab_plan:
        st.subheader("Plan")
        plan_obj = out.get("plan")
        if not plan_obj:
            st.info("No plan found in output.")
        else:
            if hasattr(plan_obj, "model_dump"):
                plan_dict = plan_obj.model_dump()
            elif isinstance(plan_obj, dict):
                plan_dict = plan_obj
            else:
                plan_dict = json.loads(json.dumps(plan_obj, default=str))

            st.write("**Title:**", plan_dict.get("blog_title"))
            cols = st.columns(3)
            cols[0].write("**Audience:** " + str(plan_dict.get("audience")))
            cols[1].write("**Tone:** " + str(plan_dict.get("tone")))
            cols[2].write("**Blog kind:** " + str(plan_dict.get("blog_kind", "")))

            tasks = plan_dict.get("tasks", [])
            if tasks:
                df = pd.DataFrame(
                    [
                        {
                            "id": t.get("id"),
                            "title": t.get("title"),
                            "target_words": t.get("target_words"),
                            "requires_research": t.get("requires_research"),
                            "requires_citations": t.get("requires_citations"),
                            "requires_code": t.get("requires_code"),
                            "tags": ", ".join(t.get("tags") or []),
                        }
                        for t in tasks
                    ]
                ).sort_values("id")
                st.dataframe(df, width="stretch", hide_index=True)

                with st.expander("Task details"):
                    st.json(tasks)

   # --- Evidence tab ---

    with tab_evidence:
        st.subheader("Evidence")

        evidence = out.get("evidence") or []

        if not evidence:
            st.info("No evidence returned (maybe closed_book mode or no Tavily key/results).")

        else:
            rows = []

            for e in evidence:

                if hasattr(e, "model_dump"):
                    e = e.model_dump()

                rows.append(
                    {
                        "title": e.get("title"),
                        "published_at": e.get("published_at") or "Unknown",
                        "source": e.get("source"),
                        "url": e.get("url"),
                    }
                )

            df = pd.DataFrame(rows)

            st.dataframe(
                df,
                width="stretch",
                hide_index=True,
                column_config={
                    "title":st.column_config.TextColumn(
                        "Title",
                        width="large"
                    ),
                    "published_at": st.column_config.TextColumn(
                        "Published At",
                        width="small"
                    ),
                    "source": st.column_config.TextColumn(
                        "Source",
                        width="small"
                    ),
                    "url": st.column_config.LinkColumn(
                        "URL",
                        display_text=r"https?://(.*)"
                    ),
                },
            )

    # --- Preview tab ---
    with tab_preview:
        st.subheader("Markdown Preview")
        final_md = out.get("final") or ""
        if not final_md:
            st.warning("No final markdown found.")
        else:
            render_markdown_with_local_images(final_md)

            plan_obj = out.get("plan")
            if hasattr(plan_obj, "blog_title"):
                blog_title = plan_obj.blog_title
            elif isinstance(plan_obj, dict):
                blog_title = plan_obj.get("blog_title", "blog")
            else:
                # fallback: parse from markdown title
                blog_title = extract_title_from_md(final_md, "blog")

            md_filename = f"{safe_slug(blog_title)}.md"
            st.download_button(
                "⬇️ Download Markdown",
                data=final_md.encode("utf-8"),
                file_name=md_filename,
                mime="text/markdown",
            )

            bundle = bundle_zip_from_specs(
                final_md,
                md_filename,
                out.get(
                "image_specs",
                    []
                ),
                Path("images")
            )

            st.download_button(
                "📦 Download Bundle (MD + images)",
                data=bundle,
                file_name=f"{safe_slug(blog_title)}_bundle.zip",
                mime="application/zip",
            )
            pdf_bytes = out.get("pdf_bytes")
            if pdf_bytes:
                st.download_button(
                    "📕 Download PDF",
                    data=pdf_bytes,
                    file_name=f"{safe_slug(blog_title)}.pdf",
                    mime="application/pdf",
                )


        # --- Images tab ---
    with tab_images:
        st.subheader("Images")

        # NEW
        image_errors = out.get(
            "image_errors",
            []
        )

        if image_errors:

            st.warning(
              f"{len(image_errors)} image(s) failed to generate."
            )

            with st.expander(
                "View Image Errors"
            ):
                 for err in image_errors:
                    st.error(err)

        specs = out.get("image_specs") or []
        images_dir = IMAGES_DIR

        if not specs :
            st.info("No images generated for this blog.")
        else:
            st.write(f"Showing {len(specs)} image(s)")
        

            for spec in specs:

                filename = spec.get(
                    "filename"
                )

                if not filename:
                    continue

                img_path = (
                    images_dir /
                    filename
                )

                if img_path.exists():

                    st.image(
                        str(img_path),
                        caption=spec.get("caption",filename),
                        width="stretch"
                    )

                else:

                    st.warning(
                        f"Missing image: {filename}"
                    )

            

            z = images_zip_from_specs(specs,images_dir)

            if z:
                st.download_button(
                    "⬇️ Download Images (zip)",
                    data=z,
                    file_name="images.zip",
                    mime="application/zip",
                )
                    
    #----SEO tab---
    with tab_seo:

        st.subheader("SEO Metadata")

        seo = out.get("seo")

        if seo:           
            title = seo.get(
                "seo_title",
                ""
            )
            description = seo.get(
                "meta_description",
                ""
            )
            keywords = seo.get(
                "keywords",
                []
            )
            # ----------------------------------
            # Safe Blog Title
            # ----------------------------------
            plan_obj = out.get("plan")

            if hasattr(plan_obj, "blog_title"):
                blog_title = plan_obj.blog_title

            elif isinstance(plan_obj, dict):
                blog_title = plan_obj.get(
                    "blog_title",
                    "blog"
                )

            else:
                blog_title = "blog"


            # SEO Title
            st.markdown("### SEO Title")

            st.code(
                title,
                language=None
            )
            # Meta Description
            st.markdown("### Meta Description")           
            st.code(
                description,
                language=None
            )
            #Keywords
            st.markdown("### Keywords")

            if keywords:

                st.code(
                    ", ".join(keywords),
                    language=None
                )

            else:

                st.caption(
                    "No keywords generated."
                )


             # Download SEO Metadata
            st.download_button(
                "⬇️ Download SEO Metadata",
                data=json.dumps(
                    seo,
                    indent=2
                ),
                file_name=f"{safe_slug(blog_title)}_seo_metadata.json",
                mime="application/json",
            )

        else:

            st.info(
                "No SEO metadata."
            )
            
    #--Timeline tab
    with tab_timeline:

        st.subheader(
            "Agent Execution Timeline"
        )

        timeline = out.get(
            "timeline",
            []
        )

        if timeline:

            df = pd.DataFrame(
                timeline
            )

            df = (
         df.groupby(
                "step",
                as_index=False
            )
            .agg(
                {"duration": "sum"}
            )
        )
            
            df["step"] = df["step"].astype(str)
            df["duration"] = df["duration"].astype(float)
            st.dataframe(
                df,
                width="stretch",
                hide_index=True
            )  

            st.metric(
                "Total Time",
                f"{df['duration'].sum():.2f} sec"
            )

        else:

            st.info(
                "No timeline available."
            )

    # ----------------------------------------
    # Details Tab
    # ----------------------------------------

    with tab_details:

        st.subheader("📄 Blog Details")

            # Nothing generated or loaded yet
        if out is None:

            st.info("No blog loaded.")

            st.stop()
        plan = out.get("plan")
        seo = out.get("seo") or {}
        timeline = out.get("timeline") or []
        final_md = out.get("final") or ""

        # ----------------------------------------
        # Blog title
        # ----------------------------------------

        if hasattr(plan, "blog_title"):

            blog_title = plan.blog_title

        elif isinstance(plan, dict):

            blog_title = plan.get("blog_title")

        else:

            blog_title = None
        
        # Final fallback
        if not blog_title:

            blog_title = "blog"

        filename = f"{safe_slug(blog_title)}.md"

        db_blog = get_blog_by_filename(filename)

        if db_blog is None:

            st.warning(
            "Metadata not found.\n\n"
            "Showing information from the generated blog."
            )

            db_blog = {

                "display_title": blog_title,

                "original_title": blog_title,

                "created_at": date.today().isoformat(),

                "word_count": len(final_md.split()),

                "image_count": len(out.get("image_specs", [])),

                "evidence_count": len(out.get("evidence", [])),

                "runtime": sum(
                    t.get("duration", 0)
                    for t in timeline
                ),

                "pinned": False,

                "id": None,
            }        

        

        # ======================================
        # Header
        # ======================================

        st.markdown(f"# {db_blog['display_title']}")

        st.caption(
            f"Created on {db_blog['created_at']}"
        )

        st.divider()

        # ======================================
        # KPI Cards
        # ======================================

        c1, c2, c3, c4 = st.columns(4)

        with c1:

            st.metric(
                "📝 Words",
                f"{db_blog['word_count']:,}"
            )

        with c2:

            st.metric(
                "🖼 Images",
                db_blog["image_count"]
            )

        with c3:

            st.metric(
                "🔎 Evidence",
                db_blog["evidence_count"]
            )

        with c4:

            st.metric(
                "⏱ Runtime",
                f"{db_blog['runtime']:.2f}s"
            )

        st.divider()

        # ======================================
        # General Information
        # ======================================

        left, right = st.columns(2)

        with left:

            st.markdown("### ℹ General")

            st.write(
                f"**Display Title:** {db_blog['display_title']}"
            )

            st.write(
                f"**Original Title:** {db_blog['original_title']}"
            )

            st.write(
                f"**Created:** {db_blog['created_at']}"
            )

            st.write(
                f"**Pinned:** {'✅ Yes' if db_blog['pinned'] else '❌ No'}"
            )

        with right:

            st.markdown("### 🏷 Categories")

            if db_blog["id"] is not None:   
                cats = get_blog_categories(
                    db_blog["id"]
                )
            else:
                cats=[]
                

            if cats:

                cols = st.columns(
                    min(3, len(cats))
                )

                for i, cat in enumerate(cats):

                    cols[i % len(cols)].success(
                        cat["name"]
                    )

            else:

                st.info(
                    "No categories assigned"
                )

        st.divider()

        # ======================================
        # File Information
        # ======================================

        st.markdown("### 📂 Files")

        f1, f2 = st.columns(2)

        with f1:

            st.info(
                f"📄 Markdown\n\nblogs/{filename}"
            )

        with f2:

            st.info(
                f"📦 Metadata\n\nblog_data/{filename.replace('.md','.json')}"
            )

        st.divider()

        # ======================================
        # Statistics
        # ======================================

        st.markdown("### 📊 Statistics")

        reading_time = max(
            1,
            round(
                len(final_md.split()) / 200
            )
        )

        if hasattr(plan, "tasks"):
            section_count = len(plan.tasks)
        elif isinstance(plan, dict):
            section_count = len(plan.get("tasks", []))
        else:
            section_count = 0


        stats = pd.DataFrame(
            [
                ["Word Count",  str(db_blog["word_count"])],
                ["Reading Time", f"{reading_time} min"],
                ["Sections", str(section_count)],
                ["Images", str(db_blog["image_count"])],
                ["Evidence", str(db_blog["evidence_count"])],
                ["SEO Keywords", str(len(seo.get("keywords", [])))],
                ["Timeline Steps", str(len(timeline))],
                ["Runtime", f"{db_blog['runtime']:.2f} sec"],
            ],
            columns=[
                "Metric",
                "Value",
            ],
        )
        
            
            
        st.dataframe(
            stats,
            hide_index=True,
            width="stretch",
        )

        st.divider()

        # ======================================
        # Content Summary
        # ======================================
        st.markdown("### 📖 Content Summary")

        words = final_md.split()

        preview = " ".join(words[:120])

        if len(words) > 120:
            preview += "..."

        st.info(preview)

        st.divider()

        # ======================================
        # Document Health
        # ======================================

        st.markdown("### ✅ Document Health")

        health = []

        # Word Count

        if db_blog["word_count"] >= 1500:

            health.append("✅ Excellent article length")

        elif db_blog["word_count"] >= 800:

            health.append("✅ Good article length")

        else:

            health.append("⚠ Short article")

        # Evidence

        if db_blog["evidence_count"] > 0:

            health.append("✅ Research evidence available")

        else:

            health.append("⚠ No supporting evidence")

        # Images

        if db_blog["image_count"] > 0:

            health.append("✅ Contains generated images")

        else:

            health.append("⚠ No images")

        # SEO

        keyword_count = len(
            seo.get(
                "keywords",
                []
            )
        )

        if keyword_count >= 8:

            health.append("✅ Strong SEO optimization")

        elif keyword_count >= 4:

            health.append("✅ Moderate SEO optimization")

        else:

            health.append("⚠ Few SEO keywords")

        # Reading Time

        if reading_time <= 5:

            health.append("📖 Quick read")

        elif reading_time <= 10:

            health.append("📖 Medium length read")

        else:

            health.append("📖 Long-form article")

        for item in health:

            st.write(item)

        st.divider()

        # ======================================
        # Generation Summary
        # ======================================

        st.markdown("### 📋 Generation Summary")

        summary = pd.DataFrame(
            [
                ["Display Title", str(db_blog["display_title"])],
                ["Original Title", str(db_blog["original_title"])],
                ["Pinned", "Yes" if db_blog["pinned"] else "No"],
                ["Categories", str(len(cats))],
                ["Markdown File", str(filename)],
                ["Metadata File", str(filename.replace(".md", ".json"))],
            ],
            columns=[
                "Property",
                "Value",
            ],
        )
            
        summary = summary.astype(str)

        st.dataframe(
            summary,
            hide_index=True,
            width="stretch",
        )
        
        st.divider()

        # ======================================
        # Generation Settings
        # ======================================

        st.markdown("### ⚙️ Generation Settings")

        settings = out.get(
            "generation_settings",
            {}
        )

        if settings:

            settings_df = pd.DataFrame(
                [
                    [
                        "Research Mode",
                        str(settings.get("research_mode", "Auto"))
                    ],
                    [
                        "As-of Date",
                        str(settings.get("as_of_date", "-"))
                    ],
                    [
                        "Search Queries",
                        f"{settings.get('min_queries', 2)} → "
                        f"{settings.get('max_queries', 3)}"
                    ],
                    [
                        "Results / Query",
                        f"{settings.get('min_results', 2)} → "
                        f"{settings.get('max_results', 3)}"
                    ],
                    [
                        "Sections",
                        f"{settings.get('min_sections', 2)} → "
                        f"{settings.get('max_sections', 3)}"
                    ],
                    [
                        "Bullets / Section",
                        f"{settings.get('min_bullets', 2)} → "
                        f"{settings.get('max_bullets', 3)}"
                    ],
                    [
                        "Target Words",
                        f"{settings.get('min_words', 50)} → "
                        f"{settings.get('max_words', 100)}"
                    ],
                    [
                        "Images",
                        f"{settings.get('min_images', 1)} → "
                        f"{settings.get('max_images', 1)}"
                    ],
                ],
                columns=[
                    "Setting",
                    "Value",
                ],
            )

            settings_df = settings_df.astype(str)

            st.dataframe(
                settings_df,
                hide_index=True,
                width="stretch",
            )

        else:

            st.info(
                "Generation settings are not available for this blog."
            )       
                               
    # --- Logs tab ---
    with tab_logs:

        st.subheader("Logs")

        st.text_area(
            "Event log",
            value="\n\n".join(
                st.session_state["logs"][-200:]
            ),
            height=520
        )

        if st.button(
            "🗑 Clear Logs"
        ):
            st.session_state["logs"] = []
            st.rerun()
else:

    with tab_plan:
        st.info("Enter a topic and click Generate Blog.")

    with tab_evidence:
        st.info("No blog loaded.")

    with tab_preview:
        st.info("No blog loaded.")

    with tab_images:
        st.info("No blog loaded.")

    with tab_seo:
        st.info("No blog loaded.")

    with tab_timeline:
        st.info("No blog loaded.")

    with tab_details:
        st.info("No blog loaded.")

    with tab_logs:
        st.info("No logs available.")



# ----------------------------------------
# Analytics Tab
# ----------------------------------------

with tab_analytics:

    st.subheader("📊 Analytics Dashboard")
    # =====================================
    # Overall Analytics
    # =====================================

    stats = get_blog_statistics()

    df = get_all_blog_dataframe()
        
    st.markdown("## 🌍 Overall Analytics")

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.metric(
            "📝 Blogs",
            stats["total_blogs"]
        )

    with c2:
        st.metric(
            "📖 Words",
            f"{stats['total_words']:,}"
        )

    with c3:
        st.metric(
            "🖼 Images",
            stats["total_images"]
        )

    with c4:
        st.metric(
            "📚 Evidence",
            stats["total_evidence"]
        )

    st.divider()

    c1, c2, c3 = st.columns(3)

    with c1:
        st.metric(
            "⭐ Pinned",
            stats["pinned"]
        )

    with c2:
        st.metric(
            "⏱ Avg Runtime",
            f"{stats['avg_runtime']:.2f} sec"
        )

    with c3:

        if stats["total_words"]:

            reading = round(
                stats["total_words"] / 200
            )

        else:

            reading = 0

        st.metric(
            "📄 Reading Time",
            f"{reading} min"
        )

    st.divider()
        
    # =====================================
    # Current Activity
    # =====================================

    st.markdown("## 📅 Current Activity")

    t1, t2, t3 = st.columns(3)

    with t1:

        st.metric(
            "📅 Blogs Today",
            get_today_blog_count()
        )

    with t2:

        st.metric(
            "📅 This Week",
            get_week_blog_count()
        )

    with t3:

        st.metric(
            "📅 This Month",
            get_month_blog_count()
        )

    st.divider()
    # =====================================
    # Date Range Analytics
    # =====================================

    st.markdown("## 📅 Date Range Analytics")

    available = get_available_blog_dates()

    today = date.today()

    if (
        st.session_state["analytics_start_date"] is None
        or
        st.session_state["analytics_end_date"] is None
    ):

        st.info(
            "Showing overall analytics.\n\n"
            "Select a date range then click "
            "'Fetch Data' to filter analytics."
        )

    first_blog = (
        date.fromisoformat(available["first_blog"])
        if available["first_blog"]
        else today
    )

    last_blog = (
        date.fromisoformat(available["last_blog"])
        if available["last_blog"]
        else today
    )

    c1, c2 = st.columns(2)

    with c1:

        start_date = st.date_input(
            "From",
            value=st.session_state["analytics_start_date"]
            or first_blog,
            min_value=first_blog,
            max_value=today,
        )

    with c2:

        end_date = st.date_input(
            "To",
            value=st.session_state["analytics_end_date"]
            or last_blog,
            min_value=first_blog,
            max_value=today,
        )

    b1, b2 = st.columns(2)

    with b1:

        fetch = st.button(
            "🔍 Fetch Data",
            width="stretch"
        )

    with b2:

        reset = st.button(
            "↺ Reset",
            width="stretch"
        )

    if fetch:

        if start_date > end_date:

            st.error(
                "Start date must be before End date."
            )

        else:

            st.session_state["analytics_filter"] = True
            st.session_state["analytics_start_date"] = start_date
            st.session_state["analytics_end_date"] = end_date

            st.rerun()

    if reset:

        st.session_state["analytics_filter"] = False
        st.session_state["analytics_start_date"] = None
        st.session_state["analytics_end_date"] = None

        st.rerun()

    if st.session_state["analytics_filter"]:

        date_stats = get_date_statistics(
            st.session_state["analytics_start_date"],
            st.session_state["analytics_end_date"],
        )

    else:

        date_stats = stats

    m1, m2, m3, m4 = st.columns(4)

    with m1:

        st.metric(
            "📝 Blogs",
            date_stats["total_blogs"],
        )

    with m2:

        st.metric(
            "📖 Words",
            f"{date_stats['total_words']:,}",
        )

    with m3:

        st.metric(
            "🖼 Images",
            date_stats["total_images"],
        )

    with m4:

        st.metric(
            "📚 Evidence",
            date_stats["total_evidence"],
        )

    st.divider()
           
    st.markdown("## 📈 Blog Growth")
          
    if st.session_state.get("analytics_filter", False):
        growth = get_date_blog_growth(
        st.session_state["analytics_start_date"],
        st.session_state["analytics_end_date"],
        )
            
        growth_title = (
            f"{st.session_state['analytics_start_date']} "
            f"→ "
            f"{st.session_state['analytics_end_date']}"
        )
    else:
            

        growth = get_blog_growth()
        growth_title = "Blogs Created Over Time"


    if not growth.empty:

        fig = px.line(
            growth,
            x="day",
            y="blogs",
            markers=True,
            title=growth_title,
        )

        st.plotly_chart(
            fig,
            width="stretch",
        )

    else:

        st.info("Not enough data.")

    st.markdown("## 📊 Word Count Distribution")
        
    if st.session_state.get("analytics_filter", False):

        df = get_date_blog_dataframe(
            st.session_state["analytics_start_date"],
            st.session_state["analytics_end_date"],
        )

    else:

        df = get_all_blog_dataframe()
        

    if not df.empty:

        fig = px.histogram(
            df,
            x="word_count",
            nbins=10,
            title="Distribution of Blog Word Counts",
        )

        st.plotly_chart(
            fig,
            width="stretch",
        )

    else:

        st.info("No data.")
    
    st.markdown("## 🏷 Top Categories")
        
    if st.session_state.get("analytics_filter", False):

        cat_df = get_date_category_statistics(
            st.session_state["analytics_start_date"],
            st.session_state["analytics_end_date"],
        )

    else:

        cat_df = get_category_statistics()

    if not cat_df.empty:

        fig = px.pie(
            cat_df,
            values="total",
            names="name",
            title=(
                "Blogs by Category"
                if not st.session_state.get("analytics_filter", False)
                else
                f"Category Distribution \n "
                f"{st.session_state['analytics_start_date']} → "
                f"{st.session_state['analytics_end_date']} "
            ),
        )

        st.plotly_chart(
            fig,
            width="stretch",
        )

    else:

        st.info("No categories available.")

    # =====================================
    # Blog Database
    # =====================================

    st.markdown("## 📋 Blog Database")

    if st.session_state.get("analytics_filter", False):


        st.success(
            f"Showing blogs from "
            f"{st.session_state['analytics_start_date']}"
            " → "
            f"{st.session_state['analytics_end_date']}"
        )

        table_df = get_date_blog_dataframe(
            st.session_state["analytics_start_date"],
            st.session_state["analytics_end_date"]
        )

    else:

        st.info(
            "Showing all blogs."
        )

        table_df = get_all_blog_dataframe()

    if table_df.empty:

        st.warning(
            "No blogs found."
        )

    else:

        show = table_df[
            [
                "display_title",
                "created_at",
                "word_count",
                "image_count",
                "evidence_count",
                "runtime",
            ]
        ]

        st.dataframe(
            show,
            hide_index=True,
            width="stretch"
        )