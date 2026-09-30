# Mapping to frameworks

**Evidence, not compliance.** This table shows which BOM fields an auditor or
governance board will find useful when they ask you about a framework. `aibom`
produces inventory and evidence. It does not decide whether your system is
lawful, and a document does not make you compliant. Read this as "where to find
the facts", not "this makes you done".

| Framework | What it asks for | BOM fields that help | Notes |
| --- | --- | --- | --- |
| **EU AI Act — Art. 13 (transparency)** | Instructions for use: intended purpose, capabilities and limitations | `system.purpose`, `safety.outputs`, `safety.integrity`; `modelCard.modelParameters`, `modelCard.considerations.useCases`, `modelCard.considerations.technicalLimitations` | The BOM states purpose and limitations per model; the *instructions* document is still yours to write. |
| **EU AI Act — technical documentation (Annex IV)** | System description, design, data, monitoring, risk management | `metadata.component` (`aibom:*`), `models` + `modelCard`, `datasets` (`governance`, `sensitiveData`), `services` (`x-trust-boundary`), `compositions` | `compositions` is the honest completeness statement Annex IV expects. |
| **EU AI Act — data governance (Art. 10)** | Training/validation data: provenance, characteristics, preparation | `datasets[].properties` (`source`, `jurisdiction`, `retention`, `consent_basis`), `data[].sensitiveData`, `data[].governance.owners` | Fill `aibom.yaml` `datasets`; scanned repos rarely reveal this. |
| **EU AI Act — record-keeping (Art. 12)** | Automatically generated logs (for high-risk systems) | Not a BOM concern past identifying the AI surface | `aibom` inventories the surface; logging is runtime and out of scope. |
| **ISO/IEC 42001 — A.5.2 (AI system inventory)** | Maintain an inventory of AI systems | The whole BOM: `metadata.component`, `components[]`, `services[]` | This is the closest one-to-one fit. |
| **ISO/IEC 42001 — A.5.3 (roles & responsibilities)** | Assign accountability, then re-verify on change | `metadata.authors`, `aibom:owners` on prompts, `dataset.governance.owners`, CODEOWNERS | `aibom diff` in CI is the "re-verify on change" loop. |
| **ISO/IEC 42001 — A.6.2.6 (third-party AI)** | Assess and monitor supplied AI | `services[]` (providers, MCP, external services), `aibom:dpa`, `aibom:region`, `aibom:data_processing_agreement` | Review note `provider.no_dpa` flags gaps. |
| **ISO/IEC 42001 — A.8.2 (data for AI)** | Data provenance and quality | `datasets[].properties`, `data[].governance`, `data[].sensitiveData` | Same declarations as Art. 10 above. |
| **NIST AI RMF — MAP 1.1/1.2** | Context, intended purpose, affected parties | `system.purpose`, `aibom:deployment`, `aibom:risk_classification`, `aibom:human_oversight` | Purpose and deployment live on the application component. |
| **NIST AI RMF — MAP 2.1/2.3** | AI system components and dependencies | `components[]`, `services[]`, `dependencies[]` | The dependency graph is the RMF "system map". |
| **NIST AI RMF — MAP 5** | Likelihood and magnitude of impacts | `aibom:risk`, `aibom:capabilities`, `aibom:blast_radius` on tools and MCP servers | Risk labels are heuristic and explainable (`aibom explain-risk`), not validated impact assessments. |
| **NIST AI RMF — GOVERN 1.6 / MANAGE 3.2** | Ongoing monitoring, third-party risk | `aibom diff` per release, `model.retirement` notes, `provider.no_dpa` | `diff --fail-on new-provider` is a cheap monitoring gate. |
| **SOC 2 / vendor questionnaires** | "List the AI vendors and models you use" | `services[]`, `components[]` (models), `AIBOM.md` tables | The Markdown report is written to be pasted into a questionnaire. |
| **CycloneDX ML-BOM** | Machine-readable AI inventory | Everything | Native format. Validate with `aibom validate`. |

## How to use this table honestly

- **Do** cite the BOM as evidence: "here is the inventory, its owners, its risk
  labels, and the digest that proves it hasn't changed."
- **Don't** claim the BOM satisfies a control on its own. An EU AI Act
  technical file, an ISO 42001 statement of applicability and an NIST AI RMF
  profile are documents a human writes and a reviewer accepts.
- **Don't** treat the heuristic risk labels as a legal classification. They are
  a starting point for the human conversation `aibom:risk_justification`
  records.

Contributions to this table are welcome — it is maintained with community PRs.
The rule for accepting an entry is that the BOM field must *actually* carry the
fact the framework asks for.
