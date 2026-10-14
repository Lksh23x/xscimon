## AI and GenAI research relevance scoring guide

**Goal:** Filter X posts for important developments in artificial intelligence and generative AI research—not generic AI chatter. Prioritize new, verifiable results, methods, releases, and developments that could materially change what models can do, how they are built, evaluated, or used.

### Score HIGH (0.7–1.0) for posts that report:

- **A new, substantive research result** or demonstrated capability, especially with clear evidence, comparisons, or reproducible experiments.
- **A new method, architecture, training technique, or framework** that offers a meaningful improvement or changes how a problem is approached.
- **A credible paper, preprint, or technical report** with a clear contribution. Give more weight to work with detailed methods, meaningful baselines, and evidence that supports the claims.
- **Specific, consequential benchmark or evaluation results**—including new benchmarks, major gains or failures, independent replications, or evidence that an existing benchmark is flawed.
- **A significant model release or update** with useful technical details: capabilities, limitations, evaluation, access, weights, or training and inference methods.
- **Code, model weights, datasets, or tools** that enable researchers to reproduce results or make a new capability practically accessible.
- **A major result in reasoning, agents, multimodality, robotics, AI for science, synthetic data, inference, or efficient training**—when the post explains what is new and why it matters.
- **Important safety, alignment, robustness, interpretability, or security research**, especially concrete evidence of a capability, failure mode, mitigation, or evaluation method.
- **A credible replication, correction, or retraction** that changes confidence in a widely cited result or influential claim.
- **A material policy, infrastructure, or compute development** when it has a direct, well-explained impact on AI research or the availability of important capabilities.
- **A claim of an unprecedented breakthrough** only when the post provides evidence, a technical source, and enough detail to assess what was actually demonstrated.

### Score MEDIUM (0.3–0.6) for:

- Informed analysis or synthesis of recent research that adds useful interpretation but reports no new result.
- A technically substantive conference talk, poster, workshop, or call for papers.
- A promising preprint with a potentially useful idea but limited validation, unclear comparisons, or no independent confirmation.
- Thoughtful discussion of research directions, open problems, limitations, or benchmark design.
- A model or tool announcement with some technical detail but uncertain novelty or research impact.
- Expert commentary on AI safety, capabilities, or societal implications that is grounded in concrete research or evidence.
- A paper summary that accurately explains the contribution but does not add new information.

### Score LOW (0.0–0.2) for:

- Congratulatory replies, social posts, or general career updates.
- Vague hype (“AGI is here,” “this changes everything,” “insane results”) without evidence or specifics.
- Product launches, demos, or feature announcements with no meaningful research contribution.
- Generic AI commentary, speculation, or predictions with no supporting evidence.
- Benchmark claims that omit the task setup, comparison conditions, or relevant limitations.
- Promotional posts that repeat a lab or company’s claims without technical substance.
- Retweets, quote posts, or paper links that add no explanation or useful context.
- Recycled research presented as new, or claims based only on an abstract, teaser, or viral clip.
- AI-themed content that is mainly unrelated politics, investing, lifestyle, or engagement bait.

### Importance and credibility checks

- **Novelty:** What is genuinely new compared with prior work?
- **Evidence:** Is the result supported by a paper, report, code, data, or a sufficiently detailed experiment?
- **Comparison:** Are baselines and evaluation conditions appropriate and clearly described?
- **Reproducibility:** Are methods, data, code, or model access available—or are limitations clearly stated?
- **Significance:** Does this change capabilities, costs, reliability, scientific understanding, or safety in a meaningful way?
- **Source quality:** Distinguish peer-reviewed work, preprints, lab announcements, independent evaluations, and unverified claims. A preprint can still be important, but don’t treat it as independently confirmed.
- **Time sensitivity:** Identify genuinely new results and releases; flag older work resurfacing as if it were breaking news.

### Output

For each post, return:

- **Score:** 0.0–1.0  
- **Topic:** e.g., LLMs, agents, multimodal, robotics, AI for science, safety, interpretability, infrastructure  
- **Key claim:** one concise sentence  
- **Why it matters:** the likely research or practical significance  
- **Evidence status:** peer-reviewed, preprint, official announcement, independent evaluation, or unverified  
- **Caveat:** the main uncertainty or limitation, if relevant  

**Scoring principle:** Rank by the importance and credibility of the information—not by excitement, virality, or the poster’s confidence.
