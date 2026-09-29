/* TURNUP / MilestoSmiles — dependency-free demo surface. */

const state = {
  horizon: 24,
  ran: false,
  imported: false,
  intervals: [],
  jobs: [
    { id: "fine-tuning", name: "AI model fine-tuning", type: "Interruptible", energy: 12, earliest: 0, deadline: 8, maxPower: 6, accent: "lime", slots: [] },
    { id: "embeddings", name: "Embedding generation", type: "Interruptible", energy: 5, earliest: 0, deadline: 12, maxPower: 4, accent: "teal", slots: [] },
    { id: "inference", name: "Batch inference", type: "Interruptible", energy: 8, earliest: 8, deadline: 18, maxPower: 5, accent: "teal", slots: [] },
    { id: "backup", name: "Database backup", type: "Continuous", energy: 3, earliest: 1, deadline: 6, maxPower: 2, accent: "orange", slots: [] },
    { id: "video", name: "Video processing", type: "Interruptible", energy: 10, earliest: 10, deadline: 23, maxPower: 4, accent: "teal", slots: [] }
  ],
  siteCapacity: 20
};

const $ = (selector) => document.querySelector(selector);

function formatMWh(value) { return `${value.toFixed(value < 10 ? 1 : 0)} MWh`; }
function formatMW(value) { return `${value.toFixed(1)} MW`; }
function formatHour(hour) { return `${String(Math.floor(hour) % 24).padStart(2, "0")}:${hour % 1 ? "30" : "00"}`; }

function buildDemoIntervals() {
  const intervals = [];
  for (let i = 0; i < 48; i += 1) {
    const hour = i / 2;
    const daylight = Math.max(0, Math.sin(((hour - 5.5) / 14) * Math.PI));
    const evening = Math.max(0, Math.sin(((hour - 16) / 8) * Math.PI));
    const wind = 12 + 9 * Math.sin((hour + 2) / 3.5) + 3.2 * Math.cos(hour / 2.6);
    const solar = 2 + daylight * 20;
    const renewable = Math.max(6, wind + solar);
    const load = 17 + evening * 3.5 + 1.4 * Math.sin((hour - 7) / 2.1) + (hour < 6 ? -2.3 : 0);
    const price = 72 + 35 * evening - 52 * daylight - 10 * Math.sin((hour + 1) / 2.5);
    const residual = Math.max(1, load - renewable);
    const opportunity = Math.max(0, Math.min(1, (renewable - load + 13) / 29 + Math.sin(hour * 1.7) * .055));
    const probability = Math.max(0.03, Math.min(.97, opportunity * .82 + (hour >= 10 && hour <= 16 ? .13 : 0)));
    const expectedCurtailment = Math.max(0, probability * (renewable * .095) - residual * .012);
    intervals.push({ i, hour, wind, solar, renewable, load, baseline: 9.5 + 2.3 * evening + .5 * Math.sin(hour / 1.9), price, residual, opportunity, probability, expectedCurtailment, scheduled: 0 });
  }
  return intervals;
}

function getVisibleIntervals() {
  return state.intervals.slice(0, Math.round(state.horizon * 2));
}

function resetJobs() {
  state.jobs.forEach((job) => { job.slots = []; });
}

function scoreInterval(interval, job) {
  const deadlineUrgency = Math.max(0, 1 - ((job.deadline - interval.hour) / Math.max(1, job.deadline - job.earliest)));
  const priceScore = Math.max(0, Math.min(1, (120 - interval.price) / 180));
  return interval.opportunity * .52 + interval.probability * .24 + priceScore * .14 + deadlineUrgency * .1;
}

function runScheduler() {
  resetJobs();
  const horizon = getVisibleIntervals();
  horizon.forEach((interval) => { interval.scheduled = 0; });
  const sortedJobs = [...state.jobs].sort((a, b) => a.deadline - b.deadline);
  for (const job of sortedJobs) {
    let remaining = job.energy;
    const eligible = horizon.filter((interval) => interval.hour >= job.earliest && interval.hour < job.deadline)
      .sort((a, b) => scoreInterval(b, job) - scoreInterval(a, job));
    for (const interval of eligible) {
      if (remaining <= .001) break;
      const available = Math.max(0, state.siteCapacity - interval.baseline - interval.scheduled);
      const power = Math.min(job.maxPower, available, remaining / .5);
      if (power <= .05) continue;
      interval.scheduled += power;
      remaining -= power * .5;
      job.slots.push({ hour: interval.hour, power, score: scoreInterval(interval, job) });
    }
    job.remaining = Math.max(0, remaining);
  }
  state.ran = true;
  renderAll();
}

