from __future__ import annotations

import operator
import os
import re
from datetime import date, timedelta
import time
from pathlib import Path
from typing import TypedDict, List, Optional, Literal, Annotated

from pydantic import BaseModel, Field

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

from urllib.parse import urlparse

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from dotenv import load_dotenv
from dataclasses import asdict
from io import BytesIO
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Image,
)
from reportlab.lib.styles import getSampleStyleSheet
import logging
from database import *
import json

init_db()
load_dotenv()


# ============================================================
# Blog Writer (Router → (Research?) → Orchestrator → Workers → ReducerWithImages)
# Patches image capability using your 3-node reducer flow:
#   merge_content -> decide_images -> generate_and_place_images
# ============================================================

# =====================================================
# LOGGER SETUP
# =====================================================


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)

logger.info(f"TAVILY_API_KEY Loaded: {bool(...)}")

# -------------------------------------------------
# Directories
# -------------------------------------------------

BLOGS_DIR = Path("blogs")
BLOGS_DIR.mkdir(exist_ok=True)

IMAGES_DIR = Path("images")
IMAGES_DIR.mkdir(exist_ok=True)

BLOG_DATA_DIR = Path("blog_data")
BLOG_DATA_DIR.mkdir(exist_ok=True)

# -----------------------------
# 1) Schemas
# -----------------------------
class Task(BaseModel):
    id: int
    title: str
    goal: str = Field(..., description="One sentence describing what the reader should do/understand.")
    bullets: List[str] = Field(..., min_length=1, max_length=20)
    target_words: int = Field(..., ge=20,le=5000,)

    tags: List[str] = Field(default_factory=list)
    requires_research: bool = False
    requires_citations: bool = False
    requires_code: bool = False


class Plan(BaseModel):
    blog_title: str
    audience: str
    tone: str
    blog_kind: Literal["explainer", "tutorial", "news_roundup", "comparison", "system_design"] = "explainer"
    constraints: List[str] = Field(default_factory=list)
    tasks: List[Task] = Field(min_length=1,max_length=20,)


class EvidenceItem(BaseModel):
    title: str
    url: str
    published_at: Optional[str] = None  # ISO "YYYY-MM-DD" preferred
    snippet: Optional[str] = None
    source: Optional[str] = None


class RouterDecision(BaseModel):
    needs_research: bool
    mode: Literal["closed_book", "hybrid", "open_book"]
    reason: str
    queries: List[str] = Field(default_factory=list)
    max_results_per_query: int = Field(5)


class EvidencePack(BaseModel):
    evidence: List[EvidenceItem] = Field(default_factory=list)


# ---- Image planning schema (ported from your image flow) ----
class ImageSpec(BaseModel):
    placeholder: str = Field(..., description="e.g. [[IMAGE_1]]")
    filename: str = Field(..., description="Save under images/, e.g. qkv_flow.png")
    alt: str
    caption: str
    prompt: str = Field(..., description="Prompt to send to the image model.")
    size: Literal["1024x1024", "1024x1536", "1536x1024"] = "1024x1024"
    quality: Literal["low", "medium", "high"] = "medium"


class GlobalImagePlan(BaseModel):
    md_with_placeholders: str
    images: List[ImageSpec] = Field(default_factory=list)

class State(TypedDict):
    topic: str
    generation_settings: dict
    
    # routing / research
    mode: str
    needs_research: bool
    queries: List[str]
    evidence: List[EvidenceItem]
    plan: Optional[Plan]

    # recency
    as_of: str
    recency_days: int

    # workers
    sections: Annotated[List[tuple[int, str]], operator.add]  # (task_id, section_md)

    # reducer/image
    merged_md: str
    md_with_placeholders: str
    image_specs: List[dict]
    image_errors: List[str]
    pdf_bytes: bytes
    final: str
    
    seo: dict
    timeline: List[dict]
    worker_times: Annotated[List[float], operator.add]

class SEOData(BaseModel):
    seo_title: str
    meta_description: str
    keywords: List[str]

# -----------------------------
# 2) LLM
# -----------------------------
llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0
)

from generation_settings import GenerationSettings

DEFAULT_SETTINGS = asdict(GenerationSettings())


