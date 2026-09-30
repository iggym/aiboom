# Risk rules

This page is **generated** from `src/aibom/risk/rules/capabilities.yaml` and
`src/aibom/risk/rules/mcp-packages.yaml`. It cannot drift from the code that
runs: `make docs-check` fails if the committed file differs.

Every verdict `aibom` prints is reproducible. Run
`aibom explain-risk <tool>` (or `aibom explain-risk <mcp-server>`) to see the
rule ids that fired, the field they matched, and the evidence.

## How classification works

For each tool and MCP server, `aibom` builds a *haystack*:

| Field | Source |
| --- | --- |
| `identifier` | the tool/server name, split on case, `_`, `.` and `-` |
| `description` | the docstring / declared description |
| `parameters` | the parameter names of the tool function |
| `command` | an MCP server's command + args |
| `package` | an MCP server's npm/PyPI package name |

A rule declares one or more field regexes. By default the rule fires when **any**
declared field matches — the fields are alternative sources of the same evidence
(a `path` parameter *or* a `file`-ish name both mean filesystem access). A rule
that sets `match: all` requires **every** declared field to match, which is for
rules where one field qualifies the other (`bulk_*` is only destructive if the
description also says delete).

Rules are additive: a tool can hold several capabilities, and its risk is the
highest level among them. Curated MCP package entries act as a *floor* — they
add capabilities the name alone cannot reveal.


## Risk levels

| Capability | Level | Label |
| --- | --- | --- |
| `code-exec` | high | Code execution |
| `secrets` | high | Secrets access |
| `financial` | high | Financial |
| `destructive` | high | Destructive |
| `identity` | medium | Identity & permissions |
| `write` | medium | Write |
| `external-comms` | medium | External comms |
| `filesystem` | medium | Filesystem |
| `network` | low | Network |
| `read` | low | Read |
| `unknown` | unknown | Unknown |

## Capability rules

`rules_version: 2026.09.1`

| Rule | Capability | Risk | Match | Why |
| --- | --- | --- | --- | --- |
| `exec.shell` | code-exec | high | any | Shell command execution gives an attacker arbitrary code on the host. |
| `exec.eval` | code-exec | high | any | Dynamic evaluation executes data as code. |
| `exec.python` | code-exec | high | any | Invoking a Python interpreter or notebook kernel executes arbitrary code. |
| `exec.package-install` | code-exec | high | any | Installing packages runs arbitrary install hooks. |
| `exec.sql-raw` | code-exec | high | any | Raw SQL execution against a live database can read or destroy data. |
| `secrets.read` | secrets | high | any | Reading credentials from the environment or a vault exposes them to the model. |
| `secrets.env` | secrets | high | any | Environment variables commonly hold provider keys and session tokens. |
| `secrets.rotate` | secrets | high | any | Rotating or minting credentials is a privileged identity operation. |
| `money.movement` | financial | high | any | Moving money is irreversible and directly monetisable by an attacker. |
| `money.pricing` | financial | high | any | Price manipulation affects customer billing. |
| `money.subscription` | financial | high | any | Subscription changes alter recurring revenue and entitlements. |
| `destructive.delete` | destructive | high | any | Deletion destroys data and is usually not reversible. |
| `destructive.bulk` | destructive | high | all | Bulk mutation amplifies the blast radius of a mistake. |
| `destructive.overwrite` | destructive | high | any | Overwriting replaces existing state without a copy. |
| `identity.auth` | identity | medium | any | Authentication surfaces can be abused to impersonate or escalate. |
| `identity.permission` | identity | medium | any | Changing permissions or roles is a privilege-escalation primitive. |
| `identity.user-admin` | identity | medium | all | User administration can create or take over accounts. |
| `identity.identity-provider` | identity | medium | any | Identity-provider operations affect the whole tenant. |
| `write.mutation` | write | medium | any | Writing changes state the system or a third party depends on. |
| `write.issue-tracker` | write | medium | all | Filing or editing tickets is a durable, externally visible write. |
| `write.document` | write | medium | all | Document edits are durable writes into shared knowledge stores. |
| `write.calendar` | write | medium | any | Scheduling writes affect other people's calendars. |
| `comms.email` | external-comms | medium | any | Outbound email leaves the trust boundary and is hard to recall. |
| `comms.chat` | external-comms | medium | any | Chat messages reach humans directly and can be socially engineered. |
| `comms.webhook` | external-comms | medium | any | Webhooks push data to endpoints outside the system's control. |
| `comms.social` | external-comms | medium | any | Public posting is an unrecallable external communication. |
| `comms.voice` | external-comms | medium | any | Voice/TTS output is a direct external communication channel. |
| `fs.access` | filesystem | medium | any | Filesystem access reaches everything the process can read or write. |
| `fs.attachment` | filesystem | medium | any | Attachments are attacker-controlled files that may be parsed or executed. |
| `fs.config` | filesystem | medium | any | Editing configuration can change runtime behaviour. |
| `net.http` | network | low | any | Outbound HTTP reaches endpoints outside the trust boundary. |
| `net.dns` | network | low | any | Name resolution and raw sockets can be used for exfiltration. |
| `net.browse` | network | low | any | Browsing fetches arbitrary remote content into the model's context. |
| `read.query` | read | low | any | Reading exposes data to the model and its logs. |
| `read.knowledge` | read | low | any | Knowledge-base reads surface internal content into prompts. |