function canvasSize(canvas) {
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * ratio));
  canvas.height = Math.max(1, Math.floor(rect.height * ratio));
  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);
  return { ctx, width: rect.width, height: rect.height };
}

function drawChart() {
  const canvas = $("#opportunityChart");
  if (!canvas) return;
  const { ctx, width, height } = canvasSize(canvas);
  const data = getVisibleIntervals();
  const pad = { top: 11, right: 6, bottom: 16, left: 4 };
  const chartW = width - pad.left - pad.right;
  const chartH = height - pad.top - pad.bottom;
  const maxRenewable = Math.max(...data.map((d) => d.renewable), 40) * 1.08;
  const x = (i) => pad.left + (i / Math.max(1, data.length - 1)) * chartW;
  const y = (value) => pad.top + chartH - (value / maxRenewable) * chartH;
  ctx.clearRect(0, 0, width, height);
  ctx.strokeStyle = "rgba(202,242,218,.1)";
  ctx.lineWidth = 1;
  for (let g = 0; g < 4; g += 1) { const gy = pad.top + (g / 3) * chartH; ctx.beginPath(); ctx.moveTo(pad.left, gy); ctx.lineTo(width - pad.right, gy); ctx.stroke(); }

  // Opportunity ribbon.
  ctx.beginPath();
  data.forEach((item, i) => { const px = x(i); const py = pad.top + chartH - item.opportunity * chartH * .86; i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py); });
  data.forEach((item, i) => { const px = x(data.length - 1 - i); const py = pad.top + chartH; i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py); });
  ctx.closePath(); ctx.fillStyle = "rgba(255,155,98,.10)"; ctx.fill();

  // Renewable generation area.
  ctx.beginPath(); data.forEach((item, i) => { const px = x(i); const py = y(item.renewable); i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py); });
  ctx.lineTo(x(data.length - 1), y(0)); ctx.lineTo(x(0), y(0)); ctx.closePath();
  const gradient = ctx.createLinearGradient(0, pad.top, 0, height); gradient.addColorStop(0, "rgba(184,243,110,.30)"); gradient.addColorStop(1, "rgba(184,243,110,.015)"); ctx.fillStyle = gradient; ctx.fill();
  ctx.beginPath(); data.forEach((item, i) => { const px = x(i); const py = y(item.renewable); i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py); }); ctx.strokeStyle = "#b8f36e"; ctx.lineWidth = 2; ctx.stroke();

  // Opportunity score trace.
  ctx.beginPath(); data.forEach((item, i) => { const px = x(i); const py = pad.top + chartH - item.opportunity * chartH * .86; i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py); }); ctx.strokeStyle = "#ff9b62"; ctx.lineWidth = 1.5; ctx.setLineDash([3, 4]); ctx.stroke(); ctx.setLineDash([]);

  if (state.ran) {
    data.forEach((item, i) => { if (item.scheduled <= 0) return; const px = x(i); ctx.beginPath(); ctx.arc(px, pad.top + chartH - 7, 3.2, 0, Math.PI * 2); ctx.fillStyle = "#56cfbf"; ctx.fill(); });
  }
  const labels = $("#axisLabels"); labels.innerHTML = "";
  [0, Math.floor(data.length * .25), Math.floor(data.length * .5), Math.floor(data.length * .75), data.length - 1].forEach((index) => { const span = document.createElement("span"); span.textContent = formatHour(data[index].hour); labels.appendChild(span); });
}

