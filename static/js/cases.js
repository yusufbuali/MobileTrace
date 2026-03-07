import { api } from "./api.js";

const caseList = document.getElementById("case-list");
const searchInput = document.getElementById("search-cases");
const filterStatus = document.getElementById("filter-status");
const btnNewCase = document.getElementById("btn-new-case");
const btnCancel = document.getElementById("btn-cancel-case");
const formNewCase = document.getElementById("form-new-case");

let allCases = [];
let activeCaseId = null;

function statusBadge(status) {
  return `<span class="status-badge status-${status}">${status.replace("_", " ")}</span>`;
}

function renderCases(cases) {
  caseList.innerHTML = cases.map(c => `
    <div class="case-item ${c.id === activeCaseId ? "active" : ""}" data-id="${c.id}">
      <div class="case-title">${c.title}</div>
      <div class="case-meta">
        ${c.officer || "&mdash;"} &middot; ${statusBadge(c.status)}
      </div>
    </div>
  `).join("");

  caseList.querySelectorAll(".case-item").forEach(el => {
    el.addEventListener("click", () => openCase(el.dataset.id));
  });
}

async function loadCases() {
  const status = filterStatus.value;
  allCases = await api.getCases(status);
  filterCases();
}

function filterCases() {
  const q = searchInput.value.toLowerCase();
  const filtered = q
    ? allCases.filter(c => c.title.toLowerCase().includes(q) || (c.case_number || "").toLowerCase().includes(q))
    : allCases;
  renderCases(filtered);
}

function showView(id) {
  document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
  document.getElementById(id).classList.add("active");
}

function openCase(id) {
  activeCaseId = id;
  renderCases(allCases);
  showView("view-case-dashboard");
  // Dashboard population handled by dashboard.js (Phase 4)
  document.getElementById("dashboard-placeholder").textContent = `Case ${id} — parsing & analysis coming in Phase 4`;
}

btnNewCase.addEventListener("click", () => showView("view-new-case"));
btnCancel.addEventListener("click", () => showView("view-welcome"));
searchInput.addEventListener("input", filterCases);
filterStatus.addEventListener("change", loadCases);

formNewCase.addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(formNewCase);
  const body = {
    title: fd.get("title"),
    officer: fd.get("officer"),
    case_number: fd.get("case_number"),
  };
  try {
    const c = await api.createCase(body);
    allCases.unshift(c);
    activeCaseId = c.id;
    filterCases();
    showView("view-case-dashboard");
    formNewCase.reset();
  } catch (err) {
    alert("Failed to create case: " + err.message);
  }
});

// Boot
loadCases();
showView("view-welcome");
