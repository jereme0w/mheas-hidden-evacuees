"use strict";
const byId = id => document.getElementById(id);
let snapshot = null;
let selectedRegion = null;
let selectedReport = null;
let lastUpdated = null;
let loading = false;
const colours = { investigate: "#f9deda", monitor: "#ffedc9", clear: "#e3edf5", unknown: "#e9eef1" };
const number = value => Number.isFinite(value) ? value.toLocaleString(undefined, { maximumFractionDigits: 1 }) : "Unavailable";
const statusClass = row => row.alert ? "investigate" : row.classification === "Monitor" ? "monitor" : row.classification === "No silence alert" ? "clear" : "unknown";
const countKnown = row => row.classification !== "Insufficient data";
const node = (tag, text, className) => {
    const item = document.createElement(tag);
    if (text !== undefined) item.textContent = text;
    if (className) item.className = className;
    return item;
};
const badge = (text, className) => node("span", text, "badge " + className);

function chooseRegion(id) {
    if (!snapshot || !snapshot.area_information_gaps.some(row => row.region_id === id)) return;
    selectedRegion = id;
    renderMap(); renderDistrict();
}

function renderMap() {
    const damageLayer = byId("mapLayer").value === "damage";
    for (const row of snapshot.area_information_gaps) {
        const group = document.querySelector(`[data-region="${row.region_id}"]`);
        if (!group) continue;
        group.classList.toggle("selected", row.region_id === selectedRegion);
        group.setAttribute("aria-pressed", String(row.region_id === selectedRegion));
        group.setAttribute("aria-label", `${row.region_name}: ${row.classification}; ${countKnown(row) ? number(row.report_count) : "unknown"} received, ${number(row.expected_reports)} expected`);
        const damage = row.context.damage_level;
        group.querySelector("path").style.fill = damageLayer
            ? (damage >= .6 ? "#f8b4a7" : damage >= .3 ? "#fde6b7" : "#e8f0f3")
            : colours[statusClass(row)];
        group.querySelector(".map-count").textContent = damageLayer
            ? `${Math.round(damage * 100)}/100 damage index`
            : (countKnown(row) ? `${number(row.report_count)} received / ${number(row.expected_reports)} expected` : "Reporting unavailable");
        group.querySelector(".map-status").textContent = row.classification;
    }
    const legend = byId("mapLegend"); legend.replaceChildren();
    const entries = damageLayer
        ? [["#e8f0f3", "Index below 30"], ["#fde6b7", "Index 30–59"], ["#f8b4a7", "Index 60–100"]]
        : [[colours.investigate, "Investigate"], [colours.monitor, "Monitor"], [colours.clear, "No silence alert"], [colours.unknown, "Review / unavailable"]];
    for (const [colour, text] of entries) {
        const label = node("span"); const swatch = node("i", undefined, "swatch");
        swatch.style.backgroundColor = colour; label.append(swatch, node("span", text)); legend.append(label);
    }
}

function addContext(list, label, value) {
    const row = node("div", undefined, "context-row");
    row.append(node("dt", label), node("dd", value)); list.append(row);
}

function renderDistrict() {
    const row = snapshot.area_information_gaps.find(item => item.region_id === selectedRegion);
    if (!row) return;
    byId("districtTitle").textContent = row.region_name;
    byId("districtBadge").textContent = row.classification;
    byId("districtBadge").className = "badge " + statusClass(row);
    byId("districtPanel").className = "panel district-panel " + statusClass(row);
    byId("districtReason").textContent = row.reason;
    byId("selectedReceived").textContent = countKnown(row) ? number(row.report_count) : "Unknown";
    byId("selectedExpected").textContent = number(row.expected_reports);
    byId("predictionRange").textContent = Array.isArray(row.expected_range_90)
        ? `90% predictive report-count range: ${row.expected_range_90.join("–")}` : "Predictive range unavailable";
    const list = byId("districtContext"); list.replaceChildren();
    addContext(list, "Estimated population", number(row.context.population));
    addContext(list, "Occupied households", number(row.context.occupied_households));
    addContext(list, "Shaking intensity", `${number(row.context.shaking_intensity)} MMI`);
    addContext(list, "Damage index", `${Math.round(row.context.damage_level * 100)} / 100`);
    addContext(list, "Infrastructure disruption", row.context.infrastructure);
    addContext(list, "Communications", row.context.communications);
    addContext(list, "Collection feed", row.context.report_feed_complete ? "Up to date" : "Incomplete / unknown");
    addContext(list, "Latest report age", row.latest_report_age_hours === null ? "No reports" : `${number(row.latest_report_age_hours)} h in scenario`);
    addContext(list, "Lower-tail probability", Number.isFinite(row.lower_tail_probability) ? row.lower_tail_probability.toExponential(2) : "Unavailable");
    byId("filterDistrict").disabled = false;
}