function renderKpis() {
  const data = getVisibleIntervals();
  const jobsComplete = state.ran ? state.jobs.filter((job) => (job.remaining || 0) < .01).length : 0;
  const potential = state.ran ? data.reduce((sum, item) => sum + Math.min(item.expectedCurtailment, item.scheduled * .5), 0) : data.reduce((sum, item) => sum + item.expectedCurtailment * .35, 0);
  const peak = Math.max(...data.map((item) => item.baseline + item.scheduled), 0);
  const confidence = state.ran ? Math.round(85 + jobsComplete * 2) : 78;
  $("#kpiEnergy").textContent = formatMWh(potential);
  $("#kpiPeak").textContent = formatMW(peak);
  $("#kpiPeakCaption").textContent = `limit ${formatMW(state.siteCapacity)}`;
  $("#kpiJobs").textContent = state.ran ? `${jobsComplete} / ${state.jobs.length}` : `— / ${state.jobs.length}`;
  $("#kpiConfidence").textContent = `${confidence}%`;
  $("#capacityFill").style.width = `${Math.min(100, (peak / state.siteCapacity) * 100)}%`;
  $("#confidenceRing").style.background = `conic-gradient(var(--acid) ${confidence * 3.6}deg, rgba(217,246,220,.11) 0deg)`;
  $("#confidenceRing span").textContent = `${confidence}%`;
  $("#jobDots").innerHTML = state.jobs.map((job) => `<i class="${job.remaining > .01 ? "off" : ""}"></i>`).join("");
}

function renderExplanations() {
  const list = $("#explanationList");
  const data = getVisibleIntervals();
  const selected = data.filter((item) => item.scheduled > 0).sort((a, b) => b.opportunity - a.opportunity).slice(0, 5);
  const top = selected.length ? selected : [...data].sort((a, b) => b.opportunity - a.opportunity).slice(0, 5);
  $("#traceCount").textContent = `${selected.length} / ${state.jobs.length}`;
  list.innerHTML = top.map((item, index) => {
    const reason = item.price < 45 ? "low price + renewable surplus" : item.renewable > item.load ? "renewables exceed residual load" : "high forecast opportunity";
    return `<div class="explanation-item"><span class="explanation-rank">0${index + 1}</span><div class="explanation-copy"><strong>${formatHour(item.hour)} · ${reason}</strong><span>${Math.round(item.probability * 100)}% event probability · ${formatMW(item.renewable)} renewable supply</span></div><span class="explanation-score">${Math.round(item.opportunity * 100)} score</span></div>`;
  }).join("");
  $("#chartSummary").textContent = state.ran ? `${selected.length} high-value windows selected; baseline and deadlines remain protected.` : "The scheduler is looking for the cleanest windows.";
}

function renderJobs() {
  const rows = $("#workloadRows");
  rows.innerHTML = state.jobs.map((job) => {
    const status = !state.ran ? "READY" : (job.remaining || 0) < .01 ? "PROTECTED" : "NEEDS REVIEW";
    const slots = job.slots.slice(0, 4).map((slot) => `<span class="slot-pill">${formatHour(slot.hour)}</span>`).join("") || `<span class="slot-pill">—</span>`;
    return `<tr><td><strong>${job.name}</strong><small>${job.type}</small></td><td>${job.energy} MWh</td><td>${formatHour(job.earliest)} – ${formatHour(job.deadline)}</td><td>${job.maxPower} MW</td><td><span class="job-status ${status === "PROTECTED" ? "" : status === "READY" ? "ready" : "pending"}"><i>●</i> ${status}</span></td><td><div class="slot-pills">${slots}</div></td></tr>`;
  }).join("");
}

function renderAll() { renderKpis(); renderExplanations(); renderJobs(); drawChart(); }

