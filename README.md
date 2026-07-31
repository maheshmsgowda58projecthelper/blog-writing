# 🚀 AI Blog Writing Agent using LangGraph

> **A production-style Agentic AI system that plans, researches, writes, and assembles complete blogs automatically using LangGraph's Orchestrator–Worker architecture.**

---

## 📖 Overview

This project demonstrates how modern **AI agents** are built beyond simple prompt engineering.

Instead of asking a single LLM to generate an entire blog, the system behaves like a real editorial team:

* 🧠 Plans the blog structure
* 🌐 Performs web research when needed
* 👨‍💻 Assigns sections to multiple AI workers
* ⚡ Generates content in parallel
* 🖼️ Plans and generates images
* 🔍 Creates SEO metadata
* 📄 Exports the final blog as Markdown and PDF
* 💾 Stores blogs with analytics and management features

The entire workflow is orchestrated using **LangGraph**, making it modular, scalable, and production-ready.

---

# ✨ Features

## 🤖 AI Blog Generation

Generate complete blogs from a single topic.

* Professional structure
* Multiple sections
* SEO-friendly writing
* Automatic conclusion
* Consistent writing style

---

## 🧠 Intelligent Routing

The Router Agent decides whether web research is required.

Supported modes:

* Auto
* Local
* Hybrid
* Web

This minimizes unnecessary API calls while improving factual accuracy.

---

## 🌐 Internet Research

Uses **Tavily Search** to gather recent information.

Automatically:

* Generates search queries
* Searches the web
* Filters duplicate results
* Collects evidence
* Passes evidence to workers

---

## 📋 Blog Planning

An Orchestrator Agent creates:

* Blog title
* Audience
* Writing tone
* Section outline
* Word targets
* Tags

This ensures every blog has a logical structure before writing begins.

---

## ⚡ Parallel AI Workers

Each section is written by an independent worker agent.

Instead of writing sequentially:

Section 1 → Section 2 → Section 3

The system writes all sections simultaneously using LangGraph's dynamic parallel execution.

---

## 📚 Evidence-Based Writing

Workers write using retrieved evidence instead of relying solely on LLM knowledge.

Each section includes:

* Web evidence
* Citations
* References

This significantly reduces hallucinations.

---

## 🖼️ Automatic Image Planning

The system identifies where images should appear.

For every image it generates:

* Caption
* Alt text
* Placeholder
* Image prompt

---

## 🎨 AI Image Generation

Automatically creates images matching the blog content.

Images are inserted into the final Markdown document.

---

## 🔍 SEO Metadata Generation

Automatically generates:

* SEO Title
* Meta Description
* Keywords

Useful for publishing blogs directly.

---

## 📄 PDF Export

Export the generated blog as a professional PDF.

---

## 📝 Markdown Export

Download the blog in Markdown format.

Perfect for:

* GitHub
* Notion
* Medium
* Dev.to
* Documentation

---

## 📦 ZIP Export

Download:

* Markdown
* Images

Together as a ZIP package.

---

## 📂 Blog Management

Supports:

* Blog history
* Search
* Categories
* Pinning
* Rename
* Delete

---

## 📊 Analytics Dashboard

Track:

* Total blogs
* Total words
* Images generated
* Runtime
* Evidence collected

---

# 🏗 System Architecture

```text
                    User
                     │
                     ▼
            Streamlit Frontend
                     │
                     ▼
          Generation Settings
                     │
                     ▼
             Router Decision
                     │
      ┌──────────────┴──────────────┐
      │                             │
      ▼                             ▼
 No Research                  Tavily Research
      │                             │
      └──────────────┬──────────────┘
                     ▼
            Planner (Orchestrator)
                     │
                     ▼
         Dynamic Worker Generation
                     │
      ┌────────┬────────┬────────┐
      ▼        ▼        ▼        ▼
   Worker1  Worker2  Worker3  WorkerN
      │        │        │        │
      └────────┴────────┴────────┘
                     ▼
                 Reducer
                     ▼
          Image Planning Agent
                     ▼
         AI Image Generation
                     ▼
          SEO Metadata Generator
                     ▼
        Markdown + PDF Generator
                     ▼
      SQLite + File Storage + UI
```

---

# 🛠 Tech Stack

## AI Framework

* LangGraph
* LangChain

## Large Language Model

* Groq (Llama 3.3 70B)

## Research

* Tavily Search

## Image Generation

* Google Gemini

## Frontend

* Streamlit

## Database

* SQLite

## Visualization

* Plotly

## PDF

* ReportLab

---

# 🧠 LangGraph Concepts Demonstrated

This project showcases many advanced LangGraph concepts.

* StateGraph
* Shared State
* Conditional Routing
* Router Nodes
* Planner (Orchestrator)
* Worker Agents
* Dynamic Parallel Execution (`Send`)
* Reducers
* Structured Outputs
* Multi-Agent Workflows
* Evidence-Based Generation

---

# 📂 Project Structure

```text
blog-writing-agent-using-langgraph/
│
├── bwa_backend.py
├── bwa_frontend.py
├── database.py
├── generation_settings.py
├── generation_settings_panel.py
├── requirements.txt
├── README.md
├── .env.example
│
├── blogs/
├── blog_data/
├── images/
```

---

# ⚙️ Installation

## Clone Repository

```bash
git clone https://github.com/maheshmsgowda58/blog-writing-agent-using-langgraph.git

cd blog-writing-agent-using-langgraph
```

---

## Install Dependencies

```bash
pip install -r requirements.txt
```

---

## Environment Variables

Create a `.env` file.

```env
GROQ_API_KEY=your_groq_api_key

TAVILY_API_KEY=your_tavily_api_key

GOOGLE_API_KEY=your_google_api_key
```

---

## Run the Application

```bash
streamlit run bwa_frontend.py
```

---

# 🎯 Example Workflow

User enters:

```
The Future of Artificial Intelligence
```

The system automatically:

1. Determines if research is needed
2. Searches the web
3. Creates a blog outline
4. Launches multiple worker agents
5. Writes sections in parallel
6. Generates citations
7. Plans images
8. Creates AI-generated images
9. Generates SEO metadata
10. Produces Markdown and PDF
11. Saves everything locally

---

# 💡 Future Improvements

* Authentication
* User accounts
* Cloud storage
* Vector database integration
* Long-term memory
* Human-in-the-Loop editing
* Multi-language blog generation
* Team collaboration

---

# 🎓 Learning Outcomes

This project demonstrates practical understanding of:

* Agentic AI
* LangGraph
* Multi-Agent Systems
* Orchestrator–Worker Pattern
* AI Workflow Design
* Parallel Processing
* Retrieval-Augmented Generation
* Production AI Application Development

---

# 👨‍💻 Author

**Mahesh M S Gowda**

GitHub: https://github.com/maheshmsgowda58

---

# ⭐ If you found this project useful

Please consider giving it a ⭐ on GitHub.
