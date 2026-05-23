# Milady OCR — Workflow BL / clôture / facture (COM-611)

Scoping document for the real-world BL → clôture → facture cycle observed at
HYPER INTERMARCHÉ ARGELÈS / SAS ARGEPER for supplier **POLE EMBAL (DPH)**.

This document frames the future OCR implementation. It is **not** a record of
production OCR output. The page-by-page content below was derived from macOS
Vision OCR over rendered images of a vault-only client PDF; values flagged
*OCR-uncertain* must be checked against the original before being trusted.

## Source PDF (vault-only)

- Vault path: `~/vault/email-attachments/2026-05-22/19e5005bd13f005d/pol.pdf`
- Size: 4,954,145 bytes
- Producer / creator: `SECnvtToPDF V1.0` / `TOSHIBA e-STUDIO330AC`
- Created: `2026-05-22 14:37:13 +01:00`
- Pages: 12, PDF 1.7
- Origin: forwarded by Charlotte (Service Gestion Fournisseurs Directs,
  SAS ARGEPER / INTERMARCHÉ Argelès-sur-Mer) — *"Comme convenue je t'envoie le
  bl, clôture et facture du cas vu ce matin."*

**Sensitivity:** the PDF is client evidence and stays vault-only. It must
never be committed to this repository or any other shared store. Anonymized
derivatives can be shared on a case-by-case basis, but the original scans must
not leave the vault.

## The PDF is scanned/image-only

`PyMuPDF` native text extraction returned **0 characters for all 12 pages**.
The PDF is a stitched bundle of scans/print-to-PDF images coming out of a
Toshiba MFP — there is no embedded text layer. Any field extraction therefore
requires **OCR or human visual review**; the sidecar must not pretend that a
native text path exists for documents shaped like this one.

## Workflow narrative

The PDF bundles three layers of the same purchase cycle into one file:

1. **Supplier delivery note (BL) packet** — pages 6–12. Pôle Embal prints a
   6-page BL (`n° 7/24558`, nomenclature *Emballages ménagers*) plus a
   separate 1-page BL covering the *Entretien* nomenclature (carré vaisselle,
   récureurs). Both BL packets reference the same `Cde n° 235531` and ship via
   XPO LOGISTICS MESSAGERIE, quai 12, delivered on `18/05/2026`.
2. **Internal closure / recap (clôture)** — pages 4–5. After the delivery is
   received at the PDV (ARGEPER 06822), the store prints, on
   `mar. 19/05/2026 - 09:17:44`, (a) a per-nomenclature BL recap totalling
   `1306,80 €` HT against nomenclature `40 48 4804 EMBALLAGES / EPONGES` and
   (b) a full closure detail page with quantities, achat/vente, marge —
   matching the invoice totals to the centime.
3. **Supplier invoice (facture)** — pages 1–3. Pôle Embal issues invoice
   `26011401 RI` dated `18/05/2026`, payable by virement DOM at 45 jours fin
   de mois (échéance `30/06/2026`), total HT `1 306,80 €`, TVA 20 %
   `261,36 €`, TTC `1 568,16 €`. The invoice cross-references `Cde n° 235531`
   and `N° BL 724558` (note: the BL number is rendered `724558` on the invoice
   and `7 / 24558` on the BL itself — same number, different formatting).

The OCR sidecar must be able to recognize these three roles even when the
operator forwards the whole PDF as one upload: pages 1–3 feed the *facture*
flow, page 4–5 are local control evidence (no native Milady write target
today), pages 6–12 belong to the *commande* / BL flow and must be reconciled
back to `commandes.num_cmd = 235531` and `commandes.num_bl = 7/24558`.

## Page-by-page map

The supplier invoice arrives in *reverse* page order in this PDF — page 1 of
the PDF is page 3/3 of the invoice. Page numbering below refers to the PDF.

### Pages 1–3 — Supplier invoice (Pôle Embal)

