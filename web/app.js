const $ = (selector) => document.querySelector(selector);
const documents = $("#documents");
const count = $("#count");
const conversation = $("#conversation");

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `Request failed (${response.status})`);
  return result;
}

function pdfUrl(id, page = 1) {
  return `/viewer.html?id=${encodeURIComponent(id)}&page=${page}`;
}

async function loadDocuments() {
  const list = await api("/api/documents");
  count.textContent = `${list.length} ${list.length === 1 ? "file" : "files"}`;
  documents.replaceChildren();
  if (!list.length) {
    const empty = document.createElement("p");
    empty.className = "tip";
    empty.textContent = "No PDFs yet. Upload a company report to begin.";
    documents.append(empty);
  }
  for (const doc of list) {
    const row = document.createElement("div"); row.className = "doc";
    const top = document.createElement("div"); top.className = "doc-top";
    const link = document.createElement("a"); link.className = "doc-name";
    link.href = pdfUrl(doc.id); link.target = "_blank"; link.rel = "noopener";
    link.textContent = doc.name; link.title = "Open PDF";
    const remove = document.createElement("button"); remove.className = "delete";
    remove.type = "button"; remove.textContent = "Delete";
    remove.addEventListener("click", async () => {
      if (!confirm(`Delete ${doc.name} from this local collection?`)) return;
      try { await api(`/api/documents/${doc.id}`, {method: "DELETE"}); await loadDocuments(); }
      catch (error) { setStatus(error.message, true); }
    });
    const meta = document.createElement("div"); meta.className = "doc-meta";
    meta.textContent = `${doc.pages} pages · ${doc.indexed_chunks} passages · uploaded ${doc.uploaded_at}`;
    top.append(link, remove); row.append(top, meta); documents.append(row);
  }
}

function setStatus(message, isError = false) {
  const status = $("#upload-status"); status.textContent = message;
  status.classList.toggle("error", isError);
}

function addMessage(role, body, sources = []) {
  const wrapper = document.createElement("div"); wrapper.className = `message ${role}`;
  const bubble = document.createElement("div"); bubble.className = "bubble";
  bubble.textContent = body; wrapper.append(bubble);
  if (sources.length) {
    const list = document.createElement("ul"); list.className = "source-list";
    sources.forEach((source) => {
      const item = document.createElement("li");
      const link = document.createElement("a"); link.href = pdfUrl(source.id, source.page);
      link.target = "_blank"; link.rel = "noopener";
      link.textContent = `${source.number ? `[${source.number}] ` : ""}${source.name} · PDF p. ${source.page}`;
      item.append(link); list.append(item);
    });
    wrapper.append(list);
  }
  conversation.append(wrapper);
  conversation.scrollTop = conversation.scrollHeight;
  return wrapper;
}

$("#upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = $("#pdf-file").files[0]; if (!file) return;
  if (file.size > 50 * 1024 * 1024) return setStatus("Please choose a PDF under 50 MB.", true);
  const button = $("#upload-button"); button.disabled = true;
  setStatus("Uploading and indexing pages. Large reports may take several minutes…");
  try {
    const data = new FormData(); data.append("file", file);
    const result = await api("/api/documents", {method: "POST", body: data});
    setStatus(`${result.name} indexed: ${result.pages} pages, ${result.chunks} passages${result.embedded_chunks ? `, ${result.embedded_chunks} embeddings` : " (keyword search)"}.`);
    $("#pdf-file").value = "";
    await loadDocuments();
  } catch (error) { setStatus(error.message, true); }
  finally { button.disabled = false; }
});

$("#chat-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const field = $("#question"); const question = field.value.trim(); if (!question) return;
  field.value = ""; addMessage("user", question);
  const button = $("#ask-button"); button.disabled = true;
  const pending = addMessage("assistant", "Searching your PDFs and asking the local model…");
  try {
    const result = await api("/api/chat", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({question})});
    pending.remove(); addMessage("assistant", result.answer, result.sources);
  } catch (error) { pending.remove(); addMessage("assistant", error.message); }
  finally { button.disabled = false; field.focus(); }
});

loadDocuments().catch((error) => setStatus(error.message, true));
