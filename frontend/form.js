"use strict";
const form = document.getElementById("reportForm");
const statusBox = document.getElementById("status");
const submitButton = form.querySelector('button[type="submit"]');
const regionInput = document.getElementById("region_id");
const householdInput = document.getElementById("household_number");
const urgency = document.getElementById("urgency");
let districts = [];

function showStatus(message, state) {
    statusBox.textContent = message;
    statusBox.dataset.state = state;
    statusBox.style.display = "block";
    statusBox.scrollIntoView({ behavior: "smooth", block: "center" });
}

urgency.addEventListener("input", () => {
    document.getElementById("urgencyValue").textContent = urgency.value;
});

regionInput.addEventListener("change", () => {
    const district = districts.find(row => row.region_id === regionInput.value);
    householdInput.disabled = !district;
    householdInput.max = district ? String(district.occupied_households) : "";
    document.getElementById("householdHint").textContent = district
        ? `Use 1 to ${district.occupied_households}. Reuse the same number when updating a fictional household.`
        : "Choose a district first.";
});

async function initialise() {
    if (window.location.protocol === "file:") {
        showStatus("Open the form at http://127.0.0.1:5000 after starting Python.", "error");
        return;
    }
    try {
        const response = await fetch("/api/context");
        if (!response.ok) throw new Error("Context unavailable");
        const context = await response.json();
        if (!Array.isArray(context.regions) || !context.regions.length) throw new Error("Missing districts");
        districts = context.regions;
        for (const district of districts) {
            const option = document.createElement("option");
            option.value = district.region_id;
            option.textContent = district.region_name;
            regionInput.append(option);
        }
        document.getElementById("scenarioTime").textContent =
            `Demo snapshot: ${context.hours_since_earthquake} hours after the earthquake.`;
        submitButton.disabled = false;
    } catch (error) {
        showStatus("Could not load Riverford districts. Check the application and reload this page.", "error");
    }
}

form.addEventListener("submit", async event => {
    event.preventDefault();
    if (submitButton.disabled || !form.reportValidity()) return;
    const data = new FormData(form);
    const needs = data.getAll("needs");
    const highRiskVulnerabilities = data.getAll("high_risk_vulnerabilities");
    if (!needs.length) {
        showStatus("Select at least one type of help needed.", "error");
        document.querySelector('input[name="needs"]').focus();
        return;
    }
    const payload = {
        region_id: data.get("region_id"), household_number: data.get("household_number"),
        reporter_type: data.get("reporter_type"), people_affected: data.get("people_affected"),
        immediate_danger: data.get("immediate_danger"),
        self_reported_urgency: data.get("self_reported_urgency"),
        vulnerability_count: data.get("vulnerability_count"),
        high_risk_vulnerabilities: highRiskVulnerabilities, primary_needs: needs,
        shelter_status: data.get("shelter_status"), responder_access: data.get("responder_access")
    };
    submitButton.disabled = true;
    submitButton.textContent = "Submitting...";
    showStatus("Submitting your report...", "pending");
    try {
        const response = await fetch(form.getAttribute("action"), {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (!response.ok) {
            showStatus(result.error || "Could not save your report. Please retry.", "error");
        } else if (response.status !== 201 || result.status !== "received" || !result.report_id) {
            throw new Error("Unexpected response");
        } else {
            showStatus("Report received. Reference: " + result.report_id, "success");
        }
    } catch (error) {
        showStatus("Could not confirm submission. Your answers are still here. Check the connection before retrying.", "error");
    } finally {
        submitButton.disabled = false;
        submitButton.textContent = "Submit Report";
    }
});

initialise();
