# Cinesis Load Matcher
**Live Demo**: https://hawkeye.mdrul.dev/
**Stack:** Python, FastAPI, OpenAI, plain HTML/CSS/JS

## Part A — Extraction

Transcript was sent to OpenAI with a structured JSON prompt. Fields were inferred from natural speech — the driver never stated them as clean fields. Key assumption: weight capacity defaulted to 16,000 lb (hotshot gooseneck legal max). The 44,000 lb figure in the transcript is the dispatcher describing their Huntsville load, not the driver's truck capacity. Prompt explicitly instructs the LLM to extract weight only from Driver-spoken lines.

## Part B — Ranking

Filter order: equipment → price → weight → destination. Only loads passing all filters are ranked. Effective rate = price ÷ (deadhead to origin + loaded miles + deadhead home) using haversine straight-line distance for all three legs.

## Incomplete Rows

**L06** — rejected at equipment check (Van trailer). Missing price and overweight are noted but irrelevant since equipment already disqualifies it.  
**L07** — destination missing. Ran geometric budget analysis from both driver positions. From Dallas: 238 + 487 = 725 mi. From San Antonio: 487 + 487 = 974 mi. Both exceed max budget of 550 mi at $2.00/mi. Load is mathematically unviable from either position — no destination search needed.

## Rejected High-Paying Load

L07 — $1,100, Hotshot, 13,400 lb. Passes equipment and weight checks but destination is missing and geometrically unviable regardless of destination. Highest eligible load by absolute price is L08 at $1,700 — ranks #2 after haversine calculation.