function renderChart() {
    const rows = snapshot.area_information_gaps;
    const maximum = Math.max(1, ...rows.flatMap(row => [row.report_count || 0, row.expected_reports || 0, row.expected_range_90?.[1] || 0]));
    const chart = byId("reportChart"); chart.replaceChildren();
    for (const row of rows) {
        const item = node("button", undefined, "chart-row"); item.type = "button";
        item.setAttribute("aria-label", `${row.region_name}: ${countKnown(row) ? number(row.report_count) : "unknown"} received, ${number(row.expected_reports)} expected`);
        item.addEventListener("click", () => chooseRegion(row.region_id));
        const bars = node("div");
        for (const [value, style, known] of [[row.report_count, "received", countKnown(row)], [row.expected_reports, "expected", Number.isFinite(row.expected_reports)]]) {
            const line = node("div", undefined, "bar-line"); const track = node("div", undefined, "bar-track");
            const bar = node("div", undefined, "bar " + style); bar.style.width = known ? `${value / maximum * 100}%` : "0%";
            track.append(bar); line.append(track, node("span", known ? number(value) : "—", "bar-value")); bars.append(line);
        }
        bars.append(node("div", Array.isArray(row.expected_range_90) ? `90% expected range ${row.expected_range_90.join("–")}` : "Estimate unavailable", "chart-range"));
        item.append(node("span", row.region_name, "chart-name"), bars); chart.append(item);
    }
}

function renderQueue() {
    const queue = byId("reviewQueue"); queue.replaceChildren();
    const order = { investigate: 0, unknown: 1, monitor: 2, clear: 3 };
    const rows = snapshot.area_information_gaps.filter(row => statusClass(row) !== "clear").sort((a, b) => order[statusClass(a)] - order[statusClass(b)]);
    if (!rows.length) queue.append(node("p", "No regional visibility alerts in this snapshot. This does not establish safety.", "empty"));
    for (const row of rows) {
        const item = node("button", undefined, "review-item"); item.type = "button";
        const title = node("div", undefined, "review-title"); title.append(node("strong", row.region_name), badge(row.classification, statusClass(row)));
        item.append(title, node("p", `${countKnown(row) ? number(row.report_count) : "Unknown"} received · ${number(row.expected_reports)} expected · damage index ${Math.round(row.context.damage_level * 100)}/100`));
        item.addEventListener("click", () => chooseRegion(row.region_id)); queue.append(item);
    }
}

function reportSource(record) {
    return record.source === "synthetic_count_fixture" ? "Legacy count fixture" : record.source === "synthetic_community_report" ? "Fictional demo report" : "Community form";
}