def get_settings(state: State) -> dict:
    """
    Returns user settings merged with defaults.
    """

    settings = state.get("generation_settings")

    if not settings:
        return DEFAULT_SETTINGS.copy()

    merged = DEFAULT_SETTINGS.copy()
    merged.update(settings)

    return merged

# -----------------------------
# 3) Router
# -----------------------------
ROUTER_SYSTEM = """You are a routing module for a technical blog planner.

Decide whether web research is needed BEFORE planning.

Modes:

- closed_book
  Evergreen concepts.
  No web research required.

- hybrid
  Evergreen concepts with current examples, tools or models.

- open_book
  News, latest releases, pricing, APIs, policies, benchmarks and rapidly changing information.

Generation Settings

- Produce between {min_queries} and {max_queries} search queries.
- Do not exceed the maximum.
- Produce only high-quality search queries.

If needs_research=true:

- For open_book, queries should target information available before the supplied As-of Date.
- Prefer recent information unless the As-of Date indicates otherwise.

Return only the RouterDecision schema.
"""

#The queries are intended as a baseline and can be customized further based on your specific requirements

def router_node(state: State) -> dict:
    start = time.time()
    settings = get_settings(state)
    decider = llm.with_structured_output(RouterDecision)
    settings = get_settings(state)
    router_prompt = ROUTER_SYSTEM.format(
        min_queries=settings["min_queries"],
        max_queries=settings["max_queries"],
    )
    
    settings = get_settings(state)

    mode = settings["research_mode"]

    if mode == "local":
        return {
            "mode": "closed_book",
            "needs_research": False,
            "queries": [],
            "recency_days": 3650,
            "timeline":[{"step":"Router","duration":0}]
        }

    if mode == "hybrid":
        return {
            "mode":"hybrid",
            "needs_research":True,
            "queries":[state["topic"]],
            "recency_days":45,
            "timeline":[{"step":"Router","duration":0}]
        }

    if mode == "web":
        return {
            "mode":"open_book",
            "needs_research":True,
            "queries":[state["topic"]],
            "recency_days":7,
            "timeline":[{"step":"Router","duration":0}]
        }


    
    
    decision = decider.invoke(
        [
            SystemMessage(content=router_prompt),
            HumanMessage(content=(
                f"Topic: {state['topic']}\n"
                f"As-of date: {state['as_of']}\n"
                f"Generate between "
                f"{settings['min_queries']} and "
                f"{settings['max_queries']} "
                f"search queries."
                )
            
            ),
        ]
    )
    decision.queries = decision.queries[:settings["max_queries"]]
    
    # Ensure minimum number of queries
    if (
        decision.needs_research
        and len(decision.queries) < settings["min_queries"]
    ):

        while len(decision.queries) < settings["min_queries"]:
            decision.queries.append(state["topic"])
            
            
    if decision.mode == "open_book":
        recency_days = 7
    elif decision.mode == "hybrid":
        recency_days = 45
    else:
        recency_days = 3650
        
    duration = round(
        time.time() - start,
        2
    )
    logger.info(
        f"Router: mode={decision.mode}, "
        f"research={decision.needs_research}"
    )


    return {
        "needs_research": decision.needs_research,
        "mode": decision.mode,
        "queries": decision.queries,
        "recency_days": recency_days,
        "timeline": [
            {
                "step": "Router",
                "duration": duration
            }
        ]
    }

def route_next(state: State) -> str:
    return "research" if state["needs_research"] else "orchestrator"

# -----------------------------
# 4) Research (Tavily)
# -----------------------------
def _tavily_search(query: str, max_results: int = 3) -> List[dict]:
    # The queries are intended as a baseline and can be customized further based on your specific requirements
    api_key = os.getenv("TAVILY_API_KEY")

    if not api_key:
        raise RuntimeError(
            "TAVILY_API_KEY is missing. Check your .env file."
        )

    try:
        from langchain_tavily import TavilySearch

        tool = TavilySearch(max_results=max_results)

        response = tool.invoke(query)


        results = response.get("results", [])

        out: List[dict] = []

        for r in results:
            url = r.get("url", "")
            domain = urlparse(url).netloc
            domain = domain.replace("www.", "")

            out.append(
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": (r.get("content") or "")[:500],
                    "published_at": (
                        r.get("published_date")
                        or r.get("published_at")
                        or None
                    ),
                    "source": domain,
                }
            )


        return out

    except Exception as e:

        logger.error(f"Tavily Error: {e}")

        return []

