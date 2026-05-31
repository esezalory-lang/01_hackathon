# Track: Forecasting AI
## Use Case Title: Build on Probability — Decision Agents on a Probabilistic Forecasting API

**Challenge Owner:** Sybilion
**Mentor(s):** TBD (Sybilion domain expert + Lumos)
**Difficulty:** Intermediate to Advanced
**Estimated Scope:** Yes, the case is realistic in 36h. The forecasting engine is provided as an API, so teams focus on building decision logic, reasoning, and adaptive behavior on top — not on training their own model. The deliberately open domain choice lets teams scope to what their team can ship.

---

### 1. Problem Statement (3–5 sentences)

Most forecasting tools give you a number. This one gives you a result with the meaningful signals that drove it — but a number plus a driver list does not, by itself, change decisions. The gap between a probabilistic forecast and an actual decision change is where the work sits: how do you build an agent that takes the API output, surfaces what matters, and helps a real decision-maker act on it? Teams have 36 hours to pick a domain where uncertainty affects decisions, build a decision agent on top of the Sybilion API, and prove on Sunday that their agent changes outcomes when assumptions shift mid-run.

### 2. Why It Matters (Business Context)

- Forecasting models are everywhere; **decision agents that use them well are rare**. The bottleneck in most organizations is not prediction accuracy — it is the translation of probabilistic output into action that respects uncertainty.
- Wide confidence bands are not noise to be ignored. They are the most decision-relevant part of the output, because they encode *when not to act*. Agents that hide uncertainty cause worse decisions than no agent at all.
- Driver importance changes by horizon: a signal that dominates month one may be irrelevant by month six. An agent that surfaces the right driver at the right time enables far better strategic thinking than a static dashboard ever could.
- Connection to **European AI Sovereignty**: this case is explicitly *not* about training another forecasting model. It is about building independent decision intelligence on top of a European forecasting infrastructure, in a way that other tools and APIs cannot easily replicate.

### 3. Expected Outcome / Definition of Done

- **Minimum Viable Result:** A working decision agent or application built on the Sybilion API, scoped to a clearly defined domain, demonstrating end-to-end how a forecast and its driver signals translate into a concrete decision recommendation. A short written summary documenting key technical challenges and solutions.
- **Stretch Goals:** Agent that adapts when a core assumption shifts mid-run, multi-scenario simulation, integration of multiple driver signals across horizons, custom UI that makes uncertainty legible to non-experts, large-scale scenario stress-testing on Leonardo.
- **Learning goals for participants:** Building decision logic on top of probabilistic forecasts, designing for uncertainty rather than around it, sourcing and preparing real time-series data, surfacing driver importance in a way humans can act on, stress-testing agent behavior against shifting conditions.
- **Format:** Working agent or application plus brief written summary (key technical challenges encountered, solutions implemented).
- **Sunday live demo:** A domain-specific challenge is presented live on stage. The agent runs in real time and the jury evaluates three key areas: whether the forecast changes the decision, whether the reasoning is visible, and whether the agent adapts when a core assumption shifts mid-run.

### 4. System Specification

- **Forecasting engine:** Provided as a hosted API (Sybilion). The team does not build or train the model itself. The API accepts monthly time series plus contextual keywords and returns:
  - A probabilistic month-by-month forecast across outcome bands
  - External signals driving the forecast, scored by importance at each future horizon
  - Backtest accuracy data showing how the model would have performed historically
- **Decision agent (build focus):** A layer on top of the API that ingests forecast output, applies domain logic, and produces recommendations or decisions. This is where the team's technical contribution lives.
- **Domain choice:** Free. The choice itself is part of the technical work — finding a domain where probabilistic forecasting changes a real decision and where current tools fall short. Examples are listed below as inspiration; teams are encouraged to find something that is not on the list.
- **Constraints:** Reproducibility (the agent must run live on Sunday), traceable reasoning (the jury must be able to see *why* a recommendation was made), and adaptability (the agent must not hard-code assumptions that cannot shift mid-run). Explicitly **not** acceptable: a basic LLM wrapper that pipes API output through a model and prints a summary. The agent must have substantive logic of its own — decision rules, multi-signal synthesis, custom backtest workflow, scenario engine, or comparable.

### 5. Task Structure (Levels)

- **Level 1:** Pick a domain, source a usable time series that meets the API's minimum data requirements, get a first forecast back, understand what the driver importance scores actually mean for the chosen domain.
- **Level 2:** Build a decision agent that uses the forecast and driver output to produce a recommendation or action. Validate the recommendation against historical backtest data. Make the reasoning visible — a black-box recommendation does not pass.
- **Level 3 / Stretch:** Make the agent **adaptive**. When a core input or assumption shifts (a signal moves, a new constraint is introduced, a market event changes the picture), the agent should respond visibly and sensibly. This is the Sunday demo capability.

