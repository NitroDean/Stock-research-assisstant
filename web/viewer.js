const params = new URLSearchParams(location.search);
const id = params.get("id") || "";
let page = Math.max(1, Number.parseInt(params.get("page") || "1", 10) || 1);
let pages = 1;
const label = document.querySelector("#page-label");
const image = document.querySelector("#page-image");
const error = document.querySelector("#viewer-error");

function showPage() {
  page = Math.max(1, Math.min(page, pages));
  label.textContent = `PDF page ${page} of ${pages}`;
  image.alt = `PDF page ${page}`;
  image.src = `/api/documents/${encodeURIComponent(id)}/page/${page}`;
  history.replaceState(null, "", `/viewer.html?id=${encodeURIComponent(id)}&page=${page}`);
  document.querySelector("#previous").disabled = page <= 1;
  document.querySelector("#next").disabled = page >= pages;
}

document.querySelector("#previous").addEventListener("click", () => { page--; showPage(); });
document.querySelector("#next").addEventListener("click", () => { page++; showPage(); });
image.addEventListener("error", () => { error.textContent = "This PDF page could not be displayed."; });

fetch("/api/documents")
  .then((response) => response.json())
  .then((documents) => {
    const doc = documents.find((item) => item.id === id);
    if (!doc) throw new Error("Document not found.");
    pages = doc.pages;
    document.querySelector("#file-name").textContent = doc.name;
    document.title = `${doc.name} · PDF viewer`;
    document.querySelector("#original-link").href = `/api/documents/${encodeURIComponent(id)}/file`;
    showPage();
  })
  .catch((failure) => { error.textContent = failure.message; });