def _iso_to_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except Exception:
        return None

RESEARCH_SYSTEM = """
You are a research synthesizer.

Convert Tavily search results into EvidenceItem objects.

Generation Settings

- Results per query:
  {min_results} to {max_results}

Rules

- Return all useful evidence.
- Never invent information.
- Never hallucinate URLs.
- Deduplicate URLs.
- Preserve title.
- Preserve url.
- Preserve snippet (max 200 chars).
- published_at=null if unavailable.

Return only EvidencePack.
"""

def research_node(state: State) -> dict:
    """
    Research Node

    1. Executes Tavily searches
    2. Extracts evidence using structured output
    3. Deduplicates URLs
    4. Applies open-book date filtering
    5. Returns evidence to planner/workers
    """
    start = time.time()
    settings = get_settings(state)

    queries = (state.get("queries") or [])[: settings["max_queries"]]

    raw: List[dict] = []

    # ----------------------------------
    # Tavily Search
    # ----------------------------------
    for q in queries:
        #The queries are intended as a baseline and can be customized further based on your specific requirements
        results = _tavily_search(
            q,
            max_results=settings["max_results"]
        )



        raw.extend(results)


    if not raw:
        logger.warning("No search results found")
        logger.info(f"TAVILY_API_KEY exists: {bool(os.getenv('TAVILY_API_KEY'))}")

        logger.info(f"Queries: {queries}")

        logger.info(f"Raw Tavily Results: {len(raw)}")
        return {"evidence": []}

    # ----------------------------------
    # Evidence Extraction
    # ----------------------------------
    extractor = llm.with_structured_output(
        EvidencePack
    )

    try:
        settings = get_settings(state)
        research_prompt = RESEARCH_SYSTEM.format(
            min_results=settings["min_results"],
            max_results=settings["max_results"],
        )

        pack = extractor.invoke(
            [
                SystemMessage(
                    content=research_prompt
                ),
                HumanMessage(
                    content=f"""
                    As-of date: {state['as_of']}

                    Raw Search Results:

                    {raw}
                    """
                ),
            ]
        )



        # ----------------------------------
        # Deduplicate URLs
        # ----------------------------------
        dedup = {}

        for e in pack.evidence:

            if e.url:
                dedup[e.url] = e

        evidence = list(
            dedup.values()
        )

    except Exception as ex:

        logger.error(f"Evidence Extraction Error: {ex}")

        evidence = []

    # ----------------------------------
    # Open Book Filtering
    # ----------------------------------
    if (
        state.get("mode") == "open_book"
        and evidence
    ):

        as_of_value = state["as_of"]

        if isinstance(as_of_value, date):
            as_of = as_of_value
        else:
            as_of = date.fromisoformat(str(as_of_value))

        cutoff = as_of - timedelta(
            days=int(
                state["recency_days"]
            )
        )

        filtered = []

        for e in evidence:

            # Keep evidence if date missing
            if not e.published_at:

                filtered.append(e)

                continue

            d = _iso_to_date(
                e.published_at
            )

            if d and d >= cutoff:

                filtered.append(e)

        evidence = filtered


    duration = round(
        time.time() - start,
        2
    )

    timeline = list(
        state.get(
            "timeline",
            []
        )
    )

    timeline.append(
        {
            "step": "Research",
            "duration": duration
        }
    )
    
    logger.info(
        f"Research completed: "
        f"{len(evidence)} evidence items"
    )
    
    # Respect Results Per Query setting
    evidence = evidence[: settings["max_results"]]
    
    # Respect Results Per Query


    # Ensure minimum evidence if available
    if len(evidence) < settings["min_results"]:

        logger.warning(
            f"Only {len(evidence)} evidence items found "
            f"(minimum requested: {settings['min_results']})."
        )
    
    return {
        "evidence": evidence,
        "timeline": timeline
    }

# -----------------------------
# 5) Orchestrator (Plan)
# -----------------------------

