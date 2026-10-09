// Short form behaviour tests. Run: npm install; npm test.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");
const root = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(root, "frontend", "evac_form.html"), "utf8");
const script = fs.readFileSync(path.join(root, "frontend", "form.js"), "utf8");
const population = JSON.parse(fs.readFileSync(path.join(root, "datasets", "riverford", "population.json")));
const tick = () => new Promise(resolve => setImmediate(resolve));

async function setup(post, contextOK = true, url = "http://127.0.0.1:5000/") {
    const dom = new JSDOM(html, { url, runScripts: "outside-only" });
    const window = dom.window;
    window.HTMLElement.prototype.scrollIntoView = () => {};
    const calls = [];
    window.fetch = async (url, options) => {
        if (!options) return { ok: contextOK, json: async () => ({ regions: population, hours_since_earthquake: 2 }) };
        calls.push({ url, payload: JSON.parse(options.body) });
        return post ? post() : { ok: true, status: 201, json: async () => ({ status: "received", report_id: "example-001" }) };
    };
    window.eval(script);
    await tick();
    const doc = window.document;
    doc.getElementById("region_id").value = "westbridge";
    doc.getElementById("region_id").dispatchEvent(new window.Event("change"));
    doc.getElementById("household_number").value = "1";
    for (const id of ["report-household", "people4", "dangerYes", "vulnerability3", "limitedMobility", "water", "rescue", "shelterUnsafe", "accessNo"]) {
        doc.getElementById(id).checked = true;
    }
    const submit = () => doc.getElementById("reportForm").dispatchEvent(new window.Event("submit", { cancelable: true }));
    return { dom, doc, calls, submit };
}

test("district options and household limits come from backend context", async () => {
    const { dom, doc } = await setup();
    assert.equal(doc.querySelectorAll("#region_id option").length, 7);
    assert.equal(doc.getElementById("household_number").max, "1680");
    assert.match(doc.getElementById("scenarioTime").textContent, /2 hours/);
    assert.equal(doc.querySelector('button[type="submit"]').disabled, false);
    assert.notEqual(doc.getElementById("medical"), null);
    assert.notEqual(doc.querySelector('[name="vulnerability_count"]'), null);
    assert.notEqual(doc.querySelector('[name="high_risk_vulnerabilities"]'), null);
    dom.window.close();
});

test("valid submission preserves checkbox arrays and shows receipt only", async () => {
    const { dom, doc, calls, submit } = await setup();
    submit(); await tick();
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, "/api/reports");
    assert.deepEqual(calls[0].payload.primary_needs, ["rescue_evacuation", "water"]);
    assert.equal(calls[0].payload.region_id, "westbridge");
    assert.equal(calls[0].payload.household_number, "1");
    assert.equal(calls[0].payload.people_affected, "4+");
    assert.equal(calls[0].payload.vulnerability_count, "3+");
    assert.deepEqual(calls[0].payload.high_risk_vulnerabilities, ["limited_mobility"]);
    assert.equal(doc.getElementById("status").dataset.state, "success");
    assert.match(doc.getElementById("status").textContent, /Reference: example-001/);
    assert.equal(doc.getElementById("water").checked, true);
    dom.window.close();
});

test("empty needs do not send a request", async () => {
    const { dom, doc, calls, submit } = await setup();
    for (const input of doc.querySelectorAll('[name="needs"]')) input.checked = false;
    submit(); await tick();
    assert.equal(calls.length, 0);
    assert.equal(doc.getElementById("status").dataset.state, "error");
    dom.window.close();
});

test("invalid household number does not send a request", async () => {
    const { dom, doc, calls, submit } = await setup();
    doc.getElementById("household_number").value = "1681";
    submit(); await tick();
    assert.equal(calls.length, 0);
    dom.window.close();
});

test("API validation failure preserves answers and allows retry", async () => {
    const { dom, doc, submit } = await setup(() => ({ ok: false, status: 422, json: async () => ({ error: "Example validation error" }) }));
    submit(); await tick();
    assert.equal(doc.getElementById("status").dataset.state, "error");
    assert.match(doc.getElementById("status").textContent, /Example validation error/);
    assert.equal(doc.getElementById("household_number").value, "1");
    assert.equal(doc.querySelector('button[type="submit"]').disabled, false);
    dom.window.close();
});

test("network failure preserves answers and never claims success", async () => {
    const { dom, doc, submit } = await setup(() => { throw new Error("Offline"); });
    submit(); await tick();
    assert.equal(doc.getElementById("status").dataset.state, "error");
    assert.match(doc.getElementById("status").textContent, /Could not confirm/);
    assert.equal(doc.getElementById("water").checked, true);
    dom.window.close();
});

test("a pending request blocks repeat clicks", async () => {
    let resolvePost;
    const pending = new Promise(resolve => { resolvePost = resolve; });
    const { dom, doc, calls, submit } = await setup(() => pending);
    submit(); submit();
    assert.equal(calls.length, 1);
    assert.equal(doc.querySelector('button[type="submit"]').disabled, true);
    resolvePost({ ok: true, status: 201, json: async () => ({ status: "received", report_id: "example-002" }) });
    await tick();
    assert.equal(doc.getElementById("status").dataset.state, "success");
    dom.window.close();
});

test("unavailable context leaves submission disabled", async () => {
    const { dom, doc, calls, submit } = await setup(null, false);
    submit(); await tick();
    assert.equal(calls.length, 0);
    assert.equal(doc.getElementById("status").dataset.state, "error");
    assert.equal(doc.querySelector('button[type="submit"]').disabled, true);
    dom.window.close();
});

test("opening HTML as a file gives application URL guidance", async () => {
    const { dom, doc, calls, submit } = await setup(null, true, "file:///example/evac_form.html");
    submit(); await tick();
    assert.equal(calls.length, 0);
    assert.match(doc.getElementById("status").textContent, /127.0.0.1:5000/);
    dom.window.close();
});