function showReport(record) {
    selectedReport = record.report_id;
    byId("reportDetails").hidden = false;
    byId("reportDetailsTitle").textContent = "Report " + record.report_id;
    const body = byId("reportDetailsBody"); body.replaceChildren();
    const isFixture = record.source === "synthetic_count_fixture";
    if (isFixture) body.append(node("p", "This seeded fixture records report presence only. Its neutral placeholders are not scored report details.", "muted"));
    const list = node("dl", undefined, "context-list");
    addContext(list, "District", snapshot.area_information_gaps.find(row => row.region_id === record.region_id)?.region_name || record.region_id);
    addContext(list, "Fictional household", record.household_id);
    addContext(list, "Source", reportSource(record));
    addContext(list, "Scenario submission time", record.submitted_at);
    addContext(list, "Verification", record.verification_status);
    if (!isFixture) {
        const report = record.model_report;
        addContext(list, "People affected", report.people_affected >= 4 ? "4 or more (capped scoring factor)" : number(report.people_affected));
        addContext(list, "Self-reported urgency", report.urgency + " / 10");
        addContext(list, "Reporter type", report.reporter_type || "unspecified");
        addContext(list, "Immediate danger", report.immediate_danger ? "Yes" : "No");
        addContext(list, "Help requested", report.needs.join(", "));
        addContext(list, "Shelter / responder access", `${report.shelter_status} / ${report.responder_access}`);
        addContext(list, "Report priority", `${record.priority.priority} · ${number(record.priority.score)} / 10`);
        addContext(list, "Priority method", "Illustrative weighted baseline");
        addContext(list, record.source === "synthetic_community_report" ? "Demo snapshot time" : "Real receipt time", record.created_at);
    }
    const link = node("a", "View full saved JSON ↗"); link.href = "/api/reports/" + encodeURIComponent(record.report_id); link.target = "_blank"; link.rel = "noopener";
    body.append(list, link); byId("reportDetailsTitle").focus();
    byId("reportDetails").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function renderReports() {
    const includeFixtures = byId("showFixtures").checked;
    const district = byId("reportDistrict").value;
    const priority = byId("priorityFilter").value;
    const rows = snapshot.reports.filter(row => (includeFixtures || row.source !== "synthetic_count_fixture") && (!district || row.region_id === district) && (!priority || row.priority?.priority === priority))
        .sort((a, b) => b.submitted_at.localeCompare(a.submitted_at) || b.created_at.localeCompare(a.created_at));
    const body = byId("reportRows"); body.replaceChildren();
    const communityCount = snapshot.reports.filter(row => row.source === "fictional_community_form").length;
    byId("reportsCaption").textContent = `${communityCount} community submission${communityCount === 1 ? "" : "s"} · ${snapshot.demo_submission_count || 0} scored fictional demo reports · ${snapshot.fixture_submission_count} legacy count fixtures`;
    if (!rows.length) { const row = node("tr"); const cell = node("td", "No reports match these filters."); cell.colSpan = 5; row.append(cell); body.append(row); }
    for (const record of rows.slice(0, 200)) {
        const row = node("tr"); const districtCell = node("td");
        districtCell.append(node("span", snapshot.area_information_gaps.find(item => item.region_id === record.region_id)?.region_name || record.region_id), node("small", record.household_id));
        const isFixture = record.source === "synthetic_count_fixture";
        const priorityCell = node("td"); priorityCell.append(record.priority ? badge(record.priority.priority, record.priority.priority.toLowerCase()) : badge("Not scored", "unknown"));
        const detail = node("td"); const button = node("button", "View", "table-action"); button.type = "button"; button.addEventListener("click", () => showReport(record)); detail.append(button);
        row.append(districtCell, node("td", isFixture ? "Count fixture only" : record.model_report.needs.join(", ")), priorityCell, node("td", reportSource(record)), detail); body.append(row);
    }
    byId("reportLimit").textContent = rows.length > 200 ? `Showing the latest 200 of ${rows.length} matching submissions. Regional counts include all eligible reports.` : `${rows.length} matching submissions. Updates from one household count once in regional totals.`;
}

function render() {
    const rows = snapshot.area_information_gaps;
    const unknown = rows.filter(row => !countKnown(row)).length;
    byId("snapshot").textContent = `+${snapshot.hours_since_earthquake} h · fixed demo snapshot`;
    byId("alertCount").textContent = number(snapshot.alert_count);
    byId("alertCaption").textContent = `${rows.filter(row => row.classification === "Monitor").length} monitored · ${unknown} with unknown reporting data`;
    byId("reportCount").textContent = unknown ? "Partial data" : number(rows.reduce((sum, row) => sum + row.report_count, 0));
    byId("expectedCount").textContent = rows.every(row => Number.isFinite(row.expected_reports)) ? number(rows.reduce((sum, row) => sum + row.expected_reports, 0)) : "Unavailable";
    byId("occupiedCount").textContent = number(rows.reduce((sum, row) => sum + row.context.occupied_households, 0));
    const filter = byId("reportDistrict"); const oldFilter = filter.value;
    filter.replaceChildren(node("option", "All districts")); filter.firstChild.value = "";
    for (const row of rows) { const option = node("option", row.region_name); option.value = row.region_id; filter.append(option); }
    filter.value = oldFilter;
    if (!rows.some(row => row.region_id === selectedRegion)) selectedRegion = rows.find(row => row.alert)?.region_id || rows[0]?.region_id;
    renderMap(); renderDistrict(); renderChart(); renderQueue(); renderReports();
    if (selectedReport) { const report = snapshot.reports.find(row => row.report_id === selectedReport); if (!report) { selectedReport = null; byId("reportDetails").hidden = true; } }
}

async function load() {
    if (loading) return;
    loading = true; byId("refresh").disabled = true;
    const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 8000);
    byId("loadStatus").textContent = "Refreshing the reporting snapshot…";
    try {
        const response = await fetch("/api/dashboard", { signal: controller.signal, cache: "no-store" });
        if (!response.ok) throw new Error("Dashboard unavailable");
        const data = await response.json();
        if (!Array.isArray(data.area_information_gaps) || !data.area_information_gaps.length || !Array.isArray(data.reports)) throw new Error("Incomplete snapshot");
        snapshot = data; lastUpdated = new Date().toLocaleTimeString(); render();
        document.body.dataset.stale = "false"; byId("errorBanner").hidden = true;
        byId("loadStatus").textContent = `Fetched at ${lastUpdated} · Scenario time ${snapshot.assessment_time} · Synthetic training`;
    } catch (error) {
        document.body.dataset.stale = "true"; byId("errorBanner").hidden = false;
        byId("errorBanner").textContent = snapshot ? `Could not refresh. Showing the last successful snapshot fetched at ${lastUpdated}; these results may be stale.` : "Dashboard data is unavailable. Report counts are unknown; check the server and retry.";
        byId("loadStatus").textContent = "Data unavailable — refresh to retry.";
    } finally { clearTimeout(timer); loading = false; byId("refresh").disabled = false; }
}

byId("refresh").addEventListener("click", load);
byId("mapLayer").addEventListener("change", () => { if (snapshot) renderMap(); });
for (const id of ["reportDistrict", "priorityFilter", "showFixtures"]) byId(id).addEventListener("change", () => { if (snapshot) renderReports(); });
byId("filterDistrict").addEventListener("click", () => { if (!snapshot) return; byId("reportDistrict").value = selectedRegion; renderReports(); byId("reportRows").scrollIntoView({ behavior: "smooth", block: "center" }); });
byId("closeDetails").addEventListener("click", () => { selectedReport = null; byId("reportDetails").hidden = true; });
for (const group of document.querySelectorAll(".district")) {
    group.addEventListener("click", () => chooseRegion(group.dataset.region));
    group.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); chooseRegion(group.dataset.region); } });
}
load();