function parseCsv(text) {
  const lines = text.trim().split(/\r?\n/).filter(Boolean);
  if (lines.length < 2) throw new Error("CSV has no data rows");
  const headers = lines.shift().split(",").map((item) => item.trim().toLowerCase());
  const indexOf = (names) => names.map((name) => headers.indexOf(name)).find((index) => index >= 0);
  const timeIndex = indexOf(["timestamp_utc", "timestamp", "datetime"]);
  const renewableIndex = indexOf(["total_renewable_mw", "renewable_mw"]);
  const windActualIndex = indexOf(["wind_actual_mw"]);
  const solarActualIndex = indexOf(["solar_actual_mw"]);
  const loadIndex = indexOf(["load_actual_mw", "load_mw", "load_forecast_mw"]);
  const priceIndex = indexOf(["price_eur_per_mwh", "price"]);
  const curtailmentIndex = indexOf(["system_curtailment_mwh", "curtailment_mwh"]);
  const modelProbabilityIndex = indexOf(["model_event_probability"]);
  const modelExpectedIndex = indexOf(["model_expected_curtailment_mwh"]);
  const heuristicIndex = indexOf(["heuristic_opportunity_score"]);
  if (timeIndex === undefined || loadIndex === undefined || (renewableIndex === undefined && windActualIndex === undefined)) throw new Error("Required columns: timestamp_utc, renewable (or wind_actual_mw) and load");
  const parsed = lines.map((line, row) => {
    const values = line.split(",").map((item) => item.trim());
    const date = new Date(values[timeIndex]);
    if (Number.isNaN(date.valueOf())) throw new Error(`Invalid timestamp on row ${row + 2}`);
    const wind = windActualIndex === undefined ? 0 : Number(values[windActualIndex]) || 0;
    const solar = solarActualIndex === undefined ? 0 : Number(values[solarActualIndex]) || 0;
    const renewable = renewableIndex === undefined ? wind + solar : Number(values[renewableIndex]); const load = Number(values[loadIndex]);
    if (!Number.isFinite(renewable) || !Number.isFinite(load)) throw new Error(`Invalid grid values on row ${row + 2}`);
    const price = priceIndex === undefined ? 50 : Number(values[priceIndex]) || 50;
    const systemCurtailment = curtailmentIndex === undefined ? 0 : Number(values[curtailmentIndex]) || 0;
    const modelProbability = modelProbabilityIndex === undefined ? undefined : Number(values[modelProbabilityIndex]);
    const modelExpected = modelExpectedIndex === undefined ? undefined : Number(values[modelExpectedIndex]);
    const modelOpportunity = heuristicIndex === undefined ? undefined : Number(values[heuristicIndex]);
    const opportunity = Number.isFinite(modelOpportunity) ? Math.max(0, Math.min(1, modelOpportunity)) : Math.max(0, Math.min(1, (renewable - load + 13) / 29));
    const probability = Number.isFinite(modelProbability) ? Math.max(0, Math.min(1, modelProbability)) : (systemCurtailment > 0 ? .8 : .12);
    const expectedCurtailment = Number.isFinite(modelExpected) ? Math.max(0, modelExpected) : systemCurtailment;
    return { i: row, hour: date.getHours() + date.getMinutes() / 60, wind: renewable, solar: 0, renewable, load, baseline: 9.5, price, residual: Math.max(1, load - renewable), opportunity, probability, expectedCurtailment, actualCurtailment: systemCurtailment, signalSource: Number.isFinite(modelExpected) ? "TURNUP model" : "label/demo", scheduled: 0 };
  });
  return parsed.slice(0, 96);
}

async function loadAuditedDataset() {
  const button = $("#loadAudited");
  button.disabled = true;
  try {
    const response = await fetch("data/processed/turnup_scored_30min.csv", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const parsed = parseCsv(await response.text());
    if (!parsed.length) throw new Error("No usable rows found");
    state.intervals = parsed; state.horizon = Math.min(48, Math.floor(parsed.length / 2)); state.imported = true; state.ran = false; resetJobs();
    $("#horizonSelect").value = String(state.horizon); $("#importStatus").textContent = `TURNUP model-scored EirGrid join loaded — ${parsed.length} intervals. Run the schedule to score this horizon.`; renderAll();
  } catch (error) { $("#importStatus").textContent = `Could not load audited join: ${error.message}`; }
  finally { button.disabled = false; }
}

$("#runSchedule").addEventListener("click", runScheduler);
$("#loadAudited").addEventListener("click", loadAuditedDataset);
$("#resetDemo").addEventListener("click", () => { state.intervals = buildDemoIntervals(); state.ran = false; state.imported = false; resetJobs(); $("#importStatus").textContent = "Demo data is active. No external data has been uploaded."; renderAll(); });
$("#horizonSelect").addEventListener("change", (event) => { state.horizon = Number(event.target.value); state.ran = false; resetJobs(); renderAll(); });
$("#csvInput").addEventListener("change", async (event) => {
  const file = event.target.files[0]; if (!file) return;
  try { const parsed = parseCsv(await file.text()); if (!parsed.length) throw new Error("No usable rows found"); state.intervals = parsed; state.horizon = Math.min(48, Math.floor(parsed.length / 2)); $("#horizonSelect").value = String(state.horizon); state.imported = true; state.ran = false; resetJobs(); $("#importStatus").textContent = `${file.name} loaded — ${parsed.length} intervals. Run the schedule to score this horizon.`; renderAll(); }
  catch (error) { $("#importStatus").textContent = `Could not load CSV: ${error.message}`; }
});
window.addEventListener("resize", drawChart);
state.intervals = buildDemoIntervals();
renderAll();
