# Pipeline design for a one-user, 3-films-a-day LLM movie recommender (Raspberry Pi, Python stdlib + numpy)

Scope note: about 17 tool calls (searches and fetches). Classic algorithm papers were checked against primary sources where possible. Items marked "(background knowledge, not verified this session)" come from my own knowledge and were not re-checked against a source in this session. Treat them as leads to verify, not citations.

---

## 1. Hybrid architecture: multi-source candidate generation followed by LLM re-ranking. Should the LLM generate or re-rank, and how do you ground it?

### Takeaway
Since 2023 the literature has converged on a two-stage pattern. Cheap, grounded retrieval from known catalog items produces candidates, and the LLM ranks or explains them. Pure LLM generation is the least controllable option. It can hallucinate titles that are not in the catalog, it shows position and popularity biases, and inside a feedback loop it can amplify popularity and polarize exposure. For this project, keep Claude's brainstorm as one candidate source among several. Resolve every title to a TMDB/IMDb id before scoring, and let code, not the LLM, enforce diversity, calibration and exploration. Use Claude for the final choice among a small, pre-diversified shortlist and for the explanation.

### Cited Findings
- Hou et al. frame LLM recommendation as **conditional ranking**: the user's history is the condition, and the candidates come from *other* candidate generators. Zero-shot LLMs rank promisingly, but (a) they struggle to perceive the order of the history, and (b) **item popularity and the position of a candidate in the prompt bias them**. Special prompting and bootstrapping (shuffling the candidate order and aggregating several runs) reduce these effects. When candidates come from **multiple generators**, zero-shot LLM ranking can compete with conventional models. — [Hou et al., "LLMs are Zero-Shot Rankers for Recommender Systems", ECIR 2024, arXiv:2305.08845](https://arxiv.org/pdf/2305.08845)
- LlamaRec uses a two-stage design. A small sequential recommender retrieves the top 20 candidates, and an LLM (Llama-2-7B) ranks them. To avoid slow and unconstrained autoregressive generation of titles, it scores candidates through a verbalizer: each candidate gets a letter index and the logits over those letters are read. It reports gains over LLM generators such as PALR and GPT4Rec. — [Yue et al., LlamaRec, arXiv:2311.02089](https://arxiv.org/pdf/2311.02089)
- Generative recommenders "can be prone to hallucinations, sometimes even recommending out-of-inventory items". The grounding approach the authors recommend is to first collect relevant items and then let an LLM compose the final response. — [Toward Holistic Evaluation of Recommender Systems Powered by Generative Models, arXiv:2504.06667](https://arxiv.org/html/2504.06667v2)
- The RecLM work (ACL 2026 Findings) groups OOD/hallucination mitigation into three grounding paradigms: **retrieval-based**, **constrained generation** and **item-tokenizer**. Its variants reach OOD@10 = 0. — [Eliminating Out-of-Domain Recommendations in LLM-based RS, arXiv:2505.03336](https://arxiv.org/html/2505.03336v2)
- A 2026 audit of zero-shot LLM recommenders, including Claude Sonnet 4.6, reports that the catalog-hit rate swings by about 60 points. On identical outputs, the measured hallucination rate moves by an order of magnitude depending on the string matcher used to check catalog membership. Title-to-id resolution is therefore a real engineering issue, not a formality. — [Do LLM Recommenders Know When They're Hallucinating?, arXiv:2608.10008](https://arxiv.org/pdf/2608.10008)
- In a simulated feedback loop, LLM components in recommenders **amplify popularity bias**, hallucinations inject **spurious signals**, and exposure becomes **polarized and self-reinforcing** over time. — [EchoTrace / "Echoes in the Loop", arXiv:2602.07442](https://arxiv.org/abs/2602.07442)
- Popularity evidence is mixed. In a movie task, a simple LLM recommender showed *less* popularity bias than traditional recommenders without any mitigation. Prompting it toward indie films reduced bias further, but it then began recommending films obscure enough to lower accuracy. — [Lichtenberg, Buchholz, Schwöbel, "LLMs as Recommender Systems: A Study of Popularity Bias", Gen-IR@SIGIR24, arXiv:2406.01285](https://arxiv.org/abs/2406.01285)
- ChatGPT-based movie recommenders tend to recommend newer films and more diverse genres than collaborative-filtering baselines, though not always as accurately. — [Deldjoo, "Understanding Biases in ChatGPT-based Recommender Systems", arXiv:2401.10545](https://arxiv.org/html/2401.10545v1)
- A 2025 study of LLM rerankers notes that they can produce plausible but incorrect rationales when justifying pairwise or listwise choices. — [How Good are LLM-based Rerankers?, arXiv:2508.16757](https://arxiv.org/pdf/2508.16757)

### Inferences
- **Recommended pipeline (one user, runs nightly on the Pi):**
  1. **Seed sampling.** Draw about 6–10 seed films from the user's ~90 films and from recent clicks. Stratify the draw by facet (section 2) so the seeds don't all come from the arthouse cluster.
  2. **Candidate sources**, each tagged with `source` for the bandit in section 4:
     - (a) `tmdb_recommendations` and `tmdb_similar` per seed (item-item graph);
     - (b) metadata neighbors: same director, director "lineage", same writer or cinematographer, shared TMDB keywords such as `cyberpunk`, `techno`, `berlin`;
     - (c) **Claude brainstorm** with an explicit facet or theme prompt, which outputs titles and years only;
     - (d) a "festival/recent" source: TMDB discover by year ≥ 2022 plus a vote-count band.
  3. **Grounding/resolution.** Map every title to a TMDB id using (title, year), not fuzzy title alone. Drop unresolvable titles, seen films, films already sent, and films that fail hard constraints.
  4. **Feature vector per candidate:** genres, decade, country, original language, director, keyword set, `log(vote_count)` (popularity tier), `vote_average`, the source tag, and the seed facet that produced it.
  5. **Deterministic scoring:** a relevance proxy, such as how many sources and seeds hit the film, keyword overlap with the facet centroid, and a quality floor.
  6. **Slot-based diversified selection in code** (sections 2–3): build a shortlist of about 3 candidates per slot.
  7. **Claude final pick and explanation.** Give Claude the shortlist in a **shuffled** order (Hou et al. position bias), ask for one pick per slot, and require the answer by candidate letter or id, never as a free title (the LlamaRec verbalizer idea plus constrained output). The explanation must cite only metadata passed in the prompt, so it cannot hallucinate facts.
- Generating candidates with Claude while temperature is unavailable: diversity has to come from the **prompt** (different seed subsets, facet or theme, a decade or country constraint, an "exclude these 50 titles" list) instead of from sampling.
- Keep Claude's share of the final picks bounded. One way is to require at least one of the 3 picks to come from a non-LLM source, so LLM popularity priors don't take over the feedback loop (EchoTrace).

### Gaps
- I found no published head-to-head of "LLM-generator vs LLM-reranker" for a *single user with ~100 items*. All the evidence comes from datasets with thousands of users.
- I did not verify Letterboxd engineering write-ups. I found no public Letterboxd recommender architecture document.
- Chat-REC (Gao et al. 2023) and similar "LLM + retrieval" conversational designs are relevant but were not fetched this session.

---

## 2. Taste-facet clustering of a small list and allocating 3 daily slots (comfort / adjacent / exploration)

### Takeaway
Spotify's Daily Mix is an industry precedent. It clusters the user's history into groupings, extends each cluster with recommendations, and mixes familiar items with new ones. For about 90 films, simple clustering on hand-built features works: Jaccard over {director, country, decade, genres, keywords}, or numpy cosine over one-hot features, with agglomerative or k-medoids clustering and k≈6–10. You could also have Claude label facets once, then freeze and review the labels. Each daily slot then takes a role.

### Cited Findings
- Spotify's Daily Mix produces up to six mixes. It "looks for groupings of a user's most commonly listened to artists", extends each cluster with recommendations, balances familiar and new content, and orders the mixes by how much listening drove each one. A product lead described building a taste picture from the similarity distances between the artists a user plays and then finding natural groupings in it. The exact methods are not public. — [Spotify newsroom (summarized via search)](https://newsroom.spotify.com/tag/understanding-the-app); [Medium overview of Daily Mix](https://medium.com/systems-ai/spotifys-machine-learning-algorithms-and-your-daily-mix-f49d97db4b16)
- Calibration (section 3) formalizes the same concern. When a system optimizes accuracy alone, the most relevant items cluster on one facet "at the expense of other facets that go unrepresented". — [Kleinberg, Ryu, Tardos, "Calibrated Recommendations for Users with Decaying Attention", arXiv:2302.03239](https://arxiv.org/pdf/2302.03239)
- Ziegler et al.'s topic diversification balances top-N lists against "a user's full range of interests" and introduced the **intra-list similarity (ILS)** metric. It lowered offline accuracy but **improved user satisfaction** in an online study with more than 2,100 BookCrossing users. — [Ziegler et al., WWW 2005](https://archives.iw3c2.org/www2005/proceedings/docs/p22.pdf); [project page](https://dbis.informatik.uni-freiburg.de/forschung/projekte/2nd-Gen-RS)

### Inferences
- **Practical facet extraction (stdlib only):**
  - Represent each liked film as a set of tokens: `dir:Polanski`, `dec:1960s`, `cty:IT`, `gen:Thriller`, `kw:cyberpunk`, `lang:ja`, `kind:anime`.
  - Compute pairwise weighted Jaccard. Weight the tokens, for example director 3, keyword 1, genre 0.5, decade 1, country 1.
  - Run average-linkage agglomerative clustering (about 90² = 8,100 pairs, trivial on a Pi) and cut at k≈7.
  - For this user the expected facets are roughly: 60s–70s European modernism (Polanski, Antonioni); Hong Kong / Wong Kar-wai; transgressive French (Noé); 90s cyberpunk / hacker; anime (80s–90s plus Shinkai); Berlin techno / club; cozy slow indie (Jarmusch, Kaurismäki, Wenders); festival films 2022–25; psychological thrillers.
  - Alternative: have Claude propose facet labels **once**, store them in JSON, and re-run only when the list grows by more than 10 films. This keeps the nightly runs deterministic.
- **Slot roles per day:**
  - **Slot A, "close/comfort":** candidates seeded from a facet with positive click history, with a high relevance score and at least a mid popularity tier.
  - **Slot B, "adjacent":** candidates that share one or two facet dimensions but break one, e.g. same decade and country but a different director, or the same keyword in a different country.
  - **Slot C, "exploration":** a low popularity tier (a vote-count band below the user's median), or a facet chosen by Thompson sampling with a wide prior, or a "theme of the day" (section 5).
- **Facet choice per slot:** use Thompson sampling over facets (section 4), with a hard constraint that the 3 picks come from 3 different facets, and none of the same facets as yesterday's picks where possible.
- The anime, techno and cyberpunk facets are small (perhaps 3–6 films each). Under proportional calibration they would almost never get a slot, so give each facet a **floor quota**, e.g. at least one appearance every 7–10 days (see section 3 on rolling-week calibration).

### Gaps
- I found no paper that evaluates role-based slot allocation (comfort / adjacent / explore) for very short lists. The design is an inference from Daily Mix, calibration and explore/exploit work.
- I found no benchmark comparing clustering methods on lists of about 100 items.

---

## 3. Diversification: MMR, DPP and calibration with 3 slots per day and over a rolling week

### Takeaway
With N=3 per day, set-level diversity inside one email is easy to enforce. The harder problem is **cross-day** sameness. Apply the diversifier to a sliding window: the last 7 days' sent items plus today's 3. All three methods are greedy and cheap:
- **MMR:** λ·rel − (1−λ)·max similarity to already-selected items.
- **Fast greedy DPP:** kernel L = Diag(exp(α·r))·S·Diag(exp(α·r)).
- **Steck calibration:** (1−λ)·Σrel − λ·KL(p‖q̃), with the greedy guarantee proven only for equal weights.

### Cited Findings
- **DPP (Chen, Zhang, Zhou, NeurIPS 2018):**
  - Kernel L = Diag(r)·S·Diag(r), with relevance r and PSD similarity S; S_ij = (1+⟨f_i,f_j⟩)/2 maps similarities into [0,1].
  - The relevance/diversity trade-off is θ·Σrel + (1−θ)·log det(S_R). This equals a DPP with kernel Diag(exp(αr))·S·Diag(exp(αr)), where α = θ/(2(1−θ)).
  - Greedy MAP with incremental Cholesky costs O(N²M) for N items out of M candidates.
  - A **sliding-window** variant enforces diversity only within a window of w items, at cost O(wNM).
  - Stop when d_j² < ε.
  - The method was confirmed in an online A/B test. — [arXiv:1709.05135 (ar5iv full text)](https://ar5iv.arxiv.org/html/1709.05135); [NeurIPS paper](https://papers.NeurIPS.cc/paper_files/paper/2018/file/dbbf603ff0e99629dda5d75b6f75f966-Paper.pdf)
- **Calibration (Steck, RecSys 2018):**
  - The genre mix of a list should match the user's historical genre proportions. It is implemented as a **post-processing re-rank**.
  - Miscalibration is measured with KL(p‖q̃), where q̃ is smoothed with a small α so the KL stays finite.
  - The greedy heuristic is within (1−1/e) of optimal for the equal-weight (set) case. — [Steck slides](https://www.slideshare.net/slideshow/calibrated-recommendations/118205343); [summary of calibration literature](https://www.themoonlight.io/en/review/calibrated-recommendations-survey-and-future-directions)
- The list's genre distribution is defined as q(π)(g) = Σ_j w_j·q_{π_j}(g), with position weights w_j summing to 1. Steck suggested weights like MRR or nDCG. With unequal weights, KL gives a mixed-sign objective, so the guarantees no longer hold. Bounded overlap measures, such as those from **Hellinger distance**, behave better, and a greedy algorithm achieves a 2/3 approximation in the single-genre model. In a user study, people judged system quality within a single session of about 15 minutes, which argues for calibrating *within* each delivery, not only on average over the long run. — [Kleinberg, Ryu, Tardos, arXiv:2302.03239](https://arxiv.org/pdf/2302.03239)
- Later work uses Jensen-Shannon and Hellinger as bounded alternatives to KL, and also min-cost-flow formulations. Seymen et al. criticize greedy calibration as myopic. — [search summary of calibration literature](https://www.themoonlight.io/en/review/calibrated-recommendations-survey-and-future-directions); [Confidence-aware calibrated recommendation, arXiv:2208.10192](https://ar5iv.labs.arxiv.org/html/2208.10192)
- **MMR** (Carbonell & Goldstein, SIGIR 1998) selects items greedily by argmax[λ·Sim1(d,Q) − (1−λ)·max_{d_j∈S} Sim2(d,d_j)]. — [ACM DL 10.1145/290941.291025](https://dl.acm.org/doi/10.1145/290941.291025) (background knowledge, not verified this session)

### Inferences
- **What to use at N=3:**
  - **MMR over a window** is the simplest choice and enough. The similarity is the weighted Jaccard from section 2. Measure similarity against the *selected set ∪ items sent in the last 7–14 days*. This turns MMR into a cross-day diversifier at no extra cost.
  - **DPP** adds little over MMR for 3 items. Use its sliding-window form only if you want a principled single parameter θ. With numpy, a log-det over at most a 24×24 matrix (3 today plus 21 from the week) is trivial on a Pi.
- **Rolling-week calibration with stdlib:**
  - Let p(facet) be the distribution of the user's liked films over facets (or genre×decade). Smooth it toward uniform, e.g. p' = 0.7·p + 0.3·uniform, so small facets (anime, techno) still get mass. You can also blend it with a click-weighted distribution.
  - Let q be the distribution of items sent over the last 7 days plus today's candidates.
  - Each day, greedily add the item maximizing (1−λ)·rel_i − λ·H(p', q ∪ {i}). Use **Hellinger or Jensen-Shannon**, not KL, because 21 items is a tiny sample and KL is unbounded or zero-sensitive (Kleinberg et al.).
  - Start with λ≈0.5 and tune by eye.
- Use **multiple calibration axes** (genre, decade, country/language, popularity tier) as a sum of per-axis divergences. This directly counters "canonical arthouse" homogeneity, because a decade or tier axis penalizes picking three 1960s European classics.
- Position weighting is mostly irrelevant here. All 3 picks show in one email, so equal weights hold and Steck's set guarantee applies.

### Gaps
- I could not open the full text of Steck's RecSys 2018 paper this session, so the exact weight w_{u,i} and the value of α are not verified. The often-quoted α≈0.01 is unverified.
- I found no study of calibration or diversity with lists as short as 3 items per day, aggregated across days.

---

## 4. Exploration vs exploitation with tiny feedback: bandits over facets and sources; novelty, serendipity and popularity tiers

### Takeaway
With about 3 impressions a day and sparse clicks, per-item learning is hopeless. Learn at a **coarse level**: one Beta-Bernoulli arm per facet and per source, and possibly per popularity tier. Thompson sampling gives principled exploration in about 10 lines of stdlib (`random.betavariate`). Spotify's BaRT is the industry precedent for a bandit choosing which explained recommendation to show. Define "exploration" explicitly as relevant, novel and unexpected (Kotkov), and control popularity with vote-count bands.

### Cited Findings
- Spotify's **BaRT** ("Bandits for Recommendations as Treatments") is a contextual bandit that pairs items with **explanations** and accounts for uncertainty about user satisfaction. Collaborative filtering can only exploit or ignore an item, while the bandit adds an explore option. It beat the best static ordering of explanations offline and significantly improved engagement in live tests. — [McInerney et al., RecSys 2018, slides](https://static1.squarespace.com/static/5ae0d0b48ab7227d232c2bea/t/5ba85dac7817f764cdda68f4/1537760712983/bart_recsys.pdf); [bibliographic record](https://bibsonomy.org/bibtex/28398b26af8d86e48cb457e0931a8c1f7/brusilovsky); [patent US11301513](https://patents.google.com/patent/US11301513)
- Kotkov defines serendipitous items as **relevant, novel and unexpected** to the user, and documents eight variants of the definition. There is no consensus definition, a point repeated in a 2023 ACM Computing Surveys review. — [Kotkov dissertation, 2018](https://jyx.jyu.fi/handle/123456789/58207?show=full); [Kotkov et al., "Challenges of Serendipity in RS", 2016](https://scitepress.org/Papers/2016/58798/pdf/index.html)
- When an LLM recommender is pushed toward indie or niche films, it can overshoot into films too obscure to be relevant. The popularity tier has to be controlled, not simply minimized. — [Lichtenberg et al., arXiv:2406.01285](https://arxiv.org/abs/2406.01285)
- Hou et al. found popularity bias in zero-shot LLM ranking. If Claude does the final ranking, it will favor canonical titles. — [arXiv:2305.08845](https://arxiv.org/pdf/2305.08845)

### Inferences
- **Thompson sampling over arms (stdlib):**
  ```python
  # arms: facets ∪ sources ∪ pop_tiers; state: alpha, beta per arm (start 1,1 or 2,2)
  theta = {a: random.betavariate(s.alpha, s.beta) for a, s in arms.items()}
  # slot A uses argmax theta over facets; slot C samples from the posterior with higher prior variance
  # update after outcome window (e.g., 7 days): clicked -> alpha += 1; sent-not-clicked -> beta += w_neg (w_neg ~ 0.3-0.5)
  ```
  - Use **discounted** updates (multiply α and β by γ≈0.97 per day toward the prior) so arms recover, and an arm that is unlucky early is not frozen out. This is a sliding-window or discounted TS, from background knowledge (Russo et al., "A Tutorial on Thompson Sampling", arXiv:1707.02038; not verified this session).
  - Treat a non-click as *weak* negative evidence (w_neg < 1). The user may simply not have opened the email.
- **Popularity tiers** from TMDB `vote_count`, with log-scale bands (approximate):
  - T1 "canon": more than 5k votes;
  - T2 "known": 500–5k;
  - T3 "deep cut": 50–500;
  - T4 "obscure": fewer than 50, usually excluded or only allowed with a quality floor.
  
  Give each tier a target share over the rolling week (e.g. 30/40/30 for T1/T2/T3), enforce it through the calibration axis in section 3, and adapt it with the tier arms' TS posteriors. This directly attacks "only top-canon".
- **Operational novelty and unexpectedness**, computable without user studies:
  - novelty = −log(popularity), or 1 − (fraction of the user's list in the same facet);
  - unexpectedness = 1 − max Jaccard to any liked film;
  - serendipity candidate = relevance ≥ threshold AND unexpectedness ≥ threshold.
  
  Reserve slot C for these.
- With roughly 0–3 clicks a week, arm posteriors stay wide for months. Expect the system to look exploratory for a long time. That is acceptable for this use case, and the priors could be set from the list's facet sizes (e.g. α0 = 1 + 0.2·n_liked_in_facet).

### Gaps
- I found no published guidance on bandit settings for a single user at about 3 impressions per day. Any parameter values above are heuristic.
- I did not verify the BaRT paper's full text, only its slides, abstract and patents. Its reward definition (stream duration over 30 s) is from background knowledge.

---

## 5. Day-level themes (country / decade / director lineage of the day): do they improve perceived diversity?

### Takeaway
I found no direct study of "theme-of-the-day" rotation in recommenders. Two pieces of indirect evidence support it. Users rate lists spanning more of their interests higher (Ziegler), and industry presents personalized content in named, coherent groupings (Spotify Daily Mix clusters, BaRT's explanation-labelled shelves). A theme also gives Claude a concrete prompt constraint, which is the main lever for diversity when temperature can't be controlled.

### Cited Findings
- Topic diversification increased user satisfaction even though offline accuracy dropped (more than 2,100 online subjects). Users prefer lists spanning their whole range of interests over lists covering one or two topics. — [Ziegler et al., WWW 2005](https://archives.iw3c2.org/www2005/proceedings/docs/p22.pdf); [Freiburg project page](https://dbis.informatik.uni-freiburg.de/forschung/projekte/2nd-Gen-RS)
- Spotify organizes personalization into several named clusters, the Daily Mixes, each reflecting a listening mode. — [Spotify newsroom](https://newsroom.spotify.com/tag/understanding-the-app)
- BaRT treats an explanation (shelf label) and item pair as the unit the bandit chooses, which implies that the framing or theme itself affects engagement. — [BaRT slides](https://static1.squarespace.com/static/5ae0d0b48ab7227d232c2bea/t/5ba85dac7817f764cdda68f4/1537760712983/bart_recsys.pdf)

### Inferences
- **Practical design:** a theme applies to *one slot* (slot C, or B), not the whole email, so a disliked theme doesn't waste a whole day.
  - Rotate theme *types* (country → decade → director lineage → keyword or movement → festival year) on a fixed cycle.
  - Pick theme *values* by TS over facets, plus "never repeat within N days".
  - Example themes for this user: "Japan 1980s–90s" (Roujin Z adjacency); "Berlin / German 2000s"; "Antonioni lineage → Tsai Ming-liang"; "Finnish deadpan"; "techno-thriller 1995–2001".
- A theme doubles as the explanation header in the email, e.g. "Today: Hong Kong 1990s". It is cheap, and it plausibly improves perceived diversity and transparency (Ziegler; BaRT).
- Themes can be a bandit arm type themselves: clicks on themed slots update the theme-type arm.

### Gaps
- I found no controlled evidence that rotating daily themes improves perceived diversity or satisfaction versus non-themed diversification. This is an untested design hypothesis.

---

## 6. Implicit feedback without ratings: sent-not-clicked vs clicked, decay, and avoiding feedback loops

### Takeaway
Treat clicks or downloads as **positive with high confidence**. Treat "sent, not clicked" as **negative with low confidence**, in the spirit of Hu, Koren and Volinsky's preference + confidence framing. Learn at the facet, source and tier level, not the item level. Decay old evidence. Prevent feedback loops by keeping a fixed exploration share, keeping some candidates from non-LLM sources, and never feeding the system's own sent items back as "liked" seeds unless they were clicked.

### Cited Findings
- Hu, Koren and Volinsky treat implicit observations as indicators of **preference** (binary) with widely varying **confidence**. Unobserved entries are weak negatives, not missing data. A commonly cited form is c = 1 + α·r (from a secondary summary, not verified in the paper text). — [Hu, Koren, Volinsky, ICDM 2008 (record)](https://www.bibsonomy.org/bibtex/22342427342bcf66c0f59160fa90dcfaf/nosebrain); [paper PDF copy](https://samuel-deng.github.io/math4ml_su24/project/Hu_et_al.pdf); [secondary review](https://ddoeunn.github.io/2020/11/22/PAPER-REVIEW-Collaborative-Filtering-for-Implicit-feedback-datasets.html)
- LLM-powered recommenders in closed feedback loops amplify popularity bias, propagate hallucinated signals, and drift toward polarized, self-reinforcing exposure. — [arXiv:2602.07442](https://arxiv.org/abs/2602.07442)
- Spotify's Daily Mix uses listening history and active feedback, and one secondary source says Spotify weights recent activity above historical data. — [Spotify newsroom](https://newsroom.spotify.com/tag/understanding-the-app); [secondary overview](https://medium.com/systems-ai/spotifys-machine-learning-algorithms-and-your-daily-mix-f49d97db4b16) (secondary claim, low confidence)

### Inferences
- **Signal ladder** (confidence weights to apply at the facet, source and tier arms, and as seed weights):
  - Download click: +1.0, and the film enters the seed pool with weight about 1.
  - Letterboxd link click (if tracked): +0.3.
  - Sent, not clicked after 7 days: −0.3, applied to arms only, never to the film's metadata neighbors.
  - Sent twice in the same facet with no click: increase the facet's cooldown.
  - The original ~90-film list is the stable prior, at weight 1, and does not decay.
- **Decay:** exponential half-life of about 60–90 days on click-derived weights and arm counts. The original list stays constant, so the system can't forget the core taste.
- **Loop guards:**
  - (1) A fixed exploration share: one slot a day is always TS-sampled or explore, never pure exploit.
  - (2) A source quota: at least one non-LLM-sourced pick per day.
  - (3) Popularity-tier calibration (section 4).
  - (4) Never treat "sent" as "liked". Only clicks update seeds.
  - (5) Log the per-slot `source`, `facet`, `tier` and `theme` with every send, so that off-policy evaluation (e.g. per-arm click rate weighted by inverse selection probability, which needs the TS sampling probability logged) is possible later.
- Hard no-repeat: a set of every TMDB id ever sent, plus all films the user has seen or liked. This also guards against Claude re-suggesting the same canon. Pass a compact exclusion list (recent sends plus the top canon in the current facet) into the brainstorm prompt.

### Gaps
- I found no study quantifying how a "sent, not clicked" email impression should be weighted versus a true negative. Email non-opens confound it, and click tracking can't tell "not opened" from "opened, not interested" unless open tracking exists.
- "Degenerate Feedback Loops in Recommender Systems" (Jiang et al., AIES 2019, arXiv:1902.10730) is the classic reference on loop degeneracy and the role of exploration, but it was not fetched this session (background knowledge only).
