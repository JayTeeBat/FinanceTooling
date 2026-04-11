# ruff: noqa: E501
"""Self-contained static review helper for categorization triage."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from finance_tooling.categorization.classify import ClassificationRules
from finance_tooling.review.common import REVIEW_STATUS_VALUES, taxonomy_label_rows


def _serialize_payload(payload: dict[str, object]) -> str:
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    return serialized.replace("</", "<\\/")


def _clean_rows(dataframe: pd.DataFrame) -> list[dict[str, object]]:
    return dataframe.where(pd.notna(dataframe), None).to_dict(orient="records")


def _taxonomy_payload(rules: ClassificationRules | None) -> dict[str, list[str]]:
    if rules is None:
        return {"Uncategorized": []}
    mapping: dict[str, list[str]] = {}
    for category, subcategory in taxonomy_label_rows(rules):
        values = mapping.setdefault(category, [])
        if subcategory and subcategory not in values:
            values.append(subcategory)
    return dict(sorted(mapping.items(), key=lambda item: item[0].casefold()))


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Finance Tooling Review Helper</title>
  <style>
    :root {
      --paper: #fbf7ef;
      --panel: rgba(255, 252, 246, 0.96);
      --ink: #1d1a14;
      --muted: #6f6559;
      --line: #d7c8b4;
      --accent: #9a5f2f;
      --accent-deep: #6e3d19;
      --olive: #78825f;
      --warn: #b76c39;
      --shadow: 0 16px 34px rgba(64, 45, 28, 0.12);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(154, 95, 47, 0.13), transparent 30%),
        radial-gradient(circle at bottom right, rgba(120, 130, 95, 0.14), transparent 26%),
        linear-gradient(180deg, #f6efe2, var(--paper));
      min-height: 100vh;
    }
    .shell {
      max-width: min(100vw - 24px, 1680px);
      margin: 0 auto;
      padding: 16px;
      display: grid;
      gap: 18px;
    }
    .panel, .table-wrap {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: var(--shadow);
    }
    h1 {
      margin: 0;
      font-family: "IBM Plex Serif", Georgia, serif;
      font-size: 26px;
      letter-spacing: -0.03em;
    }
    .layout {
      display: grid;
      grid-template-columns: 280px minmax(0, 1fr);
      gap: 18px;
      align-items: start;
      min-height: calc(100vh - 32px);
    }
    .panel {
      padding: 12px;
      display: grid;
      gap: 10px;
      position: sticky;
      top: 16px;
      max-height: calc(100vh - 32px);
      overflow: hidden;
    }
    .panel-intro {
      display: grid;
      gap: 4px;
      padding-bottom: 0;
    }
    .section {
      display: grid;
      gap: 6px;
    }
    .section h2 {
      margin: 0;
      font-size: 16px;
      color: var(--accent-deep);
    }
    .field-grid {
      display: grid;
      gap: 8px;
    }
    label {
      display: grid;
      gap: 6px;
      font-size: 12px;
      font-weight: 700;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    input, select, textarea, button {
      font: inherit;
    }
    input, select, textarea {
      width: 100%;
      padding: 8px 10px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.95);
      color: var(--ink);
    }
    textarea { min-height: 58px; resize: vertical; }
    button {
      border: 0;
      border-radius: 999px;
      padding: 9px 14px;
      background: var(--accent);
      color: #fffaf5;
      cursor: pointer;
      font-weight: 700;
    }
    button.secondary {
      background: rgba(154, 95, 47, 0.12);
      color: var(--accent-deep);
      border: 1px solid rgba(154, 95, 47, 0.24);
    }
    .button-row {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .group-list {
      display: grid;
      gap: 8px;
      overflow: hidden;
    }
    .group-item {
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 10px 12px;
      background: rgba(255,255,255,0.72);
      cursor: pointer;
      color: var(--ink);
      text-align: left;
      width: 100%;
    }
    .group-item strong { display: block; margin-bottom: 4px; color: var(--accent-deep); }
    .group-item span { color: var(--ink); }
    .table-wrap {
      overflow: visible;
      padding: 10px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
    }
    th, td {
      border-bottom: 1px solid #eadfcc;
      padding: 8px 6px;
      vertical-align: top;
      text-align: left;
      font-size: 12px;
      overflow-wrap: anywhere;
      word-break: break-word;
    }
    th {
      position: sticky;
      top: 0;
      background: #f6eee2;
      z-index: 1;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--muted);
      white-space: nowrap;
    }
    th button {
      width: 100%;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 6px;
      padding: 0;
      border: 0;
      background: transparent;
      color: inherit;
      border-radius: 0;
      font: inherit;
      text-transform: inherit;
      letter-spacing: inherit;
      white-space: nowrap;
    }
    th button:hover {
      color: var(--accent-deep);
    }
    th button.active {
      color: var(--accent-deep);
    }
    .sort-indicator {
      color: var(--accent);
      font-size: 11px;
      line-height: 1;
      min-width: 10px;
      text-align: right;
    }
    .filter-indicator {
      color: var(--accent);
      font-size: 11px;
      line-height: 1;
    }
    td input, td select, td textarea {
      min-width: 0;
      width: 100%;
      padding: 7px 8px;
      font-size: 12px;
    }
    td textarea { min-height: 44px; }
    th:nth-child(1), td:nth-child(1) { width: 8%; }
    th:nth-child(2), td:nth-child(2) { width: 17%; }
    th:nth-child(3), td:nth-child(3) { width: 7%; }
    th:nth-child(4), td:nth-child(4) { width: 7%; }
    th:nth-child(5), td:nth-child(5) { width: 12%; }
    th:nth-child(6), td:nth-child(6) { width: 11%; }
    th:nth-child(7), td:nth-child(7) { width: 10%; }
    th:nth-child(8), td:nth-child(8) { width: 10%; }
    th:nth-child(9), td:nth-child(9) { width: 7%; }
    th:nth-child(10), td:nth-child(10) { width: 6%; }
    th:nth-child(11), td:nth-child(11) { width: 5%; }
    .stat-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }
    .stat {
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 8px;
      background: rgba(255,255,255,0.72);
    }
    .stat strong {
      display: block;
      font-size: 18px;
      color: var(--accent-deep);
    }
    .empty {
      padding: 32px;
      text-align: center;
      color: var(--muted);
    }
    .caption { color: var(--muted); font-size: 12px; }
    .filter-menu[hidden] { display: none; }
    .filter-menu {
      position: fixed;
      z-index: 10;
      width: min(280px, calc(100vw - 24px));
      max-height: min(420px, calc(100vh - 40px));
      overflow: auto;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: rgba(255, 252, 246, 0.98);
      box-shadow: var(--shadow);
      display: grid;
      gap: 10px;
    }
    .filter-menu h3 {
      margin: 0;
      font-size: 14px;
      color: var(--accent-deep);
    }
    .filter-menu h4 {
      margin: 0;
      font-size: 12px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .filter-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .menu-section {
      display: grid;
      gap: 8px;
    }
    .filter-options {
      display: grid;
      gap: 8px;
    }
    .filter-options label {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 12px;
      font-weight: 600;
      text-transform: none;
      letter-spacing: 0;
      color: var(--ink);
    }
    .filter-options input[type="checkbox"] {
      width: auto;
      margin: 0;
    }
    @media (max-width: 1450px) {
      .layout { grid-template-columns: 1fr; }
      .panel { position: static; }
    }
    @media (max-width: 1100px) {
      .layout { grid-template-columns: 1fr; }
      .panel { position: static; }
      .stat-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <div class="layout">
      <aside class="panel">
        <section class="panel-intro">
          <h1>Review Helper</h1>
        </section>
        <section class="section">
          <h2>Queue</h2>
          <div class="stat-grid">
            <div class="stat"><span class="caption">Rows</span><strong id="statRows">0</strong></div>
            <div class="stat"><span class="caption">Groups</span><strong id="statGroups">0</strong></div>
            <div class="stat"><span class="caption">Needs Rule</span><strong id="statNeedsRule">0</strong></div>
          </div>
        </section>
        <section class="section">
          <h2>Filters</h2>
          <div class="field-grid">
            <label>Search<input id="searchInput" type="search" placeholder="merchant, bank, account" /></label>
            <label>Review Status<select id="statusFilter"></select></label>
            <label>Bank<select id="bankFilter"></select></label>
            <label>Month<select id="monthFilter"></select></label>
          </div>
        </section>
        <section class="section">
          <h2>Bulk Draft</h2>
          <div class="field-grid">
            <label>Category<select id="bulkCategory"></select></label>
            <label>Subcategory<select id="bulkSubcategory"></select></label>
            <label>Review Status<select id="bulkStatus"></select></label>
            <label>Project Tags<input id="bulkProjectTags" type="text" placeholder="Family|Shared" /></label>
            <label>Review Comment<textarea id="bulkComment" placeholder="Optional note"></textarea></label>
          </div>
          <div class="button-row">
            <button id="applyToFiltered">Apply to filtered rows</button>
            <button id="downloadDraft" class="secondary">Download draft JSON</button>
          </div>
        </section>
        <section class="section">
          <h2>Top Groups</h2>
          <div class="group-list" id="groupList"></div>
        </section>
      </aside>
      <section class="table-wrap">
        <table>
          <thead>
            <tr>
              <th><button type="button" data-column-key="booking_date" data-column-label="Date">Date<span class="sort-indicator"></span><span class="filter-indicator"></span></button></th>
              <th><button type="button" data-column-key="description" data-column-label="Description">Description<span class="sort-indicator"></span><span class="filter-indicator"></span></button></th>
              <th><button type="button" data-column-key="amount_native" data-column-label="Amount">Amount<span class="sort-indicator"></span><span class="filter-indicator"></span></button></th>
              <th><button type="button" data-column-key="bank" data-column-label="Bank">Bank<span class="sort-indicator"></span><span class="filter-indicator"></span></button></th>
              <th><button type="button" data-column-key="review_group_key" data-column-label="Group" data-sort-key="review_group_size">Group<span class="sort-indicator"></span><span class="filter-indicator"></span></button></th>
              <th><button type="button" data-column-key="current_category" data-column-label="Current">Current<span class="sort-indicator"></span><span class="filter-indicator"></span></button></th>
              <th><button type="button" data-column-key="category" data-column-label="Category">Category<span class="sort-indicator"></span><span class="filter-indicator"></span></button></th>
              <th><button type="button" data-column-key="subcategory" data-column-label="Subcategory">Subcategory<span class="sort-indicator"></span><span class="filter-indicator"></span></button></th>
              <th><button type="button" data-column-key="review_status" data-column-label="Status">Status<span class="sort-indicator"></span><span class="filter-indicator"></span></button></th>
              <th><button type="button" data-column-key="project_tags" data-column-label="Project Tags">Project Tags<span class="sort-indicator"></span><span class="filter-indicator"></span></button></th>
              <th><button type="button" data-column-key="review_comment" data-column-label="Comment">Comment<span class="sort-indicator"></span><span class="filter-indicator"></span></button></th>
            </tr>
          </thead>
          <tbody id="rowsBody"></tbody>
        </table>
        <div id="emptyState" class="empty" hidden>No rows match the current filters.</div>
      </section>
    </div>
  </div>
  <div id="filterMenu" class="filter-menu" hidden>
    <h3 id="filterMenuTitle">Column</h3>
    <div class="menu-section">
      <h4>Sort</h4>
      <div class="filter-actions">
        <button id="sortAsc" type="button" class="secondary">Ascending</button>
        <button id="sortDesc" type="button" class="secondary">Descending</button>
        <button id="sortClear" type="button" class="secondary">Clear sort</button>
      </div>
    </div>
    <div id="filterSection" class="menu-section">
      <h4>Values</h4>
      <div class="filter-actions">
        <button id="filterSelectAll" type="button" class="secondary">Select all</button>
        <button id="filterClearAll" type="button" class="secondary">Clear all</button>
        <button id="filterApply" type="button">Apply</button>
      </div>
      <div id="filterOptions" class="filter-options"></div>
    </div>
  </div>
  <script>
    const payload = __PAYLOAD_JSON__;
    const taxonomy = payload.taxonomy || {};
    const categoryOptions = Object.keys(taxonomy);
    const drafts = new Map((payload.rows || []).map((row) => [String(row.transaction_id), {...row}]));
    const sortState = { key: "", direction: "" };
    const columnFilters = new Map();
    let activeColumnKey = "";
    const filterableColumnKeys = new Set(["bank", "review_group_key", "current_category", "category", "subcategory", "review_status"]);

    const els = {
      searchInput: document.getElementById("searchInput"),
      statusFilter: document.getElementById("statusFilter"),
      bankFilter: document.getElementById("bankFilter"),
      monthFilter: document.getElementById("monthFilter"),
      bulkCategory: document.getElementById("bulkCategory"),
      bulkSubcategory: document.getElementById("bulkSubcategory"),
      bulkStatus: document.getElementById("bulkStatus"),
      bulkProjectTags: document.getElementById("bulkProjectTags"),
      bulkComment: document.getElementById("bulkComment"),
      applyToFiltered: document.getElementById("applyToFiltered"),
      downloadDraft: document.getElementById("downloadDraft"),
      rowsBody: document.getElementById("rowsBody"),
      emptyState: document.getElementById("emptyState"),
      groupList: document.getElementById("groupList"),
      statRows: document.getElementById("statRows"),
      statGroups: document.getElementById("statGroups"),
      statNeedsRule: document.getElementById("statNeedsRule"),
      columnButtons: [...document.querySelectorAll("th button[data-column-key]")],
      filterMenu: document.getElementById("filterMenu"),
      filterMenuTitle: document.getElementById("filterMenuTitle"),
      filterSection: document.getElementById("filterSection"),
      filterOptions: document.getElementById("filterOptions"),
      sortAsc: document.getElementById("sortAsc"),
      sortDesc: document.getElementById("sortDesc"),
      sortClear: document.getElementById("sortClear"),
      filterSelectAll: document.getElementById("filterSelectAll"),
      filterClearAll: document.getElementById("filterClearAll"),
      filterApply: document.getElementById("filterApply"),
    };

    function buildOptions(select, values, includeBlank = true) {
      const current = select.value;
      select.innerHTML = "";
      if (includeBlank) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = "All";
        select.appendChild(option);
      }
      values.forEach((value) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        select.appendChild(option);
      });
      if ([...select.options].some((option) => option.value === current)) {
        select.value = current;
      }
    }

    function updateSubcategoryOptions(select, category, currentValue = "") {
      const subcategories = category ? (taxonomy[category] || []) : [];
      select.innerHTML = "";
      const blank = document.createElement("option");
      blank.value = "";
      blank.textContent = "";
      select.appendChild(blank);
      subcategories.forEach((subcategory) => {
        const option = document.createElement("option");
        option.value = subcategory;
        option.textContent = subcategory;
        select.appendChild(option);
      });
      if ([...select.options].some((option) => option.value === currentValue)) {
        select.value = currentValue;
      }
    }

    function collectFilters() {
      return {
        search: els.searchInput.value.trim().toLowerCase(),
        status: els.statusFilter.value,
        bank: els.bankFilter.value,
        month: els.monthFilter.value,
      };
    }

    function currentCategoryLabel(row) {
      return `${row.original_category || "Uncategorized"}${row.original_subcategory ? " / " + row.original_subcategory : ""}`;
    }

    function filterValue(row, key) {
      if (key === "current_category") return currentCategoryLabel(row);
      if (key === "review_group_key") return String(row.review_group_key || "");
      return String(row[key] || "");
    }

    function visibleRows() {
      const filters = collectFilters();
      const rows = [...drafts.values()].filter((row) => {
        const haystack = [
          row.description,
          row.normalized_description,
          row.bank,
          row.account_label,
          row.review_group_key,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        const month = row.booking_date ? String(row.booking_date).slice(0, 7) : "";
        return (!filters.search || haystack.includes(filters.search))
          && (!filters.status || row.review_status === filters.status)
          && (!filters.bank || row.bank === filters.bank)
          && (!filters.month || month === filters.month);
      });
      const filteredRows = rows.filter((row) => {
        return [...columnFilters.entries()].every(([key, selected]) => {
          if (!selected || selected.size === 0) return true;
          return selected.has(filterValue(row, key));
        });
      });
      return sortRows(filteredRows);
    }

    function sortValue(row, key) {
      if (key === "current_category") {
        return `${row.original_category || ""} / ${row.original_subcategory || ""}`.toLowerCase();
      }
      const value = row[key];
      if (key === "amount_native" || key === "review_group_size") {
        return Number(value || 0);
      }
      return String(value || "").toLowerCase();
    }

    function sortRows(rows) {
      if (!sortState.key || !sortState.direction) {
        return rows;
      }
      const direction = sortState.direction === "desc" ? -1 : 1;
      return [...rows].sort((left, right) => {
        const leftValue = sortValue(left, sortState.key);
        const rightValue = sortValue(right, sortState.key);
        if (leftValue < rightValue) return -1 * direction;
        if (leftValue > rightValue) return 1 * direction;
        return String(left.transaction_id || "").localeCompare(String(right.transaction_id || ""));
      });
    }

    function renderSortIndicators() {
      els.columnButtons.forEach((button) => {
        const indicator = button.querySelector(".sort-indicator");
        if (!indicator) return;
        const sortKey = button.dataset.sortKey || button.dataset.columnKey || "";
        if (sortKey === sortState.key) {
          indicator.textContent = sortState.direction === "asc" ? "▲" : "▼";
        } else {
          indicator.textContent = "";
        }
      });
    }

    function renderFilterIndicators() {
      els.columnButtons.forEach((button) => {
        const key = button.dataset.columnKey || "";
        const indicator = button.querySelector(".filter-indicator");
        const selected = columnFilters.get(key);
        const isActive = !!selected && selected.size > 0;
        button.classList.toggle("active", isActive);
        if (indicator) {
          indicator.textContent = isActive ? "●" : "";
        }
      });
    }

    function availableFilterValues(filterKey) {
      const values = new Set();
      [...drafts.values()].forEach((row) => {
        values.add(filterValue(row, filterKey));
      });
      return [...values].sort((left, right) => left.localeCompare(right));
    }

    function openColumnMenu(columnKey, label, anchor) {
      activeColumnKey = columnKey;
      els.filterMenuTitle.textContent = label;
      const canFilter = filterableColumnKeys.has(columnKey);
      els.filterSection.hidden = !canFilter;
      els.filterOptions.innerHTML = "";
      if (canFilter) {
        const selected = new Set(columnFilters.get(columnKey) || availableFilterValues(columnKey));
        availableFilterValues(columnKey).forEach((value) => {
          const optionLabel = document.createElement("label");
          const checkbox = document.createElement("input");
          checkbox.type = "checkbox";
          checkbox.value = value;
          checkbox.checked = selected.has(value);
          const text = document.createElement("span");
          text.textContent = value || "(blank)";
          optionLabel.appendChild(checkbox);
          optionLabel.appendChild(text);
          els.filterOptions.appendChild(optionLabel);
        });
      }
      const rect = anchor.getBoundingClientRect();
      els.filterMenu.style.top = `${Math.min(rect.bottom + 8, window.innerHeight - 440)}px`;
      els.filterMenu.style.left = `${Math.min(rect.left, window.innerWidth - 296)}px`;
      els.filterMenu.hidden = false;
    }

    function closeFilterMenu() {
      activeColumnKey = "";
      els.filterMenu.hidden = true;
    }

    function applySort(direction) {
      if (!activeColumnKey) return;
      const columnButton = els.columnButtons.find((button) => button.dataset.columnKey === activeColumnKey);
      const sortKey = (columnButton && (columnButton.dataset.sortKey || columnButton.dataset.columnKey)) || activeColumnKey;
      if (!sortKey) return;
      sortState.key = sortKey;
      sortState.direction = direction;
      closeFilterMenu();
      render();
    }

    function toggleSort(sortKey) {
      if (sortState.key !== sortKey) {
        sortState.key = sortKey;
        sortState.direction = "asc";
      } else if (sortState.direction === "asc") {
        sortState.direction = "desc";
      } else {
        sortState.key = "";
        sortState.direction = "";
      }
      render();
    }

    function writeDraftField(transactionId, field, value) {
      const row = drafts.get(String(transactionId));
      if (!row) return;
      row[field] = value || null;
      if (field === "review_status") {
        row.reviewed = value && value !== "todo";
      }
    }

    function renderRows() {
      const rows = visibleRows();
      els.rowsBody.innerHTML = "";
      els.emptyState.hidden = rows.length !== 0;

      rows.forEach((row) => {
        const tr = document.createElement("tr");
        const categorySelect = document.createElement("select");
        updateSubcategoryOptions(categorySelect, "", "");
        buildOptions(categorySelect, categoryOptions, true);
        categorySelect.value = row.category || "";
        categorySelect.addEventListener("change", () => {
          const nextCategory = categorySelect.value || null;
          writeDraftField(row.transaction_id, "category", nextCategory);
          writeDraftField(row.transaction_id, "subcategory", null);
          updateSubcategoryOptions(subcategorySelect, categorySelect.value, "");
          if (nextCategory && (statusSelect.value === "" || statusSelect.value === "todo")) {
            statusSelect.value = "done";
            writeDraftField(row.transaction_id, "review_status", "done");
            renderStats();
          }
          renderGroupList();
        });

        const subcategorySelect = document.createElement("select");
        updateSubcategoryOptions(subcategorySelect, row.category || "", row.subcategory || "");
        subcategorySelect.addEventListener("change", () => {
          writeDraftField(row.transaction_id, "subcategory", subcategorySelect.value || null);
        });

        const statusSelect = document.createElement("select");
        buildOptions(statusSelect, [...payload.review_status_values], false);
        statusSelect.value = row.review_status || "todo";
        statusSelect.addEventListener("change", () => {
          writeDraftField(row.transaction_id, "review_status", statusSelect.value);
          renderStats();
        });

        const projectInput = document.createElement("input");
        projectInput.value = row.project_tags || "";
        projectInput.addEventListener("input", () => {
          writeDraftField(row.transaction_id, "project_tags", projectInput.value);
        });

        const commentInput = document.createElement("textarea");
        commentInput.value = row.review_comment || "";
        commentInput.addEventListener("input", () => {
          writeDraftField(row.transaction_id, "review_comment", commentInput.value);
        });

        const cells = [
          row.booking_date || "",
          row.description || "",
          row.amount_native ?? "",
          row.bank || "",
          `${row.review_group_size || 0} x ${row.review_group_key || ""}`,
          currentCategoryLabel(row),
        ];
        cells.forEach((value) => {
          const td = document.createElement("td");
          td.textContent = String(value);
          tr.appendChild(td);
        });
        [categorySelect, subcategorySelect, statusSelect, projectInput, commentInput].forEach((control) => {
          const td = document.createElement("td");
          td.appendChild(control);
          tr.appendChild(td);
        });
        els.rowsBody.appendChild(tr);
      });
    }

    function renderStats() {
      const rows = visibleRows();
      const groupCount = new Set(rows.map((row) => row.review_group_key)).size;
      const needsRuleCount = rows.filter((row) => row.review_status === "needs_rule").length;
      els.statRows.textContent = String(rows.length);
      els.statGroups.textContent = String(groupCount);
      els.statNeedsRule.textContent = String(needsRuleCount);
    }

    function renderGroupList() {
      const grouped = new Map();
      visibleRows().forEach((row) => {
        const key = row.review_group_key || "unknown";
        grouped.set(key, (grouped.get(key) || 0) + 1);
      });
      els.groupList.innerHTML = "";
      [...grouped.entries()]
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
        .slice(0, 12)
        .forEach(([groupKey, count]) => {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "group-item";
          button.innerHTML = `<strong>${count} rows</strong><span>${groupKey}</span>`;
          button.addEventListener("click", () => {
            els.searchInput.value = groupKey;
            render();
          });
          els.groupList.appendChild(button);
        });
    }

    function render() {
      renderRows();
      renderStats();
      renderGroupList();
      renderSortIndicators();
      renderFilterIndicators();
    }

    function applyBulkDraft() {
      const rows = visibleRows();
      rows.forEach((row) => {
        if (els.bulkCategory.value) row.category = els.bulkCategory.value;
        if (els.bulkSubcategory.value || els.bulkCategory.value) row.subcategory = els.bulkSubcategory.value || null;
        if (els.bulkStatus.value) {
          row.review_status = els.bulkStatus.value;
          row.reviewed = els.bulkStatus.value !== "todo";
        }
        if (els.bulkProjectTags.value) row.project_tags = els.bulkProjectTags.value;
        if (els.bulkComment.value) row.review_comment = els.bulkComment.value;
        drafts.set(String(row.transaction_id), row);
      });
      render();
    }

    function downloadDraft() {
      const rows = [...drafts.values()].map((row) => ({
        ...row,
        reviewed: row.review_status ? row.review_status !== "todo" : !!row.reviewed,
      }));
      const blob = new Blob([JSON.stringify(rows, null, 2)], {type: "application/json"});
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "transactions_review.json";
      anchor.click();
      URL.revokeObjectURL(url);
    }

    function initFilters() {
      buildOptions(els.statusFilter, [...payload.review_status_values], true);
      buildOptions(els.bankFilter, payload.banks || [], true);
      buildOptions(els.monthFilter, payload.months || [], true);
      buildOptions(els.bulkCategory, categoryOptions, true);
      buildOptions(els.bulkStatus, [...payload.review_status_values], true);
      updateSubcategoryOptions(els.bulkSubcategory, "", "");

      els.bulkCategory.addEventListener("change", () => {
        updateSubcategoryOptions(els.bulkSubcategory, els.bulkCategory.value, "");
      });
      els.columnButtons.forEach((button) => {
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          const columnKey = button.dataset.columnKey || "";
          if (!columnKey) return;
          if (!els.filterMenu.hidden && activeColumnKey === columnKey) {
            closeFilterMenu();
            return;
          }
          openColumnMenu(columnKey, button.dataset.columnLabel || columnKey, button);
        });
      });
      [els.searchInput, els.statusFilter, els.bankFilter, els.monthFilter].forEach((element) => {
        element.addEventListener("input", render);
        element.addEventListener("change", render);
      });
      els.applyToFiltered.addEventListener("click", applyBulkDraft);
      els.downloadDraft.addEventListener("click", downloadDraft);
      els.sortAsc.addEventListener("click", () => applySort("asc"));
      els.sortDesc.addEventListener("click", () => applySort("desc"));
      els.sortClear.addEventListener("click", () => {
        sortState.key = "";
        sortState.direction = "";
        closeFilterMenu();
        render();
      });
      els.filterSelectAll.addEventListener("click", () => {
        [...els.filterOptions.querySelectorAll('input[type="checkbox"]')].forEach((input) => {
          input.checked = true;
        });
      });
      els.filterClearAll.addEventListener("click", () => {
        [...els.filterOptions.querySelectorAll('input[type="checkbox"]')].forEach((input) => {
          input.checked = false;
        });
      });
      els.filterApply.addEventListener("click", () => {
        if (!activeColumnKey || !filterableColumnKeys.has(activeColumnKey)) return;
        const selected = new Set(
          [...els.filterOptions.querySelectorAll('input[type="checkbox"]:checked')].map(
            (input) => input.value
          )
        );
        const allValues = availableFilterValues(activeColumnKey);
        if (selected.size === 0 || selected.size === allValues.length) {
          columnFilters.delete(activeColumnKey);
        } else {
          columnFilters.set(activeColumnKey, selected);
        }
        closeFilterMenu();
        render();
      });
      document.addEventListener("click", (event) => {
        if (els.filterMenu.hidden) return;
        if (
          els.filterMenu.contains(event.target)
          || els.columnButtons.some((button) => button.contains(event.target))
        ) {
          return;
        }
        closeFilterMenu();
      });
    }

    initFilters();
    render();
  </script>
</body>
</html>
"""


def render_review_helper_html(
    review_rows: pd.DataFrame,
    destination: Path,
    *,
    rules: ClassificationRules | None = None,
) -> Path:
    """Render a self-contained HTML helper for review triage and draft export."""
    rows = _clean_rows(review_rows)
    banks = sorted({str(row.get("bank")) for row in rows if row.get("bank")})
    months = sorted(
        {
            str(row.get("booking_date"))[:7]
            for row in rows
            if row.get("booking_date") is not None and len(str(row.get("booking_date"))) >= 7
        }
    )
    top_review_groups = [
        {
            "review_group_key": str(row.get("review_group_key") or ""),
            "count": (
                int(str(row.get("review_group_size")))
                if row.get("review_group_size") not in (None, "")
                else 0
            ),
        }
        for row in rows[:10]
    ]
    payload = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "rows": rows,
        "banks": banks,
        "months": months,
        "top_review_groups": top_review_groups,
        "taxonomy": _taxonomy_payload(rules),
        "review_status_values": list(REVIEW_STATUS_VALUES),
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        _HTML_TEMPLATE.replace("__PAYLOAD_JSON__", _serialize_payload(payload)),
        encoding="utf-8",
    )
    return destination
