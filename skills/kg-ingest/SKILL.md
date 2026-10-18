---
name: kg-ingest
description: Ingest documents into the kg knowledge graph and extract entities and relations with citable quotes. Use when adding files, folders, transcripts or text to kg, or extracting facts from documents already in it.
---

# Ingest into kg

The kg MCP server stores documents as full-text chunks. You do the extraction: read the chunks, then write entities and relations back with **provenance**, meaning the `doc_id`, the `chunk_id` and a verbatim quote. Provenance is what lets a later answer cite its source, so every fact carries it.

## 1. Load documents

- **Files or folders:** call `ingest(path, kind)` with an absolute path. One call on a folder loads every supported file under it. The `ingest` tool description lists the supported formats.
- **Any other text** (a converted PDF, output from another tool, pasted notes): call `ingest_text(title, text, kind, source)`. Set `source` to a stable id such as a URL or meeting id. Without one, a changed version lands as a second document instead of replacing the first.
- `kind` is a free label such as `transcript`, `email` or `report`. Give each batch one kind, so queries can filter on it later.

Each result carries a `status`:

- `unchanged` documents already have their facts, so skip them.
- `added` and `replaced` documents need extraction. A replace deletes the old version's facts, so use the `doc_id` from this result.

Done when you hold the list of `doc_id`s to extract. In a later session, `list_documents` rebuilds that list, because it shows `entities: 0` for every document nobody has extracted.

## 2. Load the vocabulary

Run `overview` once, then this `query`:

```sql
select e.name, e.type, group_concat(a.alias, '; ') aliases
from entities e left join aliases a on a.entity_id = e.id
group by e.id order by e.type, e.name
```

`overview` lists the entity types and relation names in use. The query lists every **canonical name** with its aliases. It stops at 500 rows, so on a big graph add `where e.type in (...)`. Reuse these names, types and relations exactly. One vocabulary query replaces a `search_entities` call per entity.

On an empty graph, pick the vocabulary from what the user wants to ask. Use a few lowercase singular types (`person`, `org`, `project`, `decision`, `risk`) and lowercase verb-phrase relations (`owns`, `works_at`, `decided`, `raised`).

Done when you know the types, relations and names you will write.

## 3. Extract one batch at a time

For each document:

1. Call `read_chunks(doc_id, start, count=20)`. A chunk is about 1,500 characters, so a short document fits in one call.
2. Extract the entities and relations in that batch.
3. Write the whole batch with one `add_facts(doc_id, entities, relations)` call.
4. Move `start` past the batch and repeat until it reaches `total_chunks`.

Writing after every batch saves the work if the session ends. To resume a half-done document, find the last chunk that has facts:

```sql
select max(c.seq) from mentions m join chunks c on c.rowid = m.chunk_id where m.doc_id = ?
```

Rules for each fact:

- `chunk_id` is the `chunk_id` field from `read_chunks`. It is a global id and differs from `seq`.
- Copy `quote` and `evidence` verbatim from that one chunk, at most a sentence. `search_text('"…"')` finds a verbatim quote and misses a paraphrase.
- List every new entity in `entities` with a `type`. A relation endpoint missing from `entities` gets created with no type.
- The first `type` and `description` written for an entity stick. Change them later with `update_entity`.
- Name each relation so `source relation target` reads as a sentence, such as `Bob owns Atlas`.
- Model a decision, risk, claim or event as an entity with a short canonical name, such as `Vendor delay`. Another document that mentions the same risk then resolves to the same entity, which is what makes cross-document questions answerable.
- Pass a `doc_id` on every `add_facts` call, because a fact without one has no source to cite. When the user states a fact directly, store it with `ingest_text` first and extract it from there.

Done when every targeted document has been read to its last chunk.

## 4. Merge duplicates

After extraction, list candidate pairs that may be one thing under two names:

```sql
select a.type, a.name name_a, b.name name_b from entities a join entities b
  on a.id < b.id and a.type is b.type
 and (b.name like '%' || a.name || '%' or a.name like '%' || b.name || '%')
```

Review each pair, because a substring match is only a hint. `merge_entities(keep, drop)` moves relations and mentions to `keep` and records `drop` as an alias. Keep the fuller name, so `Robert Smith` keeps and `Bob` drops. Pairs this query misses, such as a nickname, show up when you scan the vocabulary from step 2.

## Large corpora

If you can run subagents, give each one a set of `doc_id`s, this skill and the vocabulary from step 2. Run step 4 once after they all finish, because parallel workers can create the same entity under different names.

## Report

Tell the user the documents added, replaced and skipped, the entity and relation counts from `overview`, and the merges you made.
