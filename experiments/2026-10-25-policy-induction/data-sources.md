# Public data for testing policy induction on real judgment

The question this data has to answer: does a learner recover the rules an organization actually
applies, beyond its written policy, from real decisions made by inconsistent people?

Synthetic τ² cases cannot supply four things:
- real approver inconsistency;
- real rarity;
- real language;
- a written policy that differs from practice.

Every source below has an "organization", a written policy and recorded human decisions. All
were reachable from this environment on 2026-10-25.

## Recommended first: Stack Exchange close decisions

| | |
|---|---|
| **Organization** | Each of about 180 sites (371 archives, including meta sites). Every site applies the same close reasons under its own help-center rules |
| **Decision** | A question is closed, or left open, and sometimes later reopened |
| **Reason** | A close-reason code: 101 duplicate, 102 off-topic, 103 unclear, 104 too broad, 105 opinion-based |
| **Voters** | The JSON list of who voted for each close. Reopens are recorded too, which signals disagreement |
| **Written policy** | Each site's help center ("what topics can I ask about here"). Not in the dump; it must be collected separately |
| **Access** | The archive.org copy of the April 2024 dump (CC BY-SA 4.0), one 7z file per site. Small sites are 27–200 MB |
| **Terms** | Attribution is required. Stack Exchange's newer self-hosted dumps forbid use for training LLMs. This use (evaluating rule induction, no LLM training) is outside that restriction, but use the archive.org copy and keep only derived statistics in the repository |

**Probe result (pets site, read-only, $0).** All counts exclude the meta site:
- 8,360 questions; 837 closed (10%); 95 of those later reopened.
- Close reasons: 615 duplicate, 99 off-topic, 55 unclear, 46 too broad, 33 opinion-based.
- Voters per close: 302 had a single binding voter (a moderator or gold-badge holder); 216 had
  five voters.
- Duplicates dominate, so the policy-judgment set is the about 230 non-duplicate closes on this
  site. The larger small sites have more: law, workplace, money, cooking, travel and academia
  are 80–200 MB each.

**How it maps onto the benchmark:**

| Benchmark element | Stack Exchange equivalent |
|---|---|
| Truth | Closed against left open (or reopened) |
| Starting policy | The site's written help-center rules, applied by a fixed rubric or an LLM reading them |
| Facts | Metadata needing no model: tags, length, code blocks, links, the asker's reputation, the question's age, whether it is a question at all. An LLM fact extractor is the paid option |
| Approver consistency | Reopens; single-voter against five-voter closes; agreement across voters' histories |
| Pooling | Train on one site, test on another, to see whether pooling across organizations averages preferences away |

**Limits:**
- These are curation decisions, not agent actions. They test the mechanism, not the τ² product
  setting.
- Questions that were never closed include ones nobody looked at. "Left open" is a weaker label
  than "closed".

## Also strong

- **Wikipedia Articles for Deletion.**
  - Debates with a keep/delete/merge outcome, many voters, and votes that cite policy by name
    (for example WP:GNG). So the gap between written policy and practice is visible in the
    record.
  - The Mayfield & Black corpus (2005–2018: about 400,000 debates, 3.2M contributions) is
    available through Cornell's ConvoKit.
  - WiDe-analysis (arXiv 2408.05655) offers a cleaned 2023–2024 set with outcome and stance
    labels.
  - Topic areas or WikiProjects can stand in for organizations.
- **Reddit moderator removals by subreddit.**
  - Chandrasekharan et al. (CSCW 2018, "The Internet's Hidden Rules") studied 2.8M removals
    across 100 subreddits. They sorted norms into site-wide, shared and community-specific.
  - The released data (Zenodo, doi:10.5281/zenodo.3338698) has over 2M removed comments and 40K
    labelled by norm.
  - It is the clearest public example of written rules against practiced norms. Data access has
    since tightened (Pushshift is gone), and only removals are included, never the comments
    moderators left up.

## Possible, not probed here

- **GitHub pull requests.** Each repository is an organization: CONTRIBUTING.md against merge
  or reject decisions, with review comments. They are available through the public API or GH
  Archive. Outcomes are noisy (PRs abandoned for unrelated reasons).
- **τ² airline domain.** The same benchmark style as retail, so it is a second synthetic domain
  for replication. It needs new oracle validators.
- **US mortgage decisions (HMDA, public through the CFPB).** Real approve and deny decisions
  with denial reasons, for each lender. There is no written policy, and the decisions are
  sensitive to fair-lending law. It is useful only for questions about consistency and rarity,
  and it needs care.

## Suggested next step

Preregister a Stack Exchange pilot on 3–5 small sites with metadata facts only ($0):
1. Measure consistency (reopens and binding-voter rates).
2. Run arms S and S-text with the frozen gate, with the starting policy as a fixed rubric from
   the help center.
3. Train on one site and test on another.

An LLM fact extractor or proposer would come after, under a set budget.

## Sources

- [Stack Exchange data dump on archive.org](https://archive.org/download/stackexchange) ·
  [Archive Team: Stack Exchange](https://wiki.archiveteam.org/index.php/Stack_Exchange) ·
  [Stack Overflow blog: data hosted by the Internet Archive](https://stackoverflow.blog/2014/01/23/stack-exchange-cc-data-now-hosted-by-the-internet-archive/) ·
  [ClickHouse example dataset notes](https://clickhouse.com/docs/en/getting-started/example-datasets/stackoverflow)
- [ConvoKit: Wikipedia Articles for Deletion corpus](https://zissou.infosci.cornell.edu/socialkit/documentation/_sources/wiki-articles-for-deletion-corpus.rst.txt) ·
  [WiDe-analysis (arXiv 2408.05655)](https://arxiv.org/pdf/2408.05655) ·
  [Borkakoty & Espinosa-Anke, WNUT 2025](https://aclanthology.org/2025.wnut-1.14)
- [The Internet's hidden rules (CSCW 2018)](https://experts.illinois.edu/en/publications/the-internets-hidden-rules-an-empirical-study-of-reddit-norm-viol/) ·
  [Reddit macro-norm dataset (Zenodo)](https://zenodo.org/records/3338698) ·
  [Hybrid approaches to detect macro-norm violations](https://ar5iv.arxiv.org/html/1904.03596)