### 6. Domain Choice — Inspiration, Not Constraint

The domain choice is deliberately open. Teams pick where probabilistic forecasting can change decisions and where current tools fall short. Examples include:

procurement · pricing · logistics · energy · risk management · trading · supply planning · insurance · lending · investment workflows · policy planning · food security · deforestation monitoring · crime or safety forecasting · migration flows · money laundering risk · humanitarian response · election forecasting

These are illustrative. Some of the strongest possible answers come from domains not on this list — areas where the team brings unique knowledge or where the current mix of data and technology obviously falls short. The choice itself is part of the technical sophistication being judged.

### 7. Data & Resources

- **Sybilion API:** Hosted forecasting engine. Documentation at [sybilion.dev/docs](https://sybilion.dev/docs/). API quota per team: TBD (will be confirmed before the event).
- **Keyword quality is critical:** The relevance and quality of the input keywords directly drive forecast accuracy. Picking good keywords for your domain is itself part of the technical work, not a preprocessing step.
- **Minimum data point requirements (monthly time series):**

  | Forecast horizon | Minimum data points required |
  |---|---|
  | 1–3 months | 40 |
  | 4–6 months | 60 |
  | 7–12 months | 120 |

  Teams should pick domains where they can source time series that satisfy these minimums. Shorter horizons are easier to feed.

- **Recommended data sources:**
  - World Bank Commodity Markets / Pink Sheet — [worldbank.org](https://www.worldbank.org/en/research/commodity-markets)
  - FRED (Federal Reserve Economic Data) — [fred.stlouisfed.org](https://fred.stlouisfed.org/)
  - Eurostat — [ec.europa.eu/eurostat/data/database](https://ec.europa.eu/eurostat/data/database)
  - Yahoo Finance — [finance.yahoo.com](https://finance.yahoo.com/)
  - Our World in Data — [ourworldindata.org/data](https://ourworldindata.org/data)

- **Compute:** Leonardo cluster is available for teams that want to go further. High-performance compute enables use cases such as training auxiliary models, benchmarking against the API's accuracy at scale, or running agents across a large set of synthetic scenarios simultaneously to find where they break before Sunday. GPU quota per team: TBD.
- **NDAs / data privacy:** All recommended data sources are public. Teams are responsible for respecting source license terms.

### 8. Evaluation & Benchmarking

- **Eval setup:** Each team's deliverable is evaluated in two phases. First, the standing deliverable (working agent + written summary). Second, a **live, domain-specific challenge** presented on stage during the Sunday demo, in which the agent must run in real time and respond to a mid-run change in assumptions.
- **Three evaluation dimensions for the live demo:**

  | # | Dimension | Question | What the jury looks for |
  |---|---|---|---|
  | 1 | **Decision change** | Does the forecast change the decision? | Concrete recommendation differs meaningfully from a naive baseline |
  | 2 | **Visible reasoning** | Is the reasoning visible? | Driver importance, confidence band, and decision logic are surfaced — not hidden behind a chat output |
  | 3 | **Adaptive behavior** | Does the agent adapt when a core assumption shifts mid-run? | When the assumption changes on stage, the agent responds sensibly and transparently, not by parroting its prior answer |

- **Visualization:** Expected at minimum: the forecast with confidence bands clearly shown, driver-importance over horizon, and a clear surface of the decision the agent is recommending. A black-box "trust me, here's the answer" agent does not pass.
- **Backtest discipline:** Teams should use the API's backtest data to validate their decision logic against historical performance. Recommendations not grounded in backtest evidence are weaker than those that are.

### 9. Evaluation Criteria (track-specific)

The jury scores each category from 1 (poor) to 5 (excellent):

1. **Commercial impact / social impact** — How meaningful is the problem the agent solves? Could this actually be deployed, used, or scaled?
2. **Originality of idea** — Is the domain choice and approach genuinely creative, or a predictable use of a forecasting tool?
3. **Technical sophistication** — How well-built is the agent? Is the logic substantive, or a thin wrapper around the API?

The live-demo dimensions (decision change, visible reasoning, adaptive behavior) feed into all three scores.

### 10. Contact & Support During the Event

- **Challenge Owner:** Sybilion (Slack channel `#help-forecasting`)
- **On-site mentor:** TBD
- **Domain expert (Slack/phone):** TBD on Sybilion side
- **Emergency contact:** Lumos desk in the lobby
