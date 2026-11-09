# Why LLM movie recommenders converge on a canonical core, and prompt-level fixes

Scope: zero-shot or prompt-based LLM recommenders (ChatGPT, GPT-4, Claude), the literature on RLHF mode collapse and diversity-eliciting prompting, flat taste signals, and metrics for a one-user service. The case in mind: a Raspberry Pi service calls `claude -p` once per evening (no temperature control) with about 90 "liked" films, asks for 8 candidates and keeps 3 unseen ones. The picks keep collapsing to the same arthouse and Criterion core.

---

## Q1. What 2023-2026 research says about popularity bias, homogenization and mode collapse in LLM recommenders

### Takeaway
Measured against classic collaborative filtering, LLM recommenders are *not* extremely popularity-biased. Claude and GPT-4 actually scored lower on popularity bias than kNN in one MovieLens study. They do have strong **low per-input variance**: asked the same thing again, they give nearly the same answer, and different models converge on the same answers. Preference tuning (RLHF/DPO) sharpens output toward "typical" answers. In a domain like "cinephile picks", the typical answer is the critics' canon, so the failure here is mode collapse onto a canon prior, not mainstream-blockbuster bias.

### Cited findings

**LLM-as-recommender bias studies**
- Lichtenberg, Buchholz & Schwöbel (Gen-IR@SIGIR'24) built a simple LLM movie recommender ("WOK"). It prompts with the watch history, asks for 10 movies as "title (year)", forbids already-watched films, and runs at temperature 0. They tested it on MovieLens-10M with gpt-3.5-turbo, gpt-4-1106, claude-instant-1.2 and claude-2.1. Their popularity-bias metric is the *log popularity difference*: mean log popularity of the recommended items minus mean log popularity of the user's items. Results: UserKNN 0.630, ItemKNN 0.957, TopPop 1.455, WOK-gpt-3.5 0.682, WOK-gpt-4 0.392, WOK-claude-v1 0.565, WOK-claude-2.1 0.377 (the lowest of all models). The LLM recommenders trailed CF on hit rate (HR@10 about 0.05-0.08 vs 0.411 for UserKNN). — [Lichtenberg et al. 2024, arXiv:2406.01285](https://arxiv.org/html/2406.01285v1)
- Same paper, prompt mitigations:
  - "Mitigate" added *"Recommend movies that match the average popularity level of the movies the user watched in the past."* Bias dropped modestly (claude-2.1 to 0.181, gpt-4 to 0.341), and accuracy fell slightly for most models.
  - "Minimize" added *"Recommend indie, niche, or less well-known movies, avoiding mainstream blockbusters."* Bias turned negative for all models (gpt-4 -0.972), HR@5 collapsed to 0.004-0.015, and invalid or unmatched titles rose (gpt-3.5: 3.39 per 10).
  - Takeaway: a blunt "avoid blockbusters" instruction overshoots into a different but still fixed region rather than spreading out. — [arXiv:2406.01285](https://arxiv.org/html/2406.01285v1)
- Di Palma et al. (GENNEXT@SIGIR'25) evaluated ChatGPT-3.5 and GPT-4 zero-shot with a role-playing "you are a recommender system" prompt on MovieLens-100k, Last.FM and Facebook Books, at top-10.
  - On movies, GPT-4 had 1−Gini 0.0853 and item coverage 553, against 0.1230 / 744 for the best CF (RP3β) and 0.3962 / 1395 for AttributeItemKNN. GPT-4's ARP was 95.70 vs 182.49 for MostPop.
  - So GPT-4's lists were *more concentrated on a small set of items* than graph or kNN baselines, while still being far less popular than MostPop.
  - Movies were the hardest domain for ChatGPT.
  - Plain zero-shot prompting for 50 items failed often: about 71% of lists were short or had duplicates.
  - — [Di Palma et al. 2025, arXiv:2601.01997](https://arxiv.org/html/2601.01997v1)
- The same paper cites prior work reporting that GPT-4 memorized 80.76% of MovieLens-1M (12.9% for LLaMA-3.1-405B). LLM movie knowledge sits on heavily memorized, frequently discussed titles. — [arXiv:2601.01997 (citing Di Palma et al. 2025)](https://arxiv.org/html/2601.01997v1)
- Deldjoo (2024) on ChatGPT movie recommendations:
  - GPT recommenders favor *newer* films (post-2000) and Drama, Comedy and Romance, compared with CF.
  - "Role-based prompts enhance fairness and diversity … mitigating popularity bias", and embedding the directive in the system role worked better than putting it in the user prompt.
  - Explicit diversification prompts cut NDCG by up to about 50%.
  - Even at temperature 0, five repeated runs showed small variations but "high consistency", meaning low run-to-run diversity.
  - — [Deldjoo 2024, arXiv:2401.10545](https://arxiv.org/html/2401.10545v3); [abstract](https://arxiv.org/abs/2401.10545v1)
- Hou et al. (ECIR'24), "LLMs are Zero-Shot Rankers": LLM rankers show position bias (candidate order in the prompt changes the output) and popularity bias. Bootstrapping, i.e. re-ranking several times over shuffled candidate orders and aggregating, reduces position bias. — [Hou et al., arXiv:2305.08845](https://arxiv.org/html/2305.08845v2)
- Zhang et al. (RecSys'23), "Is ChatGPT Fair for Recommendation?" (FaiRLLM benchmark): ChatGPT's movie recommendations shift with stated sensitive attributes, with country, continent, race and religion the most affected. Implication: whatever identity or context sits in the prompt steers which canon the model reaches for. — [Zhang et al., arXiv:2305.07609](https://arxiv.org/pdf/2305.07609)

**General mode collapse and homogenization**
- Kirk et al. (ICLR'24): compared with SFT, RLHF significantly reduces *per-input* output diversity (many samples for one prompt) on syntactic, semantic and logical metrics. It also reduces across-input diversity, less strongly, meaning outputs converge regardless of input. — [Kirk et al., arXiv:2310.06452](https://arxiv.org/html/2310.06452v2)
- Zhang et al., "Verbalized Sampling" (2025; ICML 2026 poster), identify **typicality bias** in preference data: annotators favor familiar, typical text.
  - Mechanism: the reward picks up an α·log π_ref(y|x) term, so the aligned optimum is π* ∝ π_ref^γ · exp(r/β) with γ = 1 + α/β > 1. That *sharpens* the distribution toward the base model's most typical completions, and typicality acts as a tie-breaker when many answers are equally good.
  - The fitted α on HelpSteer was 0.57-0.65 (p < 1e-14).
  - — [arXiv:2510.01171](https://arxiv.org/html/2510.01171v2); [ICML 2026](https://icml.cc/virtual/2026/poster/60489)
- NoveltyBench (Zhang et al., 2025): across 20 leading LMs, models produce far less diversity than humans. Claude 3 and GPT-4o give on average fewer than 3 functionally distinct answers in 10 queries (distinct@10: Claude-3.5-Sonnet 1.76, Claude-3.5-Haiku 1.94, Claude-3-Opus 2.04). Larger models in a family tend to be *less* diverse (Llama-3 1B 6.74 vs 70B 2.49). — [NoveltyBench, arXiv:2504.05228](https://arxiv.org/html/2504.05228v4)
- "Artificial Hivemind" (Jiang et al., NeurIPS 2025 Datasets & Benchmarks, best paper): the Infinity-Chat set has 26K real open-ended queries. The authors find (1) intra-model repetition and (2) inter-model homogeneity, where different models give strikingly similar outputs. Reward models and LM judges are poorly calibrated on items where human preferences are idiosyncratic. — [arXiv:2510.22954](https://arxiv.org/abs/2510.22954); [UW news on award](https://news.cs.washington.edu/?p=40103)

### Inferences
- The observed core (Possession, Holy Motors, Chungking Express, Mulholland Drive, Wings of Desire, Perfect Blue, The Conversation, The Fire Within, The Mother and the Whore) looks like the *typical answer* to "eclectic cinephile who likes Polanski, Wong Kar-wai and Noé, minus blockbusters". The typicality-sharpening mechanism in the VS paper predicts exactly this: many films are equally valid recommendations, and the tie-breaker is "most typical / most often co-mentioned in cinephile text". (Inference; not tested on films.)
- "Avoid obvious mega-blockbusters" probably *moves* the mode from the IMDb Top 250 to the critics' or Criterion canon instead of flattening it, mirroring Lichtenberg's "Minimize" prompt, which pushed every model to a new fixed point. (Inference from [arXiv:2406.01285](https://arxiv.org/html/2406.01285v1).)
- One call per evening with a near-identical prompt is the worst case for per-input diversity (Kirk; NoveltyBench). Without temperature control, and even with it, the day-to-day prompt has to change materially, or the model has to see its previous outputs.
- Memorization (GPT-4 memorized 80.76% of ML-1M) suggests that recall of heavily discussed titles is "cheap". Long-tail or recent festival titles (2022-2025) are both less represented and riskier to hallucinate, so the model hedges toward safe canon.
- Large frontier models may be *more* collapsed than small ones (NoveltyBench). Using a bigger Claude model does not by itself fix this.

### Gaps
- No found study measures day-over-day repetition of a deployed single-user LLM recommender, or targets "critics' canon" collapse as distinct from popularity bias. Most work uses MovieLens popularity (rating counts), which would score Possession or The Fire Within as *low* popularity and so hide this failure mode.
- No published numbers for Claude 4.x-era models as movie recommenders; the most recent Claude in a rec study is claude-2.1 (2024).
- The Artificial Hivemind abstract gives no quantitative similarity figures; I did not read the full paper.

---

## Q2. Why "please be diverse" fails, and which prompt techniques measurably help

### Takeaway
Instructions like "be diverse" or "be creative" in a system prompt are only marginally effective (NoveltyBench), and list-level requests at best give a uniform pick among the same mode-adjacent items (VS paper, Claim 2). The techniques with measured gains:
1. **In-context regeneration**: show the model what it already produced and ask for different answers. This was the strongest intervention in NoveltyBench.
2. **Verbalized Sampling**: ask for k candidates with probabilities, optionally only from the tails (p < 0.10), then sample in code. Diversity gains were 1.6-2.1x.
3. **Injected randomness**: String Seed of Thought, or simply varying the prompt content (random subsets, shuffled order, rotating constraints).
4. **Role or system-level framing**: modest gains.

Selecting from the candidates in code (not by the LLM) is what turns these into real day-to-day variety.

### Cited findings
- NoveltyBench compared four interventions:
  - Resampling at temperature 1.0 (baseline).
  - Prompt paraphrasing: "only marginally effective".
  - A system prompt asking for unique or creative answers: "only marginally effective"; asking for creative outputs "does not work very well".
  - **In-context regeneration**, where earlier answers stay in context and the model is asked for a different one: the most successful method, with three models roughly matching human diversity.
  - — [arXiv:2504.05228](https://arxiv.org/html/2504.05228v4)
- The VS paper's theory appendix (Claim 2): "List-level prompts return uniform distributions at best." Asking for a list and picking randomly gives a flat distribution over items the model already deems typical, with no tail mass. Verbalizing probabilities lets sampling follow, or deliberately skew away from, the model's distribution (Claim 3). — [arXiv:2510.01171 v2, App. E.4](https://arxiv.org/html/2510.01171v2)
- VS variants:
  - VS-Standard: one call, k responses with probabilities.
  - VS-CoT: reason first.
  - VS-Multi: several turns, each adding new candidates with probabilities.
  - k=5 for creative tasks and k=20 for open-ended QA. Too large a k degrades quality, and a higher k raises diversity.
  - A tail threshold ("each probability < 0.10") is a tunable diversity knob that needs no decoding parameters.
  - In open-ended enumeration (e.g., "name a US state"), VS lowered KL to the reference distribution and raised coverage while precision stayed about 1.0. VS-Multi gave the best trade-off.
  - Larger models gained 1.5-2x more diversity from VS. Claude-3.7-Sonnet and Claude-4-Sonnet were among the tested models.
  - VS is orthogonal to temperature and stacks with it.
  - — [arXiv:2510.01171 v2](https://arxiv.org/html/2510.01171v2)
- The authors' recommended VS prompt, verbatim: *"Generate 5 responses to the user query, each within a separate <response> tag. Each <response> must include a <text> and a numeric <probability>. Please sample at random from the tails of the distribution, such that the probability of each response is less than 0.10."* For more, ask "5 more" in the same conversation, which is the VS-Multi or in-context regeneration pattern. Their Python helper samples one item from the verbalized distribution in code (`dist.sample(seed=…)`). — [CHATS-lab/verbalized-sampling README](https://github.com/CHATS-lab/verbalized-sampling)
- String Seed of Thought (Misaki & Akiba, Sakana AI, ICLR 2026): the model first writes a random-looking string inside tags and then derives its choice from it. This brings LLM sampling close to a PRNG on distribution-faithful tasks and yields more diverse NoveltyBench outputs than prompt paraphrasing or higher temperature, without losing quality. It is prompt-only and needs no fine-tuning. — [arXiv:2510.21150](https://arxiv.org/html/2510.21150v2); [ICLR 2026](https://iclr.cc/virtual/2026/poster/10007633)
- Hou et al.: shuffling candidate or history order and aggregating several runs (bootstrapping) reduces position bias. Input order measurably changes LLM recommendation output, so a randomized order is a cheap source of variation. — [arXiv:2305.08845](https://arxiv.org/html/2305.08845v2)
- Role-based or system-role prompting raised fairness and diversity, and system-role placement beat in-prompt directives. Explicit diversification prompts cost up to about 50% NDCG. — [Deldjoo, arXiv:2401.10545](https://arxiv.org/html/2401.10545v3)
- A popularity-anchoring prompt ("match the average popularity level of the movies the user watched") reduced bias with small accuracy loss. A "niche only, avoid blockbusters" prompt overshot, giving negative bias, many invalid titles and a collapse in accuracy. — [arXiv:2406.01285](https://arxiv.org/html/2406.01285v1)
- Two-stage generate-then-rerank: Carraro & Bridge use an LLM to re-rank a relevance-ranked candidate set for diversity, measured with ILD and subtopic recall. It increases diversity but trades away more relevance and costs more than greedy algorithmic re-rankers such as MMR. — [Carraro & Bridge, arXiv:2401.11506](https://ar5iv.labs.arxiv.org/html/2401.11506)
- Plain zero-shot requests for long lists (50 items) produced short or duplicate-laden lists about 71% of the time, and few-shot about 44%. Very long candidate lists from one call are unreliable. — [arXiv:2601.01997](https://arxiv.org/html/2601.01997v1)

### Inferences (practical recipe for the Pi service; not directly tested in the literature)
1. **Move randomness out of the LLM.** Python, not Claude, should pick a daily "lens" from a rotating schedule (country or region × decade × facet × tone). Write it into the prompt as a hard constraint, e.g. "tonight: a non-European film made before 1985 that connects to the user's cyberpunk/techno facet". This uses the variation lever (prompt content) instead of the absent one (temperature).
2. **In-context regeneration via history.** Put the last 30-60 days of recommended titles, plus a fixed "canon blocklist" (the 9 titles above and similar), in the prompt as "already suggested / do not suggest". NoveltyBench found this the strongest single intervention. Also filter in code afterwards, since LLMs don't fully obey exclusion lists (Lichtenberg's "unmatched" counts include already-watched films).
3. **Verbalized Sampling for candidates.** Ask for 15-20 candidates as JSON `{title, year, country, facet, probability}`, "sampled from the tails, each probability < 0.10" (k=20 is what VS used for open-ended QA). Then *in Python*: drop seen, blocklisted and recently suggested films, enforce one pick per facet, and sample 3 weighted by (1 − p) or uniformly among tail items.
4. **Seed with a random subset.** Instead of the full ~90-film list every night, send a random 10-15-film "anchor" subset drawn from 1-2 facets, plus the full list only as a "seen" filter. The input changes daily and conditions the model on specific neighbors rather than the averaged "eclectic cinephile" persona that summons the canon. Shuffle order daily (Hou position bias).
5. **Persona or lens conditioning.** Rotate a curator persona (e.g., "programmer of a Tokyo midnight-movie series", "Berlin club-culture film festival curator", "Rotterdam IFFR Tiger competition scout") in the *system role*, which Deldjoo found more effective than in-prompt directives.
6. **Anchor popularity, don't just forbid it.** Following Lichtenberg's "Mitigate" phrasing, ask for films whose obscurity matches the user's own non-canon picks (Berlin Calling, Roujin Z, Hackers) rather than "avoid blockbusters", which pushes into a new canon. Better still, check obscurity in code via vote counts (see Q4).
7. **Two-stage critique (optional, costs a second call).** Stage 2 gets the candidates and is told to strike any title that "would appear on a Sight & Sound / Criterion / 1001 Movies list". It can also ask "5 more, different from these" (VS-Multi). Expect some relevance loss (Carraro & Bridge, Deldjoo).
8. **SSoT** is a cheap add-on if picking happens inside the LLM: "first write a random 20-character string in <seed>, then use it to choose the facet and decade". Code-side randomness is simpler and more reliable for this service.

### Gaps
- No found paper tests VS, SSoT or in-context regeneration *specifically for recommendation* or for film titles; the evidence comes from creative writing, open QA and NoveltyBench.
- No study quantifies the hallucination or invalid-title rate under tail sampling for films. Lichtenberg's "Minimize" result suggests it rises, so title validation (TMDB/IMDb lookup) is needed.
- I did not find practitioner blog posts that measured canon repetition in LLM movie picks; the search turned up only academic work.
- I could not verify how `claude -p` handles sampling parameters; no source was checked for this.

---

## Q3. Effect of a flat taste signal (no ratings, all "liked") and how to recover structure

### Takeaway
No LLM-recommender study isolates the "all items liked, no ratings" case. Classic calibration work, though, shows that a user's history is a *mixture* of interests, and recommendations should cover that mixture in proportion (Steck's calibrated recommendations). With a flat signal, the LLM tends to summarize the list into one centroid persona. Explicitly clustering the list into facets and rotating through them restores the structure.

### Cited findings
- Steck (2018) "Calibrated Recommendations": build the user's target genre distribution p(g|u) from their history, weighted by ratings. Re-rank so the list's genre distribution q(g|u) matches it, minimizing KL(p‖q) and trading relevance against calibration with λ. Uncalibrated recommenders over-represent the user's dominant interest and crowd out minor ones. — [Calibrated Recommendations survey, arXiv:2507.02643](https://arxiv.org/pdf/2507.02643); [contextual-bandit follow-up, arXiv:2509.05460](https://arxiv.org/html/2509.05460v1)
- Jensen-Shannon divergence is a common alternative to KL for calibration, and a normalization fix to Steck's method improves both precision and calibration. — [arXiv:2507.02643](https://arxiv.org/pdf/2507.02643)
- In Lichtenberg's study the user-relative popularity metric (recommended items vs the user's own items) was the basis for a "match your own popularity level" prompt. The user's own list can anchor obscurity even without ratings. — [arXiv:2406.01285](https://arxiv.org/html/2406.01285v1)
- Di Palma: in cold-start (≤10 interactions), GPT-4's coverage collapsed to 89 items and 1−Gini to 0.0349. With weak per-user signal, the LLM falls back on a small shared set of items. — [arXiv:2601.01997](https://arxiv.org/html/2601.01997v1)

### Inferences
- With about 90 equally weighted films and no ratings, the model has no way to tell "core love" from "watched once". It compresses the list into the most typical description (roughly "auteur arthouse, slightly transgressive") and returns that description's canonical neighbors. The cyberpunk, anime, techno and cozy-indie facets get averaged away. This is consistent with the cold-start collapse Di Palma observed (low coverage when the signal is weak).
- Practical structure recovery (offline and cheap; re-run when the list changes):
  1. **Facet clustering.** One-off: ask Claude, or use TMDB genres, keywords and country plus an embedding, to cluster the ~90 films into 6-10 named facets, e.g. "90s cyberpunk/hacker", "Japanese anime body-horror/mecha", "Berlin techno/club", "slow cozy indie (Paterson, Perfect Days)", "Wong Kar-wai urban melancholy", "Polanski/Noé transgression", "recent festival 2022-25". Store them as JSON.
  2. **Facet rotation and calibration.** Each evening, choose 1-2 facets by weighted round-robin, with weights ∝ facet size (Steck-style calibration) and a penalty for facets used recently. Condition the prompt on that facet's films only.
  3. **Recency weighting.** Films added in the last N weeks (IMDb list/Letterboxd timestamps) signal current taste. Oversample them as anchors, e.g. exponential decay with a ~60-day half-life. This is a heuristic, not from a cited source.
  4. **Implicit-strength proxies.** A Letterboxd "like" plus a rewatch, or a film on both IMDb and Letterboxd, could count as a stronger signal than a single list entry (heuristic).
  5. **Use each facet's own obscurity** (median IMDb vote count of facet members) as that facet's target novelty level, so the techno facet gets Berlin Calling-level obscurity rather than Possession-level canon.

### Gaps
- No found 2023-2026 paper studies LLM recommendation from unary, unrated, uniformly "liked" lists, or LLM-based clustering of a user history into facets for recommendation. The recipe above is extrapolated from calibration work.
- No source quantifies the benefit of recency weighting for a single user.

---

## Q4. Metrics for a small personal recommender

### Takeaway
Use cheap, log-based beyond-accuracy metrics:
- **Repetition rate** across days.
- **Catalog coverage**: distinct titles over a window.
- **Novelty** as popularity percentile or log vote count, relative to the user's own list.
- **Intra-list diversity** over metadata such as country, decade and genre.
- **Facet coverage and calibration** (KL or JS between facet shares in the picks and in the list).
- **Canon-hit rate** against a fixed canon list.
- **Validity rate**: real, unseen titles.

All are computable from a JSONL log plus TMDB or IMDb metadata.

### Cited findings (definitions)
- Beyond-accuracy metrics used in LLM-rec evaluation (Di Palma et al.):
  - **Gini index** (concentration of recommendations over items; report 1−Gini, higher = more even).
  - **Item coverage** (distinct items recommended).
  - **EPC / EFD** (expected popularity complement / expected free discovery; rank-aware novelty, higher = more novel).
  - **APLT** (share of long-tail items).
  - **ARP** (average recommendation popularity).
  - — [arXiv:2601.01997](https://arxiv.org/html/2601.01997v1). EPC/EFD come from Vargas & Castells' rank- and relevance-aware novelty framework. — [Vargas & Castells, RecSys 2011](https://dl.acm.org/doi/10.1145/2043932.2043955)
- **Log popularity difference** (user-relative popularity bias): mean log popularity of the recommended items minus the user's mean. 0 means the recommendations match the user's popularity level and negative means more obscure. — [arXiv:2406.01285](https://arxiv.org/html/2406.01285v1)
- **Intra-List Diversity (ILD)** and **Subtopic-Recall** for diversity of a single list. — [Carraro & Bridge, arXiv:2401.11506](https://ar5iv.labs.arxiv.org/html/2401.11506)
- **distinct@k** (number of functionally distinct answers among k samples) and **utility@k** (novelty weighted by quality) for generation-level diversity. — [NoveltyBench, arXiv:2504.05228](https://arxiv.org/html/2504.05228v4)
- **Calibration** via KL or JS divergence between the user's interest distribution and the recommendation distribution. — [arXiv:2507.02643](https://arxiv.org/pdf/2507.02643)
- **Coverage-N and KL to a reference distribution** for enumerative outputs. — [VS paper, arXiv:2510.01171](https://arxiv.org/html/2510.01171v2)

### Inferences (concrete metric set for one user; log every candidate, not just the 3 picks)

| Metric | How to compute | Target / alarm |
|---|---|---|
| Repetition rate | Share of today's 8 candidates (and 3 picks) already suggested in the last 30 days | Picks: ~0%; candidates: < 20% |
| Distinct titles / window (coverage) | Unique candidate titles over 7 and 30 days ÷ total candidates (a local distinct@k) | Rising, close to 1.0 |
| Gini over candidate titles | Over a rolling 30-day log | Low concentration |
| Novelty | Per pick: −log10(IMDb numVotes) or vote-count percentile from the IMDb `title.ratings` dataset; report as log-popularity difference vs the user's list median (Lichtenberg) | Near 0 or slightly negative; alarm if consistently positive |
| Canon-hit rate | Share of candidates on a fixed canon list (e.g. S&S top-250, Criterion, IMDb Top 250) | < 20-30% |
| Intra-list diversity | Mean pairwise distance among the 8 candidates on country, decade, primary genre and facet (e.g. 1 − Jaccard of tag sets, or embedding cosine) | High |
| Facet coverage / calibration | Over 7 days: facets hit at least once ÷ total facets, plus JS divergence between pick facet shares and list facet shares | Most facets weekly, low JS |
| Country / decade entropy | Shannon entropy of picks' countries and decades over 30 days | Rising |
| Validity | Share of candidates that resolve to a real TMDB/IMDb ID and are unseen | > 90% (tail prompts lower this) |
| Recency share | Share of picks from 2022+ | Tune to taste (the user watches recent festival films) |

- A/B over time: alternate prompt variants week by week (baseline vs VS + history + facet rotation) and compare these metrics. One user means no statistical power, so treat the comparison as directional.
- The user's own thumbs-up/down on picks, if added, gives the only real accuracy signal. Without it, beyond-accuracy metrics are all you have.

### Gaps
- No source sets benchmark thresholds for a single-user service. The targets in the table are judgment calls.
- Sources disagree on whether LLM recommenders are "diverse":
  - Lichtenberg finds Claude and GPT-4 *less* popularity-biased than kNN.
  - Di Palma finds GPT-4 *less* even than CF on Gini and coverage in movies.
  - Deldjoo reports diversity gains from role prompts.
  - The answer depends on the metric (popularity vs concentration vs repetition). For this service the key one is repetition and concentration over time, which popularity metrics don't capture.