#The tasks, number of bullet points, and target word count are configurable and can be adjusted to suit your requirements.

ORCH_SYSTEM = """You are a senior technical writer and developer advocate.

Produce a highly actionable outline.

Generation Settings

- Create between {min_sections} and {max_sections} sections.

- Each section should contain between
  {min_bullets}
  and
  {max_bullets}
  bullet points.

- Each section should target
  {min_words}
  to
  {max_words}
  words.

General Rules

- Tags are flexible.

Grounding

closed_book

- Evergreen only.

hybrid

- Use evidence for current examples.
- Mark requires_research=True.
- Mark requires_citations=True.

open_book

- blog_kind="news_roundup"
- Never invent events.
- Reflect weak evidence honestly.

Return only Plan schema.
"""

def orchestrator_node(state: State) -> dict:
    start = time.time()
    settings = get_settings(state)
    planner = llm.with_structured_output(Plan)
    mode = state.get("mode", "closed_book")
    evidence = state.get("evidence", [])

    forced_kind = "news_roundup" if mode == "open_book" else None
    settings = get_settings(state)
    orch_prompt = ORCH_SYSTEM.format(

        min_sections=settings["min_sections"],
        max_sections=settings["max_sections"],

        min_bullets=settings["min_bullets"],
        max_bullets=settings["max_bullets"],

        min_words=settings["min_words"],
        max_words=settings["max_words"],
    )
    plan = planner.invoke(
        [
            SystemMessage(content=orch_prompt),
            HumanMessage(
                content=(
                    f"Topic: {state['topic']}\n"
                    f"Mode: {mode}\n"
                    f"As-of: {state['as_of']} (recency_days={state['recency_days']})\n"
                    f"{'Force blog_kind=news_roundup' if forced_kind else ''}\n\n"
                    f"Evidence:\n{[e.model_dump() for e in evidence][:4]}"
                )
            ),
        ]
    )
    
    plan.tasks = plan.tasks[:settings["max_sections"]]

    for task in plan.tasks:
        task.bullets = task.bullets[:settings["max_bullets"]]
        
        # Ensure minimum bullets
        while (
            len(task.bullets)
            < settings["min_bullets"]
        ):

            task.bullets.append(
                "Additional point"
            )

        task.target_words = max(
            settings["min_words"],
            min(
                task.target_words,
                settings["max_words"]
            )
        )
    
    if forced_kind:
        plan.blog_kind = "news_roundup"
    
    duration = round(
        time.time() - start,
        2
    )

    timeline = list(
        state.get(
            "timeline",
            []
        )
    )
    
    timeline.append(
        {
            "step": "Planner",
            "duration": duration
        }
    )
    
    logger.info(
        f"Planner created "
        f"{len(plan.tasks)} tasks"
    )

    return {"plan": plan,
            "timeline": timeline
    }


# -----------------------------
# 6) Fanout
# -----------------------------
def fanout(state: State):
    assert state["plan"] is not None

    plan_dict = state["plan"].model_dump()

    # Convert evidence once instead of once per worker
    evidence_list = [
        e.model_dump()
        for e in state.get("evidence", [])
    ]
    settings = get_settings(state)
    return [
        Send(
            "worker",
            {
                "task": task.model_dump(),
                "generation_settings": settings,
                "topic": state["topic"],
                "mode": state["mode"],
                "as_of": state["as_of"],
                "recency_days": state["recency_days"],
                "plan": plan_dict,
                "evidence": evidence_list,
            },
        )
        for task in state["plan"].tasks
    ]

