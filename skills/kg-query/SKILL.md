---
name: kg-query
description: Answer questions from the kg knowledge graph with cited sources. Use when asking what ingested documents or transcripts say about a person, project or topic, how things connect, or what recurs across documents.
---

# Query kg with citations

Every claim in your answer cites a document and a verbatim quote that a kg tool returned. The graph holds facts that an agent extracted from document chunks. The chunks hold the original text.

## 1. Orient

Call `overview` once per session. It lists the entity types and relation names, which are the exact values your SQL filters must use. The server instructions list the tables, and `query("select sql from sqlite_master")` prints the full schema.

When coverage matters, call `list_documents`. A document with `entities: 0` has not been extracted, so graph tools cannot see it. `search_text` still can.

## 2. Resolve names

`entity`, `neighbors` and `path` take an exact name or alias, matched case-insensitively. When one returns "no entity named", call `search_entities(query)`. It matches substrings of names, aliases and descriptions. Retry with the canonical name it returns.

## 3. Pick the cheapest tool

| Question | Tool |
|---|---|
| Everything about one thing | `entity(name)` returns its relations with evidence and the documents that mention it |
| How A connects to B | `path(A, B)` |
| What surrounds A | `neighbors(A)` at depth 1 first, because depth 2 can return hundreds of edges |
| Exact wording, or anything the graph lacks | `search_text` |
| Counts, rankings, lists across documents | one `query` with `group by` |

Three limits cut results:

- `entity` returns at most 100 relations with no warning. Use SQL for a hub entity.
- `query` returns at most 500 rows. Count and group in SQL instead of pulling rows to count them.
- `neighbors` stops at 300 edges and sets `truncated`.

`search_text` takes FTS5 (SQLite full-text search) syntax: `"exact phrase"`, `OR`, `NOT`, `prefix*` and `NEAR(a b, 10)`. A plain sentence falls back to matching any of its words, which ranks loosely. Widen a name search with the aliases from `entity`, such as `"Robert Smith" OR "Bob"`.

Cross-document example, for "which risks came up in more than one meeting, and who raised them":

```sql
select t.name risk, s.name raised_by, d.title, r.evidence
from relations r
join entities s on s.id = r.src join entities t on t.id = r.dst
join docs d on d.id = r.doc_id
where r.rel = 'raised' and t.type = 'risk' and t.id in (
  select entity_id from mentions group by entity_id having count(distinct doc_id) > 1)
order by t.name
```

The graph holds only what was extracted. When it returns little, run `search_text` over the original text. If the text holds facts the graph lacks, answer from the text and offer to extract them with the kg-ingest skill.

## 4. Cite

Fetch the citation fields in the same call as the facts. This query returns an entity's relations ready to cite. Use the canonical name from step 2, because SQL does not resolve aliases.

```sql
select s.name source, r.rel relation, t.name target, r.evidence,
       d.title, d.source doc_source, c.seq
from relations r
join entities s on s.id = r.src join entities t on t.id = r.dst
left join docs d on d.id = r.doc_id
left join chunks c on c.rowid = r.chunk_id
where s.name = 'Atlas' or t.name = 'Atlas'
```

Mark each claim with `[n]` and list the sources after the answer:

```
Bob owns the Atlas migration [1]. The vendor delay came up in two standups [2][3].

[1] Standup 1 (/notes/s1.txt, chunk 0): "Bob owns the Atlas migration"
[2] Standup 1 (/notes/s1.txt, chunk 0): "vendor delay is a risk"
[3] Standup 2 (/notes/s2.txt, chunk 0): "the vendor delay risk is still open"
```

Rules for each citation:

- Quote only text a tool returned: a relation's `evidence`, a mention's quote, or chunk text.
- `search_text` snippets mark hits with `[brackets]` and cut text with `…`. Strip both before quoting, or read the chunk for the full sentence.
- The extracting agent wrote the evidence, so check the quote against its chunk before citing a claim the answer depends on. Relations carry a `chunk_id`, while `read_chunks` takes a `seq`. Fetch the chunk text by `chunk_id` in SQL instead:
  ```sql
  select d.title, d.source, c.seq, c.text from chunks c join docs d on d.id = c.doc_id where c.rowid in (12, 40)
  ```
- A relation with no `doc_id` or an empty `evidence` has no source. Say that in the answer instead of citing it.
- When documents disagree, cite each side. `docs.added` records when a file was ingested, not when it was written, so it cannot tell you which document is newer.

Done when every factual sentence carries a marker and every marker resolves to a quote a tool returned.
