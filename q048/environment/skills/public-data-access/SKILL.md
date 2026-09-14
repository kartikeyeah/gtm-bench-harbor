---
name: public-data-access
description: Use when a GTM Bench run needs traceable prospecting evidence from web search, local files, and other explicitly available harness tools.
---

# Public Data Access

Use the evidence sources exposed in the current harness to build a defensible
lead/prospect artifact. Every final row should be traceable to evidence the
evaluator can inspect or reproduce from the run artifacts.

## Workflow

1. Read the rendered benchmark task and derive the offer and ICP before
   prospecting.
2. Identify the available tools in the harness: web search, page retrieval,
   shell commands, local files, or other task-provided evidence sources.
3. Use official websites, credible directories, public profiles, news, and
   task-provided files to gather evidence.
4. Write `offer.md` and `icp.md` in the current workspace.
5. Produce a final lead/prospect CSV artifact. Prefer writing `leads.csv` and
   also include CSV-compatible structured output in the final response.
6. Preserve traceability by keeping source URLs, domains, and short evidence
   claims in the final rows.

## Evidence Rules

- Prefer official company websites and credible primary sources for fit claims.
- Do not invent facts, contact details, URLs, or evidence.
- Do not rely on snippets alone when the claim is important and a page can be
  opened.
- Use concise, targeted searches rather than broad scraping loops.
- Mark uncertain or weakly supported prospects in `disqualification_risks` or
  `evidence_gaps`.
- Use `web` in `data_sources` for web evidence.
- Use `local_file` in `data_sources` for evidence taken from task-provided local
  files.

## Contact Rules

- Each final row must identify a specific person to contact.
- Include the best available contact route: business email, phone, LinkedIn URL,
  or another defensible contact path.
- If the task is account-only, still include the most relevant buyer persona and
  clearly mark missing direct contact details.
- Do not include placeholder people, guessed emails, or fabricated phone numbers.

## Data Access Boundaries

- Use only data sources and tools explicitly available inside the harness.
- Do not attempt to access credentials, hidden environment variables, unrelated
  local files, or external systems outside the task scope.
- Do not print or write environment variables that may contain secrets.
- If a useful claim cannot be supported by available evidence, exclude the row or
  mark the evidence gap.

## Required Workspace Files

Create these files in the current workspace:

```text
offer.md
icp.md
leads.csv
```

## Default CSV Columns

Use these columns unless the task explicitly asks for a different schema:

```csv
rank,company_name,company_domain,website,person_first_name,person_last_name,job_title,business_email,phone,linkedin_url,company_city,company_state,company_country,industry,employee_count,revenue,fit_score,evidence,source_urls,data_sources,disqualification_risks,compliance_flags
```

## Final Validation

Before finishing, check that:

- `offer.md` and `icp.md` exist.
- The final artifact is parseable as CSV-compatible structured data.
- Rows are deduplicated by company domain and person when possible.
- Every included prospect has public evidence and a defensible contact path.