# -----------------------------
# 7) Worker
# -----------------------------
WORKER_SYSTEM = """
You are an expert journalist and blog writer.

Write a professional Markdown blog section using ONLY the supplied evidence.

WRITING:
- Write naturally and professionally.
- Use complete paragraphs.
- Be informative and engaging.
- Maintain logical flow.
- Avoid repetition and generic statements.
- Use headings when appropriate.
- Avoid bullet points unless necessary.

EVIDENCE:
- Use only provided evidence.
- Extract actual facts.
- Mention organizations, teams, products, people, events, and dates when available.
- Combine information from multiple sources into a coherent narrative.
- Do not invent facts, dates, statistics, or claims.

CITATIONS:
- Cite sources naturally using markdown links.

GOOD:
According to [FIFA](https://www.fifa.com/...),
Belgium and Senegal secured qualification.

GOOD:
Recent reporting from
[Yahoo Sports](https://sports.yahoo.com/...)
highlighted important match results.

BAD:
(Source)

BAD:
[Source](url)

BAD:
Visit the website.

BAD:
Check the source.

Never tell readers to visit a website.

BLOG QUALITY:
- If evidence exists, summarize and explain it.
- Never write:
  - Not found in provided sources
  - No evidence available
  - Check the official website
  - Visit the source

- Expand on evidence with meaningful explanation.
- Connect related evidence together.
- Write like a real publication.

OUTPUT:
- Output only the section.
- No notes.
- No explanations.
- No AI references.
- No reasoning.
- Use markdown links instead of raw URLs.
"""
def worker_node(payload: dict) -> dict:

    start = time.time()
    task = Task(**payload["task"])

    plan = Plan(**payload["plan"])

    evidence = [
        EvidenceItem(**e)
        for e in payload.get("evidence", [])
    ]

    bullets_text = "\n- " + "\n- ".join(
        task.bullets
    )
    settings = payload["generation_settings"]
    # ----------------------------------
    # Rich Evidence Context
    # ----------------------------------
    evidence_text = "\n\n".join(
        [
            f"""
            Title: {e.title}
            Source: {e.source}
            URL:{e.url}
            Published: {e.published_at or None}
            Snippet:{e.snippet}
            
            """
            for e in evidence
        ]
    )

    section_md = llm.invoke(
        [
            SystemMessage(content=WORKER_SYSTEM),
            HumanMessage(
                content=f"""
                Blog Title:{plan.blog_title}

                Audience:{plan.audience}

                Tone:{plan.tone}

                Blog Type: {plan.blog_kind}

                Constraints:{plan.constraints}

                Topic:{payload['topic']}

                Mode:{payload.get('mode')}

                As Of:{payload.get('as_of')}

                Recency Days: {payload.get('recency_days')}

                ------------------------------------------------

                Section Title:  {task.title}

                Goal:  {task.goal}

                Target Words: {task.target_words}
                Maximum Allowed Words: {settings["max_words"]}

                Tags: {task.tags}

                Requires Research: {task.requires_research}

                Requires Citations:  {task.requires_citations}

                Requires Code: {task.requires_code}

                Key Points: {bullets_text}

                ------------------------------------------------

                Evidence:{evidence_text}

                ------------------------------------------------

                Write a detailed blog section.

                Requirements:

                - Use the evidence.
                - Mention actual facts from the evidence.
                - Mention teams, companies, organizations, products, people, dates, events when available.
                - Never tell the reader to visit a website.
                - Never say "check the source".
                - Never say "not found in provided sources".
                - Never say "visit the official website".
                - Write naturally like a professional article.
                - Use multiple paragraphs.
                - Use only provided evidence.
                 """
            ),
        ]
    ).content.strip()
    
    logger.info(
        f"Worker completed: {task.title}"
    )
       
    duration = round(
        time.time() - start,
        2
    )

    
    
    return {
        "sections": [(task.id,section_md )],
        "worker_times": [duration]
    }
    
