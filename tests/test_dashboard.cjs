const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");
const root = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(root, "frontend", "dashboard.html"), "utf8");
const script = fs.readFileSync(path.join(root, "frontend", "dashboard.js"), "utf8");
const fixture = JSON.parse(fs.readFileSync(path.join(root, "tests", "cases", "dashboard_snapshot.json"), "utf8"));
const clone = value => JSON.parse(JSON.stringify(value));
const tick = () => new Promise(resolve => setImmediate(resolve));

async function setup(data = clone(fixture), fail = false) {
    const dom = new JSDOM(html, { url: "http://127.0.0.1:5001/dashboard", runScripts: "outside-only" });
    const window = dom.window;
    window.HTMLElement.prototype.scrollIntoView = () => {};
    window.fetch = async () => ({ ok: !fail, json: async () => data });
    window.eval(script); await tick();
    return { dom, doc: window.document };
}

test("seeded dashboard shows correct counts, six map regions and Westbridge alert", async () => {
    const { dom, doc } = await setup();
    assert.equal(doc.getElementById("reportCount").textContent, "65");
    assert.equal(doc.getElementById("alertCount").textContent, "1");
    assert.equal(doc.getElementById("occupiedCount").textContent, "8,000");
    assert.equal(doc.querySelectorAll(".district").length, 6);
    assert.equal(doc.querySelectorAll(".chart-row").length, 6);
    assert.equal(doc.getElementById("districtTitle").textContent, "Westbridge");
    assert.match(doc.getElementById("predictionRange").textContent, /37–105/);
    assert.match(doc.getElementById("districtContext").textContent, /Outage/);
    dom.window.close();
});

test("map can be selected by keyboard and shows damage layer", async () => {
    const { dom, doc } = await setup();
    const east = doc.querySelector('[data-region="eastbank"]');
    east.dispatchEvent(new dom.window.KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    assert.equal(doc.getElementById("districtTitle").textContent, "Eastbank");
    assert.equal(east.getAttribute("aria-pressed"), "true");
    doc.getElementById("mapLayer").value = "damage";
    doc.getElementById("mapLayer").dispatchEvent(new dom.window.Event("change"));
    assert.match(east.querySelector(".map-count").textContent, /65\/100 damage index/);
    dom.window.close();
});

test("scored demo reports are visible by default and can be filtered by district", async () => {
    const { dom, doc } = await setup();
    assert.equal(doc.querySelectorAll("#reportRows tr").length, 65);
    assert.match(doc.getElementById("reportsCaption").textContent, /65 scored fictional demo reports/);
    doc.getElementById("showFixtures").checked = true;
    doc.getElementById("showFixtures").dispatchEvent(new dom.window.Event("change"));
    assert.equal(doc.querySelectorAll("#reportRows tr").length, 65);
    doc.querySelector('[data-region="eastbank"]').dispatchEvent(new dom.window.Event("click"));
    doc.getElementById("filterDistrict").click();
    assert.equal(doc.querySelectorAll("#reportRows tr").length, 18);
    doc.querySelector("#reportRows button").click();
    assert.equal(doc.getElementById("reportDetails").hidden, false);
    assert.match(doc.getElementById("reportDetailsBody").textContent, /Self-reported urgency/);
    dom.window.close();
});

test("a form report can be inspected and filtered by priority", async () => {
    const data = clone(fixture);
    data.reports.push({ report_id: "form-1", region_id: "westbridge", household_id: "fictional-westbridge-household-0001", source: "fictional_community_form", verification_status: "unverified", submitted_at: data.assessment_time, created_at: "2026-10-01T04:00:00+00:00", priority: { priority: "Critical", score: 9.1 }, model_report: { people_affected: 4, immediate_danger: true, urgency: 10, vulnerability_count: 3, high_risk_vulnerabilities: [], needs: ["water"], shelter_status: "unsafe", responder_access: "no" } });
    const { dom, doc } = await setup(data);
    assert.match(doc.getElementById("reportRows").textContent, /Critical/);
    doc.getElementById("reportDistrict").value = "westbridge";
    doc.getElementById("reportDistrict").dispatchEvent(new dom.window.Event("change"));
    doc.querySelector("#reportRows button").click();
    assert.match(doc.getElementById("reportDetailsBody").textContent, /weighted baseline/);
    assert.match(doc.getElementById("reportDetailsBody").textContent, /water/);
    doc.getElementById("priorityFilter").value = "Low";
    doc.getElementById("priorityFilter").dispatchEvent(new dom.window.Event("change"));
    assert.match(doc.getElementById("reportRows").textContent, /No reports match/);
    dom.window.close();
});

test("an unavailable feed is labelled unknown rather than zero", async () => {
    const data = clone(fixture); const west = data.area_information_gaps.find(row => row.region_id === "westbridge");
    west.classification = "Insufficient data"; west.alert = false; west.context.report_feed_complete = false;
    delete west.expected_reports; delete west.expected_range_90;
    const { dom, doc } = await setup(data);
    doc.querySelector('[data-region="westbridge"]').dispatchEvent(new dom.window.Event("click"));
    assert.equal(doc.getElementById("selectedReceived").textContent, "Unknown");
    assert.equal(doc.getElementById("reportCount").textContent, "Partial data");
    assert.equal(doc.getElementById("expectedCount").textContent, "Unavailable");
    dom.window.close();
});

test("initial API failure leaves counts unknown", async () => {
    const { dom, doc } = await setup(undefined, true);
    assert.equal(doc.getElementById("reportCount").textContent, "—");
    assert.equal(doc.getElementById("errorBanner").hidden, false);
    assert.match(doc.getElementById("errorBanner").textContent, /counts are unknown/);
    dom.window.close();
});

test("refresh failure marks retained results stale", async () => {
    const { dom, doc } = await setup();
    dom.window.fetch = async () => { throw new Error("Offline"); };
    doc.getElementById("refresh").click(); await tick();
    assert.equal(doc.body.dataset.stale, "true");
    assert.equal(doc.getElementById("reportCount").textContent, "65");
    assert.match(doc.getElementById("errorBanner").textContent, /may be stale/);
    dom.window.close();
});

test("report text is rendered as text rather than interpreted HTML", async () => {
    const data = clone(fixture); data.area_information_gaps[0].reason = '<img src=x onerror="alert(1)">';
    const { dom, doc } = await setup(data);
    doc.querySelector('[data-region="central"]').dispatchEvent(new dom.window.Event("click"));
    assert.match(doc.getElementById("districtReason").textContent, /<img/);
    assert.equal(doc.querySelector("#districtReason img"), null);
    dom.window.close();
});