## Curated MCP packages

`registry_version: 2026.09.1` — 59 packages.

These entries supply capabilities the server *name* cannot reveal (a
`server-github` is a write + identity surface regardless of what its
description says). They are a floor: the classifier still runs the rules
above on top of them.

| Package | Capabilities | Risk | Why |
| --- | --- | --- | --- |
| `@modelcontextprotocol/server-aws-kb-retrieval` | read, network | low | Read-only Bedrock knowledge-base retrieval. |
| `@modelcontextprotocol/server-bigquery` | read, secrets, network | high | Read-only warehouse access with a service account. |
| `@modelcontextprotocol/server-brave-search` | network, read | low | Read-only web search via an API key. |
| `@modelcontextprotocol/server-chrome-devtools` | network, code-exec, secrets | high | DevTools protocol access to a live browser profile, including cookies. |
| `@modelcontextprotocol/server-clickhouse` | read, destructive, network | high | Analytical queries, including table drops. |
| `@modelcontextprotocol/server-cloudflare` | write, identity, network | medium | Edge configuration changes affect every request. |
| `@modelcontextprotocol/server-confluence` | write, read, identity | medium | Space and page mutation. |
| `@modelcontextprotocol/server-discord` | external-comms, write, identity | medium | Posts and moderates in a live community. |
| `@modelcontextprotocol/server-docker` | code-exec, destructive, identity | high | Container control is equivalent to root on the host. |
| `@modelcontextprotocol/server-duckdb` | read, filesystem | medium | Local analytical queries over arbitrary files. |
| `@modelcontextprotocol/server-elasticsearch` | read, write, destructive, network | high | Index mutation and deletion. |
| `@modelcontextprotocol/server-everything` | unknown | unknown | Test server exercising every primitive; treat as opaque. |
| `@modelcontextprotocol/server-fetch` | network, read, filesystem | medium | Fetches arbitrary URLs, including localhost and link-local addresses. |
| `@modelcontextprotocol/server-filesystem` | filesystem, read, write | medium | Reads and writes arbitrary paths the process can reach. |
| `@modelcontextprotocol/server-firebase` | read, write, destructive, secrets | high | Database and auth administration with a service key. |
| `@modelcontextprotocol/server-gdrive` | read, filesystem, network | medium | Reads the whole Drive corpus the token can see. |
| `@modelcontextprotocol/server-git` | read, write, filesystem | medium | Local repository manipulation; can rewrite history. |
| `@modelcontextprotocol/server-github` | write, identity, read, network | medium | Can create issues, comments, branches and PRs with the caller's token. |
| `@modelcontextprotocol/server-github-actions` | write, identity, code-exec | high | Can trigger and cancel workflows, which is a code-execution path. |
| `@modelcontextprotocol/server-gitlab` | write, identity, read, network | medium | Repository write access with the caller's token. |
| `@modelcontextprotocol/server-google-maps` | network, read | low | Read-only geocoding and routing lookups. |
| `@modelcontextprotocol/server-google-workspace` | identity, read, write, external-comms | medium | Mail, calendar and Drive access for a whole domain. |
| `@modelcontextprotocol/server-grafana` | read, network, identity | medium | Dashboard and datasource queries with a service token. |
| `@modelcontextprotocol/server-hubspot` | read, write, identity | medium | CRM contact and deal mutation. |
| `@modelcontextprotocol/server-jira` | write, read, identity | medium | Issue and project mutation with the caller's token. |
| `@modelcontextprotocol/server-jupyter` | code-exec, filesystem, network | high | Executes notebook cells against a live kernel. |
| `@modelcontextprotocol/server-kubernetes` | write, identity, code-exec, destructive | high | Cluster control plane access; can exec into pods and delete workloads. |
| `@modelcontextprotocol/server-linear` | write, read, identity | medium | Issue tracker mutation. |
| `@modelcontextprotocol/server-memory` | read, write, filesystem | medium | Persistent knowledge-graph store written to disk. |
| `@modelcontextprotocol/server-microsoft-graph` | identity, read, write, external-comms | medium | Tenant-wide directory and mail access. |
| `@modelcontextprotocol/server-mongodb` | read, write, destructive, network | high | Document mutation and collection drops. |
| `@modelcontextprotocol/server-mysql` | read, write, destructive, secrets | high | Arbitrary SQL against a live database. |
| `@modelcontextprotocol/server-notion` | write, read, identity | medium | Reads and writes the workspace knowledge base. |
| `@modelcontextprotocol/server-obsidian` | filesystem, read, write | medium | Reads and writes a local notes vault. |
| `@modelcontextprotocol/server-playwright` | network, code-exec, filesystem | high | Browser automation with script execution. |
| `@modelcontextprotocol/server-postgres` | read, write, destructive, secrets | high | Arbitrary SQL against a live database, including DDL. |
| `@modelcontextprotocol/server-prometheus` | read, network | low | Read-only metrics queries. |
| `@modelcontextprotocol/server-puppeteer` | network, code-exec, filesystem | high | Drives a real browser; can execute page scripts and read the DOM. |
| `@modelcontextprotocol/server-python` | code-exec, filesystem | high | Executes arbitrary Python in the host environment. |
| `@modelcontextprotocol/server-redis` | read, write, destructive, network | high | Arbitrary key mutation, including FLUSHALL. |
| `@modelcontextprotocol/server-salesforce` | read, write, financial, identity | high | CRM mutation including customer and contract data. |
| `@modelcontextprotocol/server-screenshot` | filesystem, network, read | medium | Captures the screen, which may include sensitive windows. |
| `@modelcontextprotocol/server-sendgrid` | external-comms, read | medium | Sends email on behalf of the organisation. |
| `@modelcontextprotocol/server-sentry` | read, network | low | Read-only access to error events. |
| `@modelcontextprotocol/server-sentry-issues` | read, write, network | medium | Can resolve and assign issues in addition to reading. |
| `@modelcontextprotocol/server-sequential-thinking` | read | low | Local reasoning scratchpad; no external effects. |
| `@modelcontextprotocol/server-shell` | code-exec, filesystem, destructive | high | Direct shell execution. |
| `@modelcontextprotocol/server-slack` | external-comms, read, write, identity | medium | Reads channels and posts as the workspace's bot identity. |
| `@modelcontextprotocol/server-snowflake` | read, secrets, network | high | Warehouse queries with a privileged credential. |
| `@modelcontextprotocol/server-sqlite` | read, write, destructive, filesystem | high | Arbitrary SQL against a local database file. |
| `@modelcontextprotocol/server-ssh` | code-exec, identity, network | high | Remote shell over SSH. |
| `@modelcontextprotocol/server-stripe` | financial, read, identity | high | Payment and refund operations against a live account. |
| `@modelcontextprotocol/server-supabase` | read, write, destructive, secrets | high | Database and auth administration with a service key. |
| `@modelcontextprotocol/server-telegram` | external-comms, write, identity | medium | Posts and reads messages as the bot. |
| `@modelcontextprotocol/server-terraform` | code-exec, destructive, identity | high | Applies infrastructure changes; can destroy resources. |
| `@modelcontextprotocol/server-time` | read | low | Timezone and clock lookups only. |
| `@modelcontextprotocol/server-timezone` | read | low | Timezone lookups only. |
| `@modelcontextprotocol/server-twilio` | external-comms, financial, identity | high | Sends SMS and voice calls at real cost. |
| `@modelcontextprotocol/server-vercel` | write, identity, network, code-exec | high | Deployment control; can ship code to production. |