# ============================================================
# 8) ReducerWithImages (subgraph)
#    merge_content -> decide_images -> generate_and_place_images
# ============================================================
def merge_content(state: State) -> dict:

    plan = state["plan"]

    if plan is None:
        raise ValueError(
            "merge_content called without plan."
        )

    # ----------------------------------
    # Timeline
    # ----------------------------------
    timeline = list(
        state.get(
            "timeline",
            []
        )
    )

    worker_times = state.get(
        "worker_times",
        []
    )

    if worker_times:

        timeline.append(
            {
                "step": "Workers",
                "duration": round(
                    sum(worker_times),
                    2
                )
            }
        )

    # ----------------------------------
    # Merge Sections
    # ----------------------------------
    ordered_sections = [
        md
        for _, md in sorted(
            state["sections"],
            key=lambda x: x[0]
        )
    ]

    body = "\n\n".join(
        ordered_sections
    ).strip()

    # ----------------------------------
    # Table of Contents
    # ----------------------------------
    toc = "## Table of Contents\n\n"

    for i, task in enumerate(
        plan.tasks,
        start=1
    ):
        toc += (
            f"{i}. {task.title}\n"
        )

    # ----------------------------------
    # References
    # ----------------------------------
    references = ""

    evidence = state.get(
        "evidence",
        []
    )

    if evidence:

        references = (
            "\n\n## References\n\n"
        )

        seen = set()

        for e in evidence:

            if e.url and e.url not in seen:

                references += (
                    f"- [{e.title}]({e.url})\n"
                )

                seen.add(
                    e.url
                )

    # ----------------------------------
    # Final Markdown
    # ----------------------------------
    merged_md = (
        f"# {plan.blog_title}\n\n"
        f"{toc}\n\n"
        f"{body}\n"
        f"{references}"
    )

    logger.info(
        f"Merged {len(ordered_sections)} sections"
    )
    
    return {
        "merged_md": merged_md,
        "timeline": timeline
    }

DECIDE_IMAGES_SYSTEM = """You are an expert technical editor.

Generation Settings

Generate between
{min_images}
and
{max_images}
images.

Rules

- Only generate images that improve understanding.
- Prefer architecture diagrams, workflows, tables and technical illustrations.
- Never generate decorative images.
- Placeholders must be

[[IMAGE_1]]

[[IMAGE_2]]

[[IMAGE_3]]

If no images are needed,

images=[]

and

md_with_placeholders=input.

Return only GlobalImagePlan.
"""
# The number of images are configurable and can be adjusted to suit your requirements.

def decide_images(state: State) -> dict:
    planner = llm.with_structured_output(GlobalImagePlan)
    settings = get_settings(state)
    merged_md = state["merged_md"]
    plan = state["plan"]
    assert plan is not None
    settings = get_settings(state)
    image_prompt = DECIDE_IMAGES_SYSTEM.format(

        min_images=settings["min_images"],
        max_images=settings["max_images"],
    )
    image_plan = planner.invoke(
        [
            SystemMessage(content=image_prompt),
            HumanMessage(
                content=(
                    f"Blog kind: {plan.blog_kind}\n"
                    f"Topic: {state['topic']}\n\n"
                    "Insert placeholders + propose image prompts.\n\n"
                    f"{merged_md}"
                )
            ),
        ]
    )

    image_plan.images = image_plan.images[:settings["max_images"]]
    
    # Remove extra placeholders if images were trimmed
    allowed = len(image_plan.images)

    for i in range(
        allowed + 1,
        20,
    ):

        image_plan.md_with_placeholders = (
            image_plan.md_with_placeholders.replace(
                f"[[IMAGE_{i}]]",
                "",
            )
        )
    
    return {
        "md_with_placeholders": image_plan.md_with_placeholders,
        "image_specs": [img.model_dump() for img in image_plan.images],
    }


def _gemini_generate_image_bytes(prompt: str) -> bytes:
    """
    Returns raw image bytes generated by Gemini.
    Requires: pip install google-genai
    Env var: GOOGLE_API_KEY
    """
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY is not set.")

    client = genai.Client(api_key=api_key)

    resp = client.models.generate_content(
        model="gemini-2.5-flash-image",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            safety_settings=[
                types.SafetySetting(
                    category="HARM_CATEGORY_DANGEROUS_CONTENT",
                    threshold="BLOCK_ONLY_HIGH",
                )
            ],
        ),
    )

    # Depending on SDK version, parts may hang off resp.candidates[0].content.parts
    parts = getattr(resp, "parts", None)
    if not parts and getattr(resp, "candidates", None):
        try:
            parts = resp.candidates[0].content.parts
        except Exception:
            parts = None

    if not parts:
        raise RuntimeError("No image content returned (safety/quota/SDK change).")

    for part in parts:
        inline = getattr(part, "inline_data", None)
        if inline and getattr(inline, "data", None):
            return inline.data

    raise RuntimeError("No inline image bytes found in response.")


