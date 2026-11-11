# Ultimate Goal: Deploy a Zero-Trust Remote Quant Hub

**The Ultimate Goal of this project is to derive cross-domain natural gas market Alpha by translating high-level natural language trading commands into deterministic, Point-in-Time financial analytics, executed securely and remotely over a zero-trust network.**

---

## 💡 Expected & Required System Output
When a user hits the remote edge endpoint with a natural language command (e.g., *"Stress test a pipeline freeze during high winter demand"*), the system must produce a **final JSON payload** and an **immutable audit artifact**:

1. **Deterministic SQL Translation:** A precise, read-only `SELECT` statement targeting exactly the historical snapshots available on that specific historical day, preventing look-ahead bias.
2. **Quantitative Impact Calculation:** A floating-point number representing the supply/demand balance disruption in Billion Cubic Feet per Day (Bcf/d).
3. **Structured Market Thesis:** A strict, un-vetted, two-sentence explanation detailing the cross-domain correlation between current variables and the target asset.
4. **Immutable Audit Trail:** A permanent, timestamped markdown log published as a private GitHub Gist via the local host's `gh` CLI, archiving the execution history for retrospective model verification.

---

## 🛠️ System Infrastructure Constraints (Do Not Modify)
* **Local OS/GPU:** Linux Mint (`joey-dell`), Intel Arc iGPU (Vulkan accelerated).
* **Local LLM Daemon:** Ollama running `qwen3:4b` pinned in VRAM (`Forever`) with `num_ctx: 2048` and `num_predict: 45`.
* **Database:** SQLite (`henry_hub_pit.db`) with table `pit_market_data` tracking 4-column Point-in-Time (PIT) series (`agent_id`, `target_timestamp`, `available_timestamp`, `value`).
* **Ingress Secure Tunnel:** `cloudflared` routing `quant.joeysvault.app` to local port `8090`.

---

## 🧠 Instruction for Incoming LLM: Backward-Engineer the Path
You are an advanced quantitative engineering agent. Your objective is to **backward-engineer the execution path** from the stated goal and constraints above, producing the complete codebase required to bridge the edge network with the local hardware stack.

### Step 1: Backward-Engineer the Edge Gateway (`worker.js` / Cloudflare Worker)
* Generate a serverless JavaScript gateway.
* Authenticate incoming mobile/API requests via a header `Authorization: Bearer <MOBILE_COMMAND_SECRET>`.
* Inject required `CF-Access-Client-Id` and `CF-Access-Client-Secret` headers to bypass the Cloudflare Access firewall.
* Forward POST requests cleanly to `https://joeysvault.app`.

### Step 2: Backward-Engineer the Local Execution Server (`command_hub.py` / Python FastAPI on Port 8090)
* **Environment Loader:** Read service token keys and local file paths cleanly from a local `.env` profile.
* **API Endpoint:** Expose a single POST endpoint at `/execute` accepting JSON payloads (`query`, `as_of_timestamp`).
* **Context Retrieval System:** Query recently injected physical context slices (EIA storage, weather ensembles) from `henry_hub_pit.db` or a local ChromaDB collection filtered strictly by `available_timestamp <= as_of_timestamp` to strip look-ahead bias.
* **LLM Translation Interface:** Construct an async handler calling local Ollama (`qwen3:4b`) using strict JSON schema formatting and the `/no_think` token limiter to output:
  1. `sql_query`: A safe, read-only `SELECT` query against `pit_market_data`.
  2. `scenario_delta_bcf`: Floating-point supply/demand balance delta estimate.
  3. `alpha_thesis`: Concise 2-sentence market impact text.
* **Safe SQL Sandbox:** Execute the compiled query against `henry_hub_pit.db` strictly in read-only mode (`mode=ro`).
* **Subprocess Audit Logger:** Programmatically call the GitHub CLI (`gh gist create`) locally using Python's `subprocess` engine to upload a timestamped, private Markdown audit log summarizing the command, analytical output, rows returned, and PIT cutoff.
