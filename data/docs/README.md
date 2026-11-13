# Scheme documents (knowledge base for RAG)

Every file in this folder is loaded by `scripts/ingest_docs.py` into the vector database
(`chroma_db/`). The agent searches it to suggest schemes, loans and licences with sources.

## Supported files
- `.md` / `.txt`: start with a YAML front-matter block (see any starter doc):
  ```
  ---
  scheme: PM Mudra Yojana
  category: loan            # loan | subsidy | registration | license | tax
  suitable_for: [street vendor, food business, manufacturing, services, women, sc_st, any]
  source_url: https://...   # the official page the facts came from
  last_verified: 2026-11-13
  ---
  ```
- `.pdf`: official PDFs (scheme guidelines, FAQs). No front-matter is possible, so the scheme name
  is taken from the file name: `pm_svanidhi_guidelines.pdf` -> "Pm Svanidhi Guidelines".
  Name PDFs clearly, e.g. `pmegp_guidelines_2024.pdf`.

## Adding official PDFs
1. Download the PDF ONLY from an official site (mudra.org.in, kviconline.gov.in,
   pmsvanidhi.mohua.gov.in, standupmitra.in, udyamregistration.gov.in, fssai.gov.in, gst.gov.in,
   msme.gov.in, pib.gov.in).
2. Save it in this folder with a clear snake_case name.
3. Rebuild the index (it deletes and recreates the collection, so there are no duplicates):
   ```bash
   python scripts/ingest_docs.py
   ```
4. Check search quality did not drop:
   ```bash
   python scripts/eval_rag.py
   ```

## Rules for editing starter docs
- Every amount, limit and eligibility rule must come from an official page. Put that page in
  `source_url` and update `last_verified`.
- If you cannot verify a fact, leave it out.
- Keep the sections: What it is · Who can apply · How much / cost · Documents needed ·
  How to apply · Official link.