def _safe_slug(title: str) -> str:
    s = title.strip().lower()
    s = re.sub(r"[^a-z0-9 _-]+", "", s)
    s = re.sub(r"\s+", "_", s).strip("_")
    return s or "blog"

def save_blog_data(
    blog_title: str,
    data: dict
):

    file_path = (
        BLOG_DATA_DIR /
        f"{_safe_slug(blog_title)}.json"
    )


    file_path.write_text(
        json.dumps(
            data,
            indent=2,
            default=str
        ),
        encoding="utf-8"
    )


def generate_pdf_bytes(markdown_text: str) -> bytes:

    buffer = BytesIO()

    doc = SimpleDocTemplate(buffer)

    styles = getSampleStyleSheet()

    body_style = styles["BodyText"]

    story = []

    lines = markdown_text.splitlines()

    image_pattern = re.compile(
        r"!\[(.*?)\]\((.*?)\)"
    )

    for line in lines:

        line = line.strip()

        if not line:
            story.append(
                Spacer(1, 12)
            )
            continue

        if line.startswith("# "):

            story.append(
                Paragraph(
                    line[2:],
                    styles["Title"]
                )
            )

            continue

        if line.startswith("## "):

            story.append(
                Paragraph(
                    line[3:],
                    styles["Heading2"]
                )
            )

            continue

        m = image_pattern.match(line)

        if m:

            img_path = m.group(2)

            if Path(img_path).exists():

                try:

                    story.append(
                        Image(
                            img_path,
                            width=400,
                            height=250
                        )
                    )

                except Exception:
                    pass

            continue

        # Convert Markdown links
        line = re.sub(
            r"\[(.*?)\]\((.*?)\)",
            r'<font color="blue"><u><link href="\2">\1</link></u></font>',
            line
        )

        story.append(
            Paragraph(
                line,
                body_style
            )
        )

    doc.build(story)

    pdf_bytes = buffer.getvalue()

    buffer.close()

    return pdf_bytes

def generate_and_place_images(state: State) -> dict:
    start = time.time()
    settings = get_settings(state)
    plan = state["plan"]
    assert plan is not None

    md = state.get("md_with_placeholders") or state["merged_md"]

    image_specs = state.get("image_specs", []) or []
    # Respect user's image limit
    max_images = settings.get("max_images", 1)

    image_specs = image_specs[:max_images]
    image_errors = []
    generated_count = 0

    # ----------------------------------
    # No Images Case
    # ----------------------------------
    if not image_specs:
        

        filename =  BLOGS_DIR / f"{_safe_slug(plan.blog_title)}.md"

        filename.write_text(
            md,
            encoding="utf-8"
        )

        pdf_bytes = generate_pdf_bytes(md)
        
        duration = round(
            time.time() - start,
            2
        )

        timeline = list(
            state.get(
                "timeline",
                []
            )
        )

        timeline.append(
            {
                "step": "Images",
                "duration": duration
            }
        )
        return {
            "final": md,
            "pdf_bytes": pdf_bytes,
            "image_errors": [],
            "generated_image_count": 0,
            "timeline": timeline
        }

    # ----------------------------------
    # Image Generation
    # ----------------------------------
    images_dir = IMAGES_DIR

    for spec in image_specs:

        placeholder = spec["placeholder"]

        filename = spec["filename"]

        out_path = images_dir / filename

        # Generate image only if not already present
        if not out_path.exists():

            try:

                img_bytes = _gemini_generate_image_bytes(
                    spec["prompt"]
                )

                out_path.write_bytes(
                    img_bytes
                )
                generated_count += 1

            except Exception as e:

                error_msg = (
                    f"{spec['alt']} -> {str(e)}"
                )

                logger.error(error_msg)

                image_errors.append(
                    error_msg
                )

                # Remove image placeholder completely
                md = md.replace(
                    placeholder,
                    ""
                )

                continue
        else:
            # Image already exists for this blog
            generated_count += 1

        img_md = (
            f"![{spec['alt']}](images/{filename})\n"
            f"*{spec['caption']}*"
        )

        md = md.replace(
            placeholder,
            img_md
        )

    # ----------------------------------
    # Save Markdown
    # ----------------------------------

    filename =  BLOGS_DIR / f"{_safe_slug(plan.blog_title)}.md"

    filename.write_text(
        md,
        encoding="utf-8"
    )

    # ----------------------------------
    # Generate PDF
    # ----------------------------------
    pdf_bytes = generate_pdf_bytes(md)
    
    duration = round(
        time.time() - start,
        2
    )

    timeline = list(
        state.get(
            "timeline",
            []
        )
    )

    timeline.append(
        {
            "step": "Images",
            "duration": duration
        }
    )
    


    logger.info(
        f"Generated {generated_count} images"
    )
    
    # ----------------------------------
    # Return Final State
    # ----------------------------------
    return {
        "final": md,
        "pdf_bytes": pdf_bytes,
        "image_errors": image_errors,
        "generated_image_count": generated_count,
        "timeline": timeline
    }

