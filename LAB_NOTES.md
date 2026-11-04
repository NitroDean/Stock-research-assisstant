# Lab Codex 4: submission notes

## Topic

How a local AI assistant can combine US-company reports, dated market information, and financial news to evaluate a stock and identify evidence-based conditions to watch before selling.

## What the app demonstrates

1. **Named sources:** Each answer displays the retrieved PDF file names and PDF page numbers as numbered, clickable source links. The model is instructed to cite those numbers in its answer.
2. **Clickable uploads:** Click a file name to open the app's page viewer. Click a source under an answer to open the exact cited PDF page. The viewer can move between pages and download the original PDF.
3. **Local AI:** PDF text is extracted and indexed locally. `nomic-embed-text` supports semantic search; `qwen3:1.7b` writes grounded answers using retrieved passages.
4. **Four topic PDFs:** The local demo contains Apple's 2026 and 2025 Forms 10-K and 2026 Q3 and Q2 Forms 10-Q. The same files can be downloaded using `download_sample_pdfs.py`. Their official links are in `SOURCES.md`.

## Demo question

> What were Apple total net sales in fiscal 2026 compared with fiscal 2025?

The 2026 Form 10-K, PDF page 29, reports $478,834 million for 2026 and $416,161 million for 2025. The assistant's answer should cite that page. This is a historical filing comparison, not a current recommendation to buy or sell.

## Optional next step for the broader topic

The code is published in the public GitHub repository. To extend the research beyond company filings, add a current, dated market snapshot and a financial news PDF you are allowed to use. The four loaded PDFs meet the lab's 4-5 PDF count, but they do not provide live prices or independent news.
