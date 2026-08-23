Eraser Architecture : Code Diagram

direction right

// FINAL — Enterprise Multimodal RAG Ingestion Architecture
// Legend: [BUY] = Composio / LlamaIndex / managed service · [BUILD] = your code

title FINAL — Enterprise RAG Ingestion Pipeline (1M docs)

Whole RAG Ingestion System [color: blue] {

  "Module 1 — Connectors & Raw Storage" [color: yellow] {
    Data Sources [color: gray] {
      User Uploads [icon: upload, label: "User Uploads\n(Files, Local)"]
      Emails [icon: mail, label: "Emails\n(Gmail, Outlook)"]
      Google Drive [icon: hard-drive, label: "GDrive Sync"]
      Slack [icon: message-square, label: "Slack\n(Channels, DMs)"]
      Notion [icon: book, label: "Notion\n(Pages, DBs)"]
      Zoom [icon: video, label: "Zoom\n(Transcripts, Video)"]
    }

    Composio Layer [color: teal] {
      Composio [icon: share-2, color: teal, label: "[BUY] Composio\n100+ connectors, OAuth vault\ntriggers: create / update\n(+ delete & ACL when available)"]
    }

    "Security & Raw Storage [BUILD]" [color: blue] {
      Security Scanner [icon: shield, color: red, label: "Malware & DLP Scanner\nClamAV + size limits\nComposio output = untrusted input"]
      Raw Store [icon: hard-drive, color: purple, shape: cylinder, label: "[BUY] S3 / GCS / R2\nImmutable, versioned, KMS"]
      Canonical DB [icon: database, color: purple, shape: cylinder, label: "[BUILD] Canonical & ACL DB\nPostgres: documents table\nACL snapshot + lineage"]
    }

    "Parsing Layer" [color: blue] {
      MIME Router [icon: git-branch, color: blue, label: "[BUILD] MIME Router\ncheap files → basic parsers\ncomplex PDFs → LlamaParse\naudio/video → media queue"]
      LlamaParse [icon: file-code, color: teal, label: "[BUY] LlamaParse +\nLlamaIndex readers\n(behind ParserService wrapper)"]
      Media Queue [icon: list, color: orange, shape: cylinder, label: "[BUILD] Media Jobs Queue\nRedis + BullMQ/Celery"]
      Transcription Workers [icon: film, color: blue, label: "[BUY] Whisper via\nGroq / Deepgram API\nasync long-running pool"]
      Parse Failure Store [icon: alert-circle, color: red, shape: cylinder, label: "[BUILD] Parse Failure Store\ncorrupt / unsupported / locked"]
    }

    "Deletion, ACL & Reconciliation [BUILD]" [color: red] {
      Deletion Handler [icon: trash-2, color: red, label: "Deletion Handler\ntombstones + GDPR erasure\ncascades to ALL stores"]
      ACL Sync [icon: refresh-cw, color: red, label: "ACL Sync Service\npatches acl[] on live chunks"]
      Reconciliation [icon: search, color: red, label: "Reconciliation Sweeper\nperiodic re-list source vs Canonical DB\ncatches missed deletes & ACL drift\n(because webhooks lie)"]
    }
  }

  "Module 2 — Memory Gatekeeper [BUILD]" [color: orange] {
    Staging Queue [icon: list, color: orange, shape: cylinder, label: "Staging Queue\nRedis + BullMQ/Celery\nFIFO load-leveled"]

    "Gatekeeper Engine" [color: orange] {
      Category Router [icon: git-branch, label: "Category Router\nN payload categories (config-driven)"]
      Lexical Checker [icon: activity, label: "Lexical & Entropy Checker\nShannon entropy & density"]
      Semantic Scorer [icon: shield-check, label: "Semantic Scorer\nversioned utility models\nlaunch in LOG-ONLY mode first"]
      Audit Logger [icon: file-text, label: "Audit Logger\nlogs EVERY stage decision\n+ policy versions"]
    }

    Rejected Store [icon: x-circle, color: gray, shape: cylinder, label: "Rejected Store\nconfident filter-outs, TTL expiry"]
    Quarantine Store [icon: alert-circle, color: red, shape: cylinder, label: "Quarantine Queue\nerrors / low confidence\nhuman review + replay"]
  }

  "Module 3 — Batch Ingestion Pipeline [BUILD]" [color: green] {
    Ingestion Queue [icon: list, color: orange, shape: cylinder, label: "Ingestion Queue\nRedis + BullMQ/Celery\nfair tenant scheduler"]

    "Worker Processing Core (Docker workers)" [color: green] {
      Loader [icon: play, color: green, label: "Batch Loader\nPostgres lease: SELECT FOR UPDATE\nSKIP LOCKED + heartbeat"]
      Chunker [icon: scissors, color: green, label: "[BUY inside BUILD]\nLlamaIndex node parsers\n(hierarchical parent/child)\nattaches tenant_id + acl[]"]
      Delta Checker [icon: check-square, color: green, label: "Delta Checker\nchunk-level composite hash\nREADS prior hashes"]
      Embedding Queue [icon: list, color: orange, shape: cylinder, label: "Embedding Queue\nauto-scales workers on queue age"]
      Embedding Workers [icon: cpu, color: green, label: "Embedding Workers\nOpenAI Batch API (50% off)\ntoken-aware rate limiter"]
      Bulk Writer [icon: upload, color: green, label: "Bulk Writer\nidempotent upsert\nkey: doc_id + chunk_index"]
      DLQ [icon: alert-triangle, color: red, shape: cylinder, label: "Dead Letter Queue\ninfra failures, replay support"]
    }

    "State & Storage" [color: purple] {
      Checkpoint Store [icon: save, color: purple, shape: cylinder, label: "[BUILD] Checkpoint Store\nPostgres: checkpoints table\npending/processing/done/failed"]
      Versioned Hash DB [icon: key, color: purple, shape: cylinder, label: "[BUILD] Hash DB\nPostgres: chunk_hashes table\nwritten POST-Mongo success"]
      MongoDB [icon: mongodb, color: teal, label: "[BUY] MongoDB Atlas M30+\nchunks + vectors + tenant_id + acl[]\nscalar quantization ON"]
      Vector Index [icon: sitemap, color: purple, label: "Vector Index (HNSW)\ndefined once, auto-updates\npre-filter: tenant_id, source_id"]
    }
  }

  Observability [color: gray] {
    Metrics [icon: bar-chart, color: gray, label: "[BUY] Grafana + Sentry\nqueue depth · queue age\nworker throughput · DLQ count"]
  }
}