def generate_seo(state: State) -> dict:
    start = time.time()
    generator = llm.with_structured_output(
        SEOData
    )

    seo = generator.invoke(
        [
            SystemMessage(
                content="""
                    Generate SEO metadata.

                    Return:

                    - seo_title
                    - meta_description
                    - keywords

                    Keep title under 60 chars.

                    Keep description under 160 chars.
                    """
            ),
            HumanMessage(
                content=state["final"][:8000]
            )
        ]
    )
    duration = round(
        time.time() - start,
        2
    )
    
    timeline = list(
        state.get(
            "timeline",
            []
        )
    )
    
    timeline.append(
        {
            "step": "SEO",
            "duration": duration
        }
    )

    logger.info("SEO metadata generated")
    
    save_blog_data(
        state["plan"].blog_title,
        {
            "plan":
                state["plan"].model_dump(),
            "evidence":
                [
                    e.model_dump()
                    for e in state.get(
                        "evidence",
                        []
                    )
                ],

            "timeline":
                timeline,
            "worker_times": state.get(
                "worker_times",
                []
            ),

            "image_specs":
                state.get(
                    "image_specs",
                    []
                ),  
            "generated_image_count": state.get(
                "generated_image_count",
                0
            ),

            "merged_md": state.get(
                "merged_md",
                ""
            ),

            "md_with_placeholders": state.get(
                "md_with_placeholders",
                ""
            ),

            "seo":
                seo.model_dump(),
            
            "generation_settings": state.get(
                "generation_settings",
                {}
            ),
            # ⭐ NEW
            "generation_settings": state.get(
                "generation_settings",
                {}
            ),


            "final":
                state.get(
                    "final",
                    ""
                )
        }
    )
    
    return {
        "seo": seo.model_dump(),
        "timeline": timeline
    }




# build reducer subgraph
reducer_graph = StateGraph(State)
reducer_graph.add_node("merge_content", merge_content)
reducer_graph.add_node("decide_images", decide_images)
reducer_graph.add_node("generate_and_place_images", generate_and_place_images)
reducer_graph.add_edge(START, "merge_content")
reducer_graph.add_edge("merge_content", "decide_images")
reducer_graph.add_edge("decide_images", "generate_and_place_images")
reducer_graph.add_edge("generate_and_place_images", END)
reducer_subgraph = reducer_graph.compile()

# -----------------------------
# 9) Build main graph
# -----------------------------

blog_graph = StateGraph(State)

blog_graph.add_node("router", router_node)
blog_graph.add_node("research", research_node)
blog_graph.add_node("orchestrator", orchestrator_node)
blog_graph.add_node("worker", worker_node)
blog_graph.add_node("seo", generate_seo)
blog_graph.add_node("reducer", reducer_subgraph)

# Start Flow
blog_graph.add_edge(START, "router")

# Router Decision
blog_graph.add_conditional_edges(
    "router",
    route_next,
    {
        "research": "research",
        "orchestrator": "orchestrator"
    }
)

# Research → Planner
blog_graph.add_edge("research","orchestrator")

# Planner → Dynamic Workers
blog_graph.add_conditional_edges("orchestrator",fanout,["worker"])

# Workers → Reducer
blog_graph.add_edge("worker","reducer")

# Reducer → SEO
blog_graph.add_edge("reducer","seo")

# SEO → END
blog_graph.add_edge("seo",END)

# Compile Graph
blog_writer_agent = blog_graph.compile()