| PDF page | Role | Key fields (OCR) |
|---|---|---|
| 1 | Invoice page **3/3** — totals + payment terms | N° doc `26011401 RI`; N° cmd fournisseur `26712826 SO`; date facture `18/05/2026`; date expédition `12/05/2026`; date livraison `18/05/2026`; client `HYPER INTERMARCHE ARGELES / MER-ARGEPER`, code `921200`; BL `724558 /`; ref `Cde n° 235531`; HT `1 306,80`; TVA 20 % `261,36`; TTC `1 568,16`; échéance `30/06/2026` (virement DOM, 45 j fin de mois). Sample lines: `NI512033 CARRE VAISSELLE x6` (20 UC, net 1,420, HT 28,40); `NI508412 RECUREUR METALLIQUE BRILLINOX X3` (20 UC, net 1,150, HT 23,00). |
| 2 | Invoice page **2/3** — middle of line table | Same header (`26011401 RI`, `Cde n° 235531`, BL `724558 /`). Rayon `EMB`. Lines `PHT50CH` (48 UC, HT 71,04), `PRE100CH` (15 UC, HT 32,85), `PST100CH` (15 UC, HT 22,35), `PST30CH` (18 UC, HT 22,32), `PST50CH` (28 UC, HT 34,72). Running subtotal `1 255,40`. |
| 3 | Invoice page **1/3** — top of line table | Same header. Rayon `EMB`. Lines include `PEST10035` (20 UC, HT 49,80), `ALU20MCH` (48 UC, HT 80,64), `FIL30MCH` (24 UC, HT 23,76), `PSB10CH` (60 UC, HT 59,40), `PSB15CH` (30 UC, HT 34,50), `ALU8MCH` (24 UC, HT 26,16, OCR-uncertain on the code), `BALU05SM/1SM/2SM` (HT 11,88 / 17,40 / 26,88), `CONZIP3FCH` (14 UC, HT 34,86), plus `PEST13035`, `PEST16040`, `CONZIP3CH`, `FIL20MCH`, `PCU20CH`, `PCU30CH`, `PCU50CH`, `PCUR50CH`. TVA constant 20 %. |

### Pages 4–5 — Internal closure / recap (ARGEPER)

| PDF page | Role | Key fields (OCR) |
|---|---|---|
| 4 | Récap BL par nomenclature (1/1) | Printed `mar. 19/05/2026 - 09:17:44`, `ARGEPER : 06822`. Commande `235531`. Fournisseur `POLE EMBAL (DPH)`. Nomenclature `40 48 4804 EMBALLAGES / EPONGES`, taux 20 %, total `1306,800`. Overall total `1306,800`. Single-line aggregate used by the PDV as the closure control. |
| 5 | BON DE LIVRAISON N°235531 — internal detail (1/1) | Printed `mar. 19/05/2026 - 09:17:44`, `ARGEPER : 06822` (Route de Perpignan, 66700 Argelès-sur-Mer, tél. 04-68-82-64-00). Date cmd `11/05/2026`; date livraison `12/05/2026`. Fournisseur `POLE EMBAL (DPH)` (BP 10, 44140 Montbert), code fournisseur `40130733`, tél FRS `0251705436`. Line table with `Code ITM8`, EAN, réf fournisseur, libellé, TVA, qté livrée, prix achat, prix vente, valeur HT, marge %. Examples: `NI512033 / 5410721552569` qty 20, achat 1,420, vente 2,84, HT 28,400, marge 33,33 %; `PEST10035 / 3434030000889` qty 20, achat 2,490, vente 5,06, HT 49,800. Totals: brut HT `1306,80`, remise `0,00`, net HT `1306,80`, TVA `261,36`, TTC `1568,16`, marge `886,31` (33,68 %). Nombre de colis `45,40` (OCR-uncertain — value/label coupling shaky in the summary block). |

### Pages 6–11 — Supplier BL packet (Pôle Embal, nomenclature *Emballages ménagers*)

