# CODE INDEX SYSTEM

## Overview

A code index system for the current codebase (python-based evolix) that is exposed as an mcp that can help navigate and understand it better/more efficiently.

Some clarifications for the languages used in this spec:
- When said "manually", it means it will be done by the human. When said "semi-automatically" it means either human or llm. When said "automatically" it means mechanically by code or tool run. Similarly, semi-auto means either by llm or by code.

## Concepts

Endpoint:
A controller endpoint (API, worker/job handler, kafka consumer handler etc). The entry point of a continuous execution that is triggered by some external event.
This could be generated quite mechanically, by scanning the codebase or even static analysis. Annotations and descriptions should be added semi-manually to provide more context.
The main exploration mechanism would be starting with an endpoint, and using lsp-like tools to spread the whole flow end-to-end through the call chain (with related code comments & docstrings) for examination.
- There could be special rules to stop the traversal e.g. stopping at a level where the internal is mostly mechanical and doesn't contain much business logic.

Flow:
A collection of endpoints (and maybe some other auxilaries) that are tightly related either from the business-oriented or techincal perspective. Examples: CRUD endpoint set, oauth/login flow, tenant onboarding flow. 1 flow could be 1 endpoint if it's declarative enough, but generally multiple endpoints.
Mostly curated and define manually, with annotations/descriptions as well.

Subsystem:
A larger grouping than flows, for a enclosed module or subsystem that is self-contained and isolated enough.
Mostly curated and define manually, with annotations/descriptions as well. In fact description should be quite encompassing and involved (but mostly about describing in a complete albeit high-level way).
Descriptions for these should be like md files, not just short sentences or paragraphs.

Logic artifact:
A quirk, convention or distinctive logic in the codebase that could be representative or repeated enough, so that it should be referenced by name.
Mostly curated and define manually, with annotations/descriptions as well.

Label:
Labels tagged to endpoints/flows/logic artifacts etc for cataloging and fast lookup. Should mostly be manually managed so the label list is lean and controlled.

## Mechanism

All the above entities in Concepts will be stored as objects in db (lets go with mongodb for now).
There can be an mcp to maintain the code index itself (separated from the one for using it).

Endpoints should be auto generated semi-automatically and regularly (e.g. twice a week or maybe with every master merge). Annotations/descriptions for these are added semi-manually (mostly right after they are generated). The llm could pre-generated them and human could come in to review and edit them.

The rest as said would be maintained mostly manually, even though llm could suggests them. Almost entirely manually with subsystems, for others the llm could be asked to suggest but human will utimately decide (then llm could do the actual managing on their behalf).

Periodically (e.g. once a week) a full sweep could run to check if the existing endpoints/flows descriptions and content would still make sense, and would need any updating (this would be lenient, only stark/important changes would trigger an update, otherwise avoid unecessary changes).

(generally) 1-n relationships: Flow -> Endpoint, Subsystem -> Endpoint, Subsystem -> Flow.
- Note that even if they feel like 1-n, it doesn't have to be strictly so e.g. 1 endpoint can be in many flows.
Labels to anything else is n-n. So is Logic artifact to Endpoints, Flows and Subsystems.

Read capabilities:
- Listing: all subsystems, all logic artifacts, all labels (to see what can be queried), all flows, and all endpoints (even though generally they should be searched)
  - Can further be filtered. Except for labels, all will be indexed in a vectorized manner for semantic search.
  - Also have static filters like by labels, logic artifacts, endpoints etc
  - Can specify fields to return.

- Spread: given an endpoint, spread them recursively under a certain format. Stops at library boundaries.
  - Can let an llm do the main spreading since there could be some decision points (something like Haiku is enough). It would make heavy used of text-based tools and lsps though.

## Tech stack of the code index

Python, mongodb for persistence, pm2 for mcp server management (just need to declare config), claude code cli for llm involvement, lsp python modules.