// ── Sources → Composio ──
User Uploads > Composio: file payload
Emails > Composio: webhooks
Google Drive > Composio: sync events
Slack > Composio: webhooks
Notion > Composio: API sync
Zoom > Composio: webhooks

// ── Composio → Security → Storage ──
Composio > Security Scanner: create/update streams
Security Scanner > Raw Store: save immutable raw
Security Scanner > Canonical DB: record ACL & lineage

// ── Parsing ──
Raw Store > MIME Router: raw bytes
MIME Router > LlamaParse: complex docs
MIME Router > Media Queue: audio / video
Media Queue > Transcription Workers: transcription jobs
LlamaParse > Staging Queue: normalized text event
Transcription Workers > Staging Queue: transcript event
LlamaParse > Parse Failure Store: corrupt / unsupported
Transcription Workers > Parse Failure Store: failed media

// ── Deletion / ACL / Reconciliation ──
Composio > Deletion Handler: delete events (when emitted)
Composio > ACL Sync: permission events (when emitted)
Reconciliation > Composio: periodic re-list via actions
Reconciliation > Deletion Handler: missed deletions found
Reconciliation > ACL Sync: ACL drift found
Deletion Handler > MongoDB: delete chunks by doc_id
Deletion Handler > Raw Store: tombstone raw object
Deletion Handler > Versioned Hash DB: purge hashes
Deletion Handler > Canonical DB: mark deleted, keep lineage
ACL Sync > Canonical DB: update ACL snapshot
ACL Sync > MongoDB: patch acl[] on live chunks

// ── Gatekeeper ──
Staging Queue > Category Router: pull event
Category Router > Lexical Checker: statistical checks
Lexical Checker > Semantic Scorer: passed items
Lexical Checker > Rejected Store: statistical rejects
Lexical Checker > Audit Logger: log decision
Semantic Scorer > Audit Logger: log decision
Semantic Scorer > Ingestion Queue: verified items
Semantic Scorer > Rejected Store: confident rejects
Semantic Scorer > Quarantine Store: errors / low confidence
Quarantine Store > Staging Queue: replay after human review

// ── Worker Core ──
Ingestion Queue > Loader: fair pull
Loader > Chunker: raw text
Canonical DB > Chunker: tenant_id + acl[] metadata
Chunker > Delta Checker: chunks + metadata
Versioned Hash DB > Delta Checker: prior hashes
Delta Checker > Embedding Queue: new / modified chunks only
Embedding Queue > Embedding Workers: batch jobs
Embedding Workers > Bulk Writer: vectors + metadata + acl
Bulk Writer > MongoDB: idempotent bulk upsert
Bulk Writer > Versioned Hash DB: write hash ONLY on success
MongoDB <> Vector Index: indexed automatically

// ── State loops ──
Checkpoint Store > Loader: next pending batch
Bulk Writer > Checkpoint Store: mark done
Embedding Workers > DLQ: exhausted retries
DLQ > Checkpoint Store: mark failed

// ── Backpressure ──
Embedding Queue > Loader: depth backpressure
Staging Queue > MIME Router: staging backpressure

// ── Observability taps ──
Ingestion Queue > Metrics: queue depth & age
Embedding Queue > Metrics: queue depth & age
DLQ > Metrics: failure count
Embedding Workers > Metrics: throughput