All six pages share the same BL header: `BL n° 7 / 24558`, expéditeur Pôle
Embal (12 LA CHARRIE), destinataire HYPER INTERMARCHE ARGELES / ME `921200`
(Route de Perpignan, 66700), `Cde n° 235531`, date livraison `18/05/2026`,
transporteur `XPO LOGISTICS MESSAGERIE`, quai `12`, footer
`édité le 12/05/2026 à 06:10:33 par MBEAU`. Shipment IDs visible on the header
include `7`, `1060177S0267/2826` and `227.178 / 191854` (OCR-uncertain).

| PDF page | Role | Key fields (OCR) |
|---|---|---|
| 6 | BL 1/6 — *Emballages ménagers* | Poids `218,620 KG`, volume `611,980 DM3`. Lines `PEST10035 / 3434030000889` (PCB 10, 2 colis, total 20), `PEST13035 / 3434030000902` (PCB 5, 1 colis, total 5), `PEST16040 / 3434030000919` (PCB 5, 1 colis, total 5). |
| 7 | BL 2/6 | Lines `PSB10CH / 3434030045965`, `PSB15CH / 3434030045972`, `PST30CH / 3434030046009`, `PST50CH / 3434030046016`, `PST100CH / 3434030046023`, `PRE100CH / 3434030046054` — quantities 60, 30, 18, 28, 15, 15. |
| 8 | BL 3/6 | Lines `PCU20CH / 3434030046085`, `PCU30CH / 3434030046092` (OCR sometimes `PCU3OCH`), `PCU50CH / 3434030046115`, `PCUR50CH / 3434030046139`, `PHT30CH / 3434030046238` — quantities 84, 75, 70, 48, 24. |
| 9 | BL 4/6 | Lines `PHT50CH / 3434030046245`, `FIL20MCH / 3434030046528`, `ALU8MCH / 3434030314108` (OCR `ALUSMCH`), `BALU05SM / 3434030317000`, `BALU1SM / 3434030317109`, `BALU2SM / 3434030317307` — quantities 48, 48, 24, 12, 12, 12. |
| 10 | BL 5/6 | Lines `CONZIP3FCH / 3434030603509`, `CONZIP1CH / 3434030618220` (OCR `CONZIPICH`), `CONZIP3CH / 3434030620322`, `ALU20MCH / 3434030901629`, `FIL30MCH / 3434032386301` — quantities 14, 24, 72, 48, 24; total quantity visible `845`. Start of the *Liste des supports* (support code `269.334`). |
| 11 | BL 6/6 — supports only | Type `P01 PALETTE DEMI-LOURDE 80x120`; dimensions `120,00 x …` (truncated/OCR-uncertain); nombre `1`; total `1`. Footer reaffirms BL `7/24558`. |

### Page 12 — Separate supplier BL (Pôle Embal, nomenclature *Entretien*)

Standalone BL, 1/1, same `BL n° 7/24558` and `Cde n° 235531`, livré le
`18/05/2026`, transporteur `XPO LOGISTICS MESSAGERIE`, quai `12`. Ray
*Entretien*. Poids `3,780 KG`, volume `25,660 DM3`. Lines `NI508412 /
5410721289588` *3 récureur métallique Brillinox X3* (total 20) and `NI512033
/ 5410721552569` *Carré vaisselle x6* (total 20); total visible `40`. Support
`P01 PALETTE DEMI-LOURDE 80x120`, `80,00 x 120,00 x 15,00`, 1 × 1. Footer
`édité le 12/05/2026 à 06:10:38 par MBEAU`.

## Candidate field mapping (PDF → OCR output → Milady schema)

The sidecar today exposes `OcrResult` (facture) and `CommandeOcrResult`
(commande) in `src/models.py`, plus per-line `OcrLineItem` / `CommandeLineItem`.
Mapping below uses those existing fields where possible and flags everything
else as backlog work.

### Supplier and PDV identity

| PDF source | OCR field | Milady column | Notes |
|---|---|---|---|
| Supplier block (`Pôle Embal`, BP 10, 44140 Montbert) | `supplier_name` → `supplier_match.id_f` (commande) / `supplier_matched_id` (facture) | `fournisseurs.id_f` | Resolved through the existing `SupplierCandidate` fuzzy match scoped per PDV. |
| Supplier code on internal BL (`fournisseur 40130733`, `tél FRS 0251705436`) | not currently extracted | could harden `fournisseurs.id_f` match | Backlog: pass these as extra match keys to short-circuit fuzz on noisy supplier names. |
| Client / livré-à block (`HYPER INTERMARCHE ARGELES / MER-ARGEPER`, code `921200`, Route de Perpignan, 66700) | implicit (request scoped by `id_pdv`) | `points_de_vente.id_pdv` | The request already carries `id_pdv`; the PDV string/code on the document should be checked against the request to flag mis-routed uploads. |
| ARGEPER local site stamp (`ARGEPER : 06822`) on closure pages | not extracted | none in current schema | Useful as evidence/notes only. |

### Order / BL / invoice references

| PDF source | OCR field | Milady column | Notes |
|---|---|---|---|
| `Cde n° 235531` (on BL, recap, invoice) | `CommandeOcrResult.num_cmd` | `commandes.num_cmd` | Same identifier across all three layers — the join key. |
| `BL n° 7 / 24558` on supplier BL, rendered `724558 /` on invoice | `CommandeOcrResult.num_bl` | `commandes.num_bl` | Normalize whitespace / slash punctuation before storage. OCR-uncertain on the invoice rendering. |
| Invoice `N° document 26011401 RI` | `OcrResult.num_fact` | `factures.num_fact` | Preserve the trailing ` RI` suffix in storage to keep the supplier reference round-trippable. |
| Invoice `N° commande 26712826 SO` (Pôle Embal internal SO) | not currently extracted | could go into `factures.notes` or `factures.justif` | Supplier-side order number ≠ Milady `num_cmd`. Backlog: capture as a secondary reference. |
| Cross-reference from facture back to commande (`Cde n° 235531` printed on invoice) | (implicit during reconciliation) | `factures.id_cmd` | Drives the matching to the existing commande row. |

### Dates

| PDF source | OCR field | Milady column | Notes |
|---|---|---|---|
| `Date de commande 11/05/2026` (internal BL) | `CommandeOcrResult.date_cmd` | `commandes.date_cmd` | Internal order date. |
| `Date livraison 12/05/2026` (internal BL) / `18/05/2026` (supplier BL & invoice) | not in current model | no dedicated column | Backlog: add `date_livraison` and `date_expedition`; until then store as `notes`/`justif`. The 12/05 vs 18/05 mismatch is the *expédition* vs *livraison promise*, not an error. |
| `Date facture 18/05/2026` | `OcrResult.date_fact` | `factures.date_fact` | |
| `Échéance 30/06/2026` | not extracted | no dedicated column | Backlog: useful for cashflow forecasting, store as note for now. |

### Amounts

| PDF source | OCR field | Milady column | Notes |
|---|---|---|---|
| Facture totals: HT `1 306,80`, TVA `261,36`, TTC `1 568,16` | `OcrResult.total_ht` / `total_ttc` / `tva_rate` | `factures.total_ht` (+ derived) | Existing facture model already covers HT, TTC, TVA rate (20). |
| Commande total HT (recap nomenclature `1 306,80`) | `CommandeOcrResult.total_ht` | `commandes.total_ht` | Recap page is the cleanest source for `total_ht` because it is typeset rather than scanned. |
| Internal closure marge HT `886,31` (33,68 %) | not extracted | none | Backlog / non-goal: margin is computed from achat/vente, not stored as OCR output. |
| Per-line `HT`, `qté`, `prix net` | `OcrLineItem` / `CommandeLineItem.{qty,unit_price,total_ht}` | future `commande_lines` / `facture_lines` | No DB table for line items today — sidecar already returns them, persistence is downstream. |

### Closure / nomenclature evidence (pages 4–5)

| PDF source | OCR field | Milady column | Notes |
|---|---|---|---|
| Nomenclature code `40 48 4804 EMBALLAGES / EPONGES` | not extracted | no direct column | Local PDV control. Best stored as evidence/notes; not a required OCR target. |
| Per-line `prix achat`, `prix vente`, `marge %` (internal BL) | not extracted | none | Out of scope for OCR — PDV already has these values from its own system. |
| Internal BL number `N°235531` (matches `num_cmd`) | reuse `num_cmd` | `commandes.num_cmd` | The internal BL re-prints the commande number as its own header — not a separate identifier. |

### Line items (future extraction targets)

The supplier BL packet (pages 6–12) and the invoice (pages 1–3) cover the same
~25 lines under slightly different SKU codings (`PEST10035`, `ALU20MCH`,
`NI512033`, …) with EAN/GENCOD on both. The pair `supplier code + EAN` is the
only reliable join between BL lines and invoice lines, because designations
are abbreviated and quantities are sometimes given in UC (units commerciales)
vs. PCB (par carton). Persisting line items in Milady is **out of scope for
COM-611**; documenting that they exist and are matchable is the deliverable.

## Implementation backlog / pricing notes

The current sidecar (see `src/ocr.py`, `src/main.py`) is single-page-PDF /
single-document oriented. Handling a real-world bundle like this PDF requires
the following work:

1. **Multi-page PDF support.** `OcrWorker._load_image_b64` uses
   `convert_from_path(..., first_page=1, last_page=1)`. The worker must
   render *all* pages and either send a multi-image request or call the
   vision endpoint per page and reconcile.
2. **Page-role classification.** Before extraction, classify each page as
   *facture*, *clôture / recap*, *internal BL*, or *supplier BL*. The current
   `doc_type` parameter is set per upload; a bundled PDF needs per-page
   routing or a wrapper step that splits the PDF before queuing.
3. **Per-page reconciliation.** Once classified, group pages by role and
   stitch them into a single OCR result: one facture (multi-page), one
   commande (with line items collected across BL pages), with `num_cmd`
   acting as the join key.
4. **Robust supplier matching with `fournisseurs`.** Today the candidate list
   is passed in by the caller; for production we will want a server-side
   lookup that already filters by `id_pdv` and exposes EAN-based fallbacks
   when the supplier string is noisy (e.g. `POLE EMBAL (DPH)` vs `Pôle Embal`).
5. **Confidence / warnings on a per-field, per-page basis.** The OCR readings
   in this PDF are reliable for headers and totals but shaky on item codes
   (`ALU8MCH` vs `ALUSMCH`, `PCU30CH` vs `PCU3OCH`, `CONZIP1CH` vs
   `CONZIPICH`). Per-field confidence should drive the human review flag
   instead of an overall document-level number.
6. **Human review screen.** Even with strong OCR, the reconciliation between
   BL line quantities (UC vs PCB) and invoice line quantities needs a
   per-line confirmation UI. This is the right place to surface mismatches,
   missing dates, and supplier match uncertainty.
7. **Schema extensions (out of repo).** Useful additions, deferred to Milady
   migrations: `commandes.date_livraison`, `commandes.date_expedition`,
   `factures.date_echeance`, `factures.num_cmd_fournisseur`, plus optional
   `commande_lines` / `facture_lines` tables if line-item persistence becomes
   a product requirement.

## Non-goals (COM-611)

- No production OCR accuracy claim. Quoted values are macOS Vision OCR
  readings and need to be cross-checked against the original scans.
- No source PDF committed. The PDF stays in `~/vault/email-attachments/` and
  must never be checked into git.
- No code changes to `src/`. COM-611 is documentation only — runtime
  changes (multi-page support, page routing, schema work) are tracked in the
  backlog above and will be scoped/priced separately.
- No assumption of a native PDF text layer. The sidecar must continue to
  treat documents like this as image-only and route them through OCR.
