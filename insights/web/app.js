let DAYS = "30";
let lastOk = 0;
let pricingCache = {models:{}};
let costByModel = {};
let includeCR = false;
let projections = {}; // actual model -> selected pricing model name
let lastCost = null;
let lastActivity = null;
let lastOpencode = null;
let lastClaudecode = null;
let lastAntigravity = null;
let lastSummary = null;
let lastModels = null;
let flowShowCR = false;
let costSource = "c6"; // 'c6' | 'opencode' | 'claudecode' | 'antigravity' | 'all' (default C6)

// TASK7: top source bar — five sources in fixed order, labels for the picker.
const SOURCE_DEFS = [
  {src: "c6", label: "C6 (Hermes)"},
  {src: "opencode", label: "opencode"},
  {src: "claudecode", label: "claude code"},
  {src: "antigravity", label: "antigravity"},
  {src: "all", label: "all"},
];

function sumBilled(models){
  let t = 0;
  for(const m of (models||[])) t += Number(m.billed_tokens||0);
  return t;
}

// Billable tokens per source for the current window (TASK7 §2).
function sourceBilled(src){
  const c6 = Number((lastSummary && lastSummary.billed_tokens)||0);
  const op = sumBilled(lastOpencode && lastOpencode.models);
  const cc = sumBilled(lastClaudecode && lastClaudecode.models);
  const ag = sumBilled(lastAntigravity && lastAntigravity.models);
  if(src === "c6") return c6;
  if(src === "opencode") return op;
  if(src === "claudecode") return cc;
  if(src === "antigravity") return ag;
  return c6 + op + cc + ag; // all
}

// Normalized summary per selected source for KPI cards.
function summaryForSource(src){
  const c6Summary = lastSummary || {};
  if(src === "c6"){
    return {
      billed_tokens: Number(c6Summary.billed_tokens || 0),
      input_tokens: Number(c6Summary.input_tokens || 0),
      output_tokens: Number(c6Summary.output_tokens || 0),
      cache_read_tokens: Number(c6Summary.cache_read_tokens || c6Summary.cache_tokens || 0),
      sessions: Number(c6Summary.sessions || 0),
      messages: c6Summary.messages != null ? Number(c6Summary.messages) : null,
      user_messages: c6Summary.user_messages != null ? Number(c6Summary.user_messages) : null,
      tool_calls: c6Summary.tool_calls != null ? Number(c6Summary.tool_calls) : null,
    };
  }
  if(src === "opencode" || src === "claudecode" || src === "antigravity"){
    const obj = src === "opencode" ? lastOpencode : (src === "claudecode" ? lastClaudecode : lastAntigravity);
    const tot = (obj && obj.total) || {};
    const models = (obj && obj.models) || [];
    return {
      billed_tokens: sumBilled(models),
      input_tokens: Number(tot.input_tokens || 0),
      output_tokens: Number(tot.output_tokens || 0),
      cache_read_tokens: Number(tot.cache_read_tokens || 0),
      sessions: Number((obj && obj.sessions) || 0),
      messages: null,
      user_messages: null,
      tool_calls: null,
    };
  }
  // "all"
  const c6s = summaryForSource("c6");
  const ops = summaryForSource("opencode");
  const ccs = summaryForSource("claudecode");
  const ags = summaryForSource("antigravity");
  return {
    billed_tokens: c6s.billed_tokens + ops.billed_tokens + ccs.billed_tokens + ags.billed_tokens,
    input_tokens: c6s.input_tokens + ops.input_tokens + ccs.input_tokens + ags.input_tokens,
    output_tokens: c6s.output_tokens + ops.output_tokens + ccs.output_tokens + ags.output_tokens,
    cache_read_tokens: c6s.cache_read_tokens + ops.cache_read_tokens + ccs.cache_read_tokens + ags.cache_read_tokens,
    sessions: c6s.sessions + ops.sessions + ccs.sessions + ags.sessions,
    messages: c6s.messages,
    user_messages: c6s.user_messages,
    tool_calls: c6s.tool_calls != null ? c6s.tool_calls : null,
  };
}

// Models for the selected source:
// For 'c6' and 'all', use the all-source d.models (C6 models live in /api/models; 'all' shows all-source list).
// For 'opencode', 'claudecode', 'antigravity', use the dedicated per-source .models array.
function modelsForSource(src){
  let rows = [];
  if(src === "opencode") rows = (lastOpencode && lastOpencode.models) || [];
  else if(src === "claudecode") rows = (lastClaudecode && lastClaudecode.models) || [];
  else if(src === "antigravity") rows = (lastAntigravity && lastAntigravity.models) || [];
  else rows = (lastModels && lastModels.models) || [];
  for(const r of rows){
    if(r && r.model) ensureProjection(r.model);
  }
  return rows;
}

function renderModelsForSource(){
  renderModels(modelsForSource(costSource));
}

// Build the #source-pick buttons once (labels + count spans), then update
// counts + active state on every render.
function buildSourceBar(){
  const host = document.getElementById("source-pick");
  if(!host || host.childElementCount) return;
  for(const d of SOURCE_DEFS){
    const b = document.createElement("button");
    b.setAttribute("data-src", d.src);
    if(d.src === costSource) b.classList.add("active");
    const lbl = document.createElement("span");
    lbl.className = "lbl";
    lbl.textContent = d.label;
    const num = document.createElement("span");
    num.className = "num srccount";
    num.setAttribute("data-count", d.src);
    num.textContent = "—";
    b.appendChild(lbl);
    b.appendChild(num);
    b.addEventListener("click", ()=>handleSourceSelect(d.src));
    host.appendChild(b);
  }
}

function updateSourceCounts(){
  buildSourceBar();
  document.querySelectorAll("#source-pick button").forEach(b=>{
    b.classList.toggle("active", b.getAttribute("data-src") === costSource);
  });
  for(const d of SOURCE_DEFS){
    const el = document.querySelector(`#source-pick [data-count="${d.src}"]`);
    if(el) el.textContent = compact(sourceBilled(d.src));
  }
}

// Single shared handler for the top bar: re-filter cost panel + headline,
// KPI cards, models table, and flow chart.
function handleSourceSelect(src){
  costSource = src;
  document.querySelectorAll("#source-pick button").forEach(x=>x.classList.toggle("active", x.getAttribute("data-src") === src));
  renderModelsForSource();
  if(lastCost){ renderCost(lastCost); }
  const head = updateCostHeadline();
  renderKPIs(summaryForSource(src), head);
  renderFlowForSource();
}

const $ = (id) => document.getElementById(id);

function compact(n){
  n = Number(n||0);
  if (n >= 1e6) return (n/1e6).toFixed(1)+"M";
  if (n >= 1e3) return (n/1e3).toFixed(1)+"K";
  return String(Math.round(n));
}
function full(n){ return Number(n||0).toLocaleString("en-US"); }
function money(x){ return "$"+Number(x||0).toFixed(2); }
function esc(s){
  return String(s??"").replace(/[&<>"']/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
function hhmmss(ts){
  try{ const d=new Date(ts*1000); return d.toLocaleTimeString("en-GB",{hour12:false}); }
  catch{ return "—"; }
}
function ymd(ts){
  try{ const d=new Date(ts*1000); const m=String(d.getMonth()+1).padStart(2,"0");
    const dd=String(d.getDate()).padStart(2,"0"); return `${d.getFullYear()}-${m}-${dd}`; }
  catch{ return ""; }
}
function ageStr(ts){
  const s = Math.max(0, Math.floor(Date.now()/1000 - ts));
  if (s < 60) return s+"s ago";
  if (s < 3600) return Math.floor(s/60)+"m ago";
  return Math.floor(s/3600)+"h ago";
}

async function getJSON(path){
  const r = await fetch(path, {cache:"no-store"});
  if(!r.ok) throw new Error(path+" "+r.status);
  return r.json();
}

async function refresh(){
  const q = "?days="+encodeURIComponent(DAYS);
  let data;
  try{
    const [summary, models, tools, skills, activity, cost, pricing, opencode, claudecode, antigravity] = await Promise.all([
      getJSON("/api/summary"+q), getJSON("/api/models"+q),
      getJSON("/api/tools"+q), getJSON("/api/skills"+q), getJSON("/api/activity"+q),
      getJSON("/api/cost"+q), getJSON("/api/pricing"), getJSON("/api/opencode"+q),
      getJSON("/api/claudecode"+q), getJSON("/api/antigravity"+q),
    ]);
    data = {summary, models, tools, skills, activity, cost, pricing, opencode, claudecode, antigravity};
  }catch(e){
    $("offline").style.display = "block";
    $("livedot").className = "dot off";
    $("livetext").textContent = "OFFLINE";
    setTimeout(refresh, 5000);
    return;
  }
  $("offline").style.display = "none";
  render(data);
  lastOk = Date.now()/1000;
  const gen = data.summary.generated_at || Date.now()/1000;
  $("updated").textContent = hhmmss(gen);
  const stale = (Date.now()/1000 - gen) > 90;
  $("livedot").className = "dot"+(stale?" stale":"");
  $("livetext").textContent = stale ? "STALE" : "LIVE";
  $("foot-age").textContent = "updated "+ageStr(gen);
  // flash
  const k = $("kpis");
  k.classList.remove("flash"); void k.offsetWidth; k.classList.add("flash");
  // empty state
  $("empty").style.display = (data.summary.sessions===0) ? "block" : "none";
}

// ---------- cost projection helpers (TASK3) ----------

function rateFor(name){
  const models = pricingCache.models||{};
  const m = models[name];
  if(m && typeof m.input === "number" && typeof m.output === "number") return m;
  // TASK4 rule: opencode: prefix never matches pricing (free-tier).
  if(String(name||"").toLowerCase().startsWith("opencode:")) return null;
  // TASK5 rule: claudecode:/antigravity: strip the prefix, match the
  // remainder against pricing keys AND `also` aliases (mirror of server).
  const stripped = stripSourcePrefix(name);
  if(stripped !== null){
    const key = pricingKeyFor(stripped);
    if(key){
      const e = models[key];
      if(e && typeof e.input === "number" && typeof e.output === "number") return e;
    }
  }
  return null;
}

// Strip claudecode:/antigravity: for pricing lookup; null = no stripping.
function stripSourcePrefix(name){
  const s = String(name||"");
  const l = s.toLowerCase();
  if(l.startsWith("claudecode:") || l.startsWith("antigravity:")) return s.slice(s.indexOf(":")+1);
  return null;
}

// Canonical pricing key for a bare model id (case-insensitive key or alias).
function pricingKeyFor(base){
  const models = pricingCache.models||{};
  const low = String(base).toLowerCase();
  for(const k of Object.keys(models)){ if(k.toLowerCase()===low) return k; }
  for(const [k,e] of Object.entries(models)){
    const also = (e && e.also)||[];
    if(also.some(a=>String(a).toLowerCase()===low)) return k;
  }
  return null;
}

// Default projection for a cost row (TASK3+5+6):
// - claude code rows with reported cost default to actual (reported) — the
//   real billed $. Zero/missing reported falls back to the stripped pricing
//   key estimate (marked estimate) so it never looks free.
// - antigravity rows default to the pricing key their stripped id resolves
//   to (API-rate estimate). opencode rows stay unpriced (—).
function isClaudecodeModel(name){
  return String(name||"").toLowerCase().startsWith("claudecode:");
}
function reportedOf(row){
  const v = row ? Number(row.reported_cost_usd||0) : 0;
  return (isFinite(v) && v > 0) ? v : (Number(row && row.reported_cost_usd)||0);
}
function hasReportedCost(row){
  return Number(row && row.reported_cost_usd||0) > 0;
}
function ensureProjection(actual){
  if(actual in projections) return;
  const row = (typeof costByModel !== "undefined" && costByModel[actual]) || null;
  if(isClaudecodeModel(actual)){
    const rep = row ? Number(row.reported_cost_usd||0) : 0;
    if(rep > 0){
      projections[actual] = actual; // actual (reported) — real billed $
      return;
    }
    // — reported (no cost-state data): fall back to estimate as default.
    const stripped = stripSourcePrefix(actual);
    if(stripped !== null){
      const key = pricingKeyFor(stripped);
      if(key){ projections[actual] = key; return; }
    }
    projections[actual] = actual;
    return;
  }
  const stripped = stripSourcePrefix(actual);
  if(stripped !== null){
    const key = pricingKeyFor(stripped);
    if(key){ projections[actual] = key; return; }
  }
  projections[actual] = actual;
}

// billable = in*in + out*out + cw*cw (+ cr*cr iff includeCR)
function projectedCost(row, targetName){
  const r = rateFor(targetName);
  if(!r) return {cost: null, priced: false, rates: null};
  const inp = row.input_tokens||0, outp = row.output_tokens||0;
  const cw = row.cache_write_tokens||0, cr = row.cache_read_tokens||0;
  const rin = Number(r.input||0), rout = Number(r.output||0);
  const rcw = Number(r.cache_write||0), rcr = Number(r.cache_read||0);
  let c = (inp*rin + outp*rout + cw*rcw)/1e6;
  if(includeCR) c += (cr*rcr)/1e6;
  return {cost: c, priced: true, rates: r};
}

function selectedFor(actual){
  return projections[actual] || actual;
}

// Effective model for KPI + flow tooltip: dominant row's current selection.
// Default = dominant actual model.
function visibleCostRows(){
  const h = (lastCost && lastCost.models) || [];
  const o = (lastOpencode && lastOpencode.models) || [];
  const cc = (lastClaudecode && lastClaudecode.models) || [];
  const ag = (lastAntigravity && lastAntigravity.models) || [];
  if(costSource === "c6") return h.map(r=>({...r, _src:"c6"}));
  if(costSource === "opencode") return o.map(r=>({...r, _src:"opencode"}));
  if(costSource === "claudecode") return cc.map(r=>({...r, _src:"claudecode"}));
  if(costSource === "antigravity") return ag.map(r=>({...r, _src:"antigravity"}));
  return [...h.map(r=>({...r, _src:"c6"})), ...o.map(r=>({...r, _src:"opencode"})),
          ...cc.map(r=>({...r, _src:"claudecode"})), ...ag.map(r=>({...r, _src:"antigravity"}))];
}

function dominantRow(){
  const rows = visibleCostRows();
  if(!rows.length) return null;
  let best = rows[0];
  let bestB = (best.billed_tokens||0);
  for(const r of rows){
    const b = (r.billed_tokens||0);
    if(b > bestB){ best = r; bestB = b; }
  }
  return best;
}

// Effective model for KPI + flow tooltip: dominant VISIBLE row's selection.
function effectiveModelName(){
  const d = dominantRow();
  if(!d) return null;
  return selectedFor(d.model);
}

function activeDaysOf(cost){
  if(!cost) return 1;
  if(cost.active_days) return Math.max(1, cost.active_days);
  if(cost.per_day_usd) return Math.max(1, cost.total_usd / cost.per_day_usd);
  return 1;
}

function activeDaysForSource(){
  if(costSource === "c6") return activeDaysOf(lastCost);
  if(costSource === "opencode"){
    if(lastOpencode && lastOpencode.active_days) return Math.max(1, lastOpencode.active_days);
    const daily = (lastOpencode && lastOpencode.daily) || [];
    const n = daily.filter(dd=>((dd.input_tokens||0)+(dd.output_tokens||0))>0).length;
    return Math.max(1, n);
  }
  if(costSource === "claudecode" || costSource === "antigravity"){
    const src = costSource === "claudecode" ? lastClaudecode : lastAntigravity;
    if(src && src.active_days) return Math.max(1, src.active_days);
    const daily = (src && src.daily) || [];
    const n = daily.filter(dd=>((dd.input_tokens||0)+(dd.output_tokens||0))>0).length;
    return Math.max(1, n);
  }
  // all -> union of active dates across all four series
  const hs = new Set();
  const ad = (lastActivity && lastActivity.daily) || [];
  for(const b of ad){ if(((b.input_tokens||0)+(b.output_tokens||0))>0) hs.add(b.date); }
  for(const s of [lastOpencode, lastClaudecode, lastAntigravity]){
    const dd = (s && s.daily) || [];
    for(const b of dd){ if(((b.input_tokens||0)+(b.output_tokens||0))>0) hs.add(b.date); }
  }
  if(hs.size) return hs.size;
  // fallback: max of the four
  return Math.max(activeDaysOf(lastCost),
    (lastOpencode && lastOpencode.active_days) ? lastOpencode.active_days : 1,
    (lastClaudecode && lastClaudecode.active_days) ? lastClaudecode.active_days : 1,
    (lastAntigravity && lastAntigravity.active_days) ? lastAntigravity.active_days : 1, 1);
}

// TASK6: effective cost for one row. Claude code rows in reported mode
// (selection == actual) contribute the REAL billed $; projected rows (and all
// other sources) contribute the pay-per-token estimate.
function effectiveRowCost(row){
  const model = row.model;
  const sel = selectedFor(model);
  const cc = (row._src === "claudecode") || isClaudecodeModel(model);
  if(cc && sel === model){
    const rep = Number(row.reported_cost_usd||0);
    if(rep > 0) return {cost: rep, priced: true, reported: true};
    return {cost: 0, priced: false, reported: true, empty: true};
  }
  const pc = projectedCost(row, sel);
  if(pc.priced) return {cost: pc.cost, priced: true, reported: false, rates: pc.rates};
  return {cost: 0, priced: false, reported: false};
}

// Recompute panel totals from current projections + includeCR flag (source-filtered).
// TASK6: `all` source — claude code rows contribute reported cost, others existing.
function recomputeTotals(){
  const rows = visibleCostRows();
  let total = 0, unpriced = 0;
  for(const row of rows){
    const eff = effectiveRowCost(row);
    if(eff.reported){
      if(eff.priced) total += eff.cost;
      else unpriced += (row.billed_tokens||0);
    }else{
      if(eff.priced) total += eff.cost;
      else unpriced += (row.billed_tokens||0);
    }
  }
  return {total, unpriced};
}

function updateCostHeadline(){
  if(!lastCost && !lastOpencode) return;
  const {total, unpriced} = recomputeTotals();
  const ad = activeDaysForSource();
  const perDay = total / ad;
  $("cost-total").textContent = money(total);
  $("cost-perday").textContent = money(perDay);
  $("cost-unpriced").textContent = full(unpriced)+" tok";
  const lbl = costSource === "c6" ? "C6 (Hermes)" : costSource === "opencode" ? "opencode" :
    costSource === "claudecode" ? "claude code" : costSource === "antigravity" ? "antigravity" : "all";
  const suffix = costSource === "opencode" ? "opencode models are free-tier via opencode-go — unpriced until projected" :
    costSource === "claudecode" ? "reported cost = what Claude Code bills · pick a model in a row to see a pay-per-token estimate" :
    costSource === "antigravity" ? "plan-based · $ shown = pay-per-token API-rate estimate" :
    costSource === "all" ? "all four usage sources combined" :
    "hermes sessions";
  const sl = $("cost-src-label");
  if(sl) sl.textContent = `usage source: ${lbl} · ${suffix}`;
  return {total, perDay, unpriced, ad};
}

// Flow series for the selected source (TASK4+6). Returns daily shaped like
// activity.daily plus TASK6 reported fields for claude code.
function flowSeriesForSource(){
  const c6daily = (lastActivity && lastActivity.daily) || [];
  const norm = (od)=> (od||[]).map(b=>({
    date: b.date, sessions: b.sessions||0,
    input_tokens: b.input_tokens||0, output_tokens: b.output_tokens||0,
    cache_read_tokens: b.cache_read_tokens||0, cache_write_tokens: b.cache_write_tokens||0,
    total_tokens: (b.input_tokens||0)+(b.output_tokens||0)+(b.cache_read_tokens||0)+(b.cache_write_tokens||0),
    reported_cost_usd: Number(b.reported_cost_usd||0),
    has_reported_cost: !!b.has_reported_cost,
  }));
  const opd = norm(lastOpencode && lastOpencode.daily);
  const ccd = norm(lastClaudecode && lastClaudecode.daily);
  const agd = norm(lastAntigravity && lastAntigravity.daily);
  if(costSource === "opencode") return opd;
  if(costSource === "claudecode") return ccd;
  if(costSource === "antigravity") return agd;
  if(costSource === "c6") return c6daily;
  // all -> combined by date
  const byDate = {};
  for(const b of c6daily){
    byDate[b.date] = byDate[b.date] || {date:b.date, sessions:0, input_tokens:0, output_tokens:0, cache_read_tokens:0, cache_write_tokens:0, total_tokens:0};
    const e = byDate[b.date];
    e.sessions += (b.sessions||0); e.input_tokens += (b.input_tokens||0);
    e.output_tokens += (b.output_tokens||0); e.cache_read_tokens += (b.cache_read_tokens||0);
    e.cache_write_tokens += (b.cache_write_tokens||0); e.total_tokens += (b.total_tokens||0);
  }
  for(const b of [...opd, ...ccd, ...agd]){
    byDate[b.date] = byDate[b.date] || {date:b.date, sessions:0, input_tokens:0, output_tokens:0, cache_read_tokens:0, cache_write_tokens:0, total_tokens:0};
    const e = byDate[b.date];
    e.sessions += (b.sessions||0); e.input_tokens += (b.input_tokens||0);
    e.output_tokens += (b.output_tokens||0); e.cache_read_tokens += (b.cache_read_tokens||0);
    e.cache_write_tokens += (b.cache_write_tokens||0); e.total_tokens += (b.total_tokens||0);
  }
  const keys = Object.keys(byDate).sort();
  // keep the C6 window ordering when possible (activity.daily order)
  if(c6daily.length && keys.length === c6daily.length){
    const order = {};
    c6daily.forEach((b,i)=>order[b.date]=i);
    keys.sort((a,b)=>(order[a]??0)-(order[b]??0));
  }
  return keys.map(k=>byDate[k]);
}

function render(d){
  const s = d.summary, cost = d.cost;
  pricingCache = d.pricing || {models:{}};
  lastSummary = s;
  lastCost = cost;
  lastModels = d.models;
  lastActivity = d.activity;
  lastOpencode = d.opencode || null;
  lastClaudecode = d.claudecode || null;
  lastAntigravity = d.antigravity || null;
  costByModel = {};
  for(const m of (cost.models||[])) costByModel[m.model] = m;
  for(const m of ((lastOpencode && lastOpencode.models)||[])) costByModel[m.model] = m;
  for(const m of ((lastClaudecode && lastClaudecode.models)||[])) costByModel[m.model] = m;
  for(const m of ((lastAntigravity && lastAntigravity.models)||[])) costByModel[m.model] = m;
  // keep projections for rows that still exist; defaults via ensureProjection
  // (plan-usage rows default to their stripped pricing key so they show $).
  for(const m of (cost.models||[])) ensureProjection(m.model);
  for(const m of ((lastOpencode && lastOpencode.models)||[])) ensureProjection(m.model);
  for(const m of ((lastClaudecode && lastClaudecode.models)||[])) ensureProjection(m.model);
  for(const m of ((lastAntigravity && lastAntigravity.models)||[])) ensureProjection(m.model);
  // drop projections for vanished rows
  for(const k of Object.keys(projections)){
    if(!costByModel[k]) delete projections[k];
  }
  // sync top source-bar UI + per-source billable counts (window-aware)
  updateSourceCounts();

  renderFlowForSource();
  renderModelsForSource();
  renderTools(d.tools);
  renderActivity(d.activity);
  renderSkills(d.skills);
  renderCost(cost);

  // KPIs — EST. COST/D is window-aware and projection-aware; must agree with panel.
  const head = updateCostHeadline();
  renderKPIs(summaryForSource(costSource), head);
}

function renderKPIs(summaryObj, costHead){
  const s = summaryObj || summaryForSource(costSource);
  const head = costHead || updateCostHeadline();
  if(!head) return;

  const hitDenom = Math.max(1, (s.input_tokens||0) + (s.cache_read_tokens||0));
  const hit = (s.cache_read_tokens||0) / hitDenom * 100;
  const eff = effectiveModelName() || "—";
  const daysLbl = (DAYS === "all") ? "all" : (DAYS+"d");
  let costCell = money(head.perDay)+" /d";
  let costSub = `at ${eff} · ${daysLbl}`;
  try{
    if(costSource === "claudecode"){
      const dr = dominantRow();
      if(dr && selectedFor(dr.model) === dr.model && Number(dr.reported_cost_usd||0) > 0){
        costSub = `reported · ${daysLbl}`;
      }else if(dr && selectedFor(dr.model) !== dr.model){
        costSub = `at ${eff} (estimate) · ${daysLbl}`;
      }
    }else if(costSource === "all"){
      // all: claude portion is reported; keep dominant-model label but flag estimate rows.
      const dr = dominantRow();
      if(dr && (dr._src === "claudecode" || isClaudecodeModel(dr.model)) && selectedFor(dr.model) !== dr.model){
        costSub = `at ${eff} (estimate) · ${daysLbl}`;
      }
    }
  }catch{}
  if(!head.total && head.unpriced){
    costCell = "$0.00* /d";
    costSub = `* unpriced — see cost panel · ${daysLbl}`;
  }

  const sessionsSub = (s.messages != null && s.user_messages != null)
    ? `${full(s.messages)} msgs · ${full(s.user_messages)} user${costSource === "all" ? " (C6)" : ""}`
    : "msgs: — (not reported for this source)";

  const toolCallsVal = s.tool_calls != null ? full(s.tool_calls) : "—";
  const toolCallsSub = s.tool_calls != null
    ? (costSource === "all" ? "reconciled (C6 only)" : "reconciled")
    : "not reported for this source";

  const kpis = [
    ["TOKENS (BILLABLE)", compact(s.billed_tokens), `in ${compact(s.input_tokens)} · out ${compact(s.output_tokens)}`, true],
    ["CACHE RE-READS", compact(s.cache_read_tokens||0), "model re-reading cached context — not billable", false],
    ["SESSIONS", full(s.sessions), sessionsSub, false],
    ["TOOL CALLS", toolCallsVal, toolCallsSub, false],
    ["CACHE HIT RATE", hit.toFixed(1)+"%", "cache read / input-side", false],
    ["EST. COST / D", costCell, costSub, true],
  ];
  $("kpis").innerHTML = kpis.map(k=>`<div class="kpi"><div class="micro">${k[0]}</div><div class="v${k[3]?" accent":" num"}">${esc(k[1])}</div><div class="sub">${esc(k[2])}</div></div>`).join("");
}

function dayCostAtRates(b, rates){
  if(!rates) return null;
  const inp=b.input_tokens||0, outp=b.output_tokens||0;
  const cw=b.cache_write_tokens||0, cr=b.cache_read_tokens||0;
  let c=(inp*Number(rates.input||0)+outp*Number(rates.output||0)+cw*Number(rates.cache_write||0))/1e6;
  if(includeCR) c+=(cr*Number(rates.cache_read||0))/1e6;
  return c;
}

function renderFlowForSource(){
  const daily = flowSeriesForSource();
  const srcLbl = costSource === "c6" ? "C6 (Hermes)" : costSource === "opencode" ? "opencode" :
    costSource === "claudecode" ? "claude code" : costSource === "antigravity" ? "antigravity" : "all";
  renderFlowDaily(daily, srcLbl);
}

function renderFlow(act){
  // legacy entry (TASK3): render the passed activity daily (C6)
  const daily = (act && act.daily) || [];
  renderFlowDaily(daily, "C6 (Hermes)");
}

function renderFlowDaily(dailyIn, srcLbl){
  const svg = $("flow"), tip = $("flow-tip");
  const daily = dailyIn || [];
  // bucket: 30d daily, 90/all weekly (7d/1d stay daily)
  let buckets = daily.map(x=>({...x}));
  let typeLbl = flowShowCR ? "input / output / cache read" : "input / output";
  let label = "daily tokens · " + typeLbl + " · src " + (srcLbl||"");
  if(DAYS==="90" || DAYS==="all"){
    const out=[];
    for(let i=0;i<daily.length;i+=7){
      const chunk=daily.slice(i,i+7);
      const agg={date:chunk[0].date+"→"+chunk[chunk.length-1].date,
        sessions:0,input_tokens:0,output_tokens:0,cache_read_tokens:0,cache_write_tokens:0,total_tokens:0,
        reported_cost_usd:0,has_reported_cost:false};
      for(const c of chunk){ agg.sessions+=c.sessions; agg.input_tokens+=c.input_tokens||0;
        agg.output_tokens+=c.output_tokens||0; agg.cache_read_tokens+=c.cache_read_tokens||0;
        agg.cache_write_tokens+=c.cache_write_tokens||0;
        agg.total_tokens+=c.total_tokens||0;
        agg.reported_cost_usd+=(Number(c.reported_cost_usd)||0);
        if(c.has_reported_cost) agg.has_reported_cost=true; }
      out.push(agg);
    }
    buckets = out;
    label = "weekly buckets · " + typeLbl + " · src " + (srcLbl||"");
  }
  const flowSub = $("flow-sub");
  if(flowSub) flowSub.textContent = label;

  const W=1000,H=240,PL=56,PB=26,PT=10,PR=10;
  const iw=W-PL-PR, ih=H-PT-PB;
  const maxV = Math.max(1, ...buckets.map(b=>{
    const inp = b.input_tokens || 0;
    const outp = b.output_tokens || 0;
    if(flowShowCR){
      const cr = b.cache_read_tokens || 0;
      return Math.max(inp, outp, cr);
    }
    return Math.max(inp, outp);
  }));

  const n = Math.max(1, buckets.length);
  const y = (v)=> PT + ih - (v/maxV)*ih;

  // gridlines: 4 ticks
  let g="";
  for(let t=0;t<=4;t++){
    const v=maxV*t/4, yy=y(v);
    g+=`<line x1="${PL}" y1="${yy}" x2="${W-PR}" y2="${yy}" stroke="rgba(255,255,255,0.07)"/>`+
       `<text x="${PL-6}" y="${yy+4}" fill="#6a6b72" font-size="11" text-anchor="end">${compact(v)}</text>`;
  }

  // grouped bars per bucket
  const slotW = iw / n;
  const numSeries = flowShowCR ? 3 : 2;
  const groupW = Math.max(numSeries, slotW * 0.7);
  const barGap = 1;
  const subW = Math.max(1, (groupW - (numSeries - 1) * barGap) / numSeries);
  const actualGroupW = numSeries * subW + (numSeries - 1) * barGap;

  let barsSvg = "";
  for(let i=0; i<n; i++){
    const b = buckets[i];
    const cx = PL + (i + 0.5) * slotW;
    const groupLeft = cx - actualGroupW / 2;

    const inp = b.input_tokens || 0;
    const outp = b.output_tokens || 0;
    const cr = b.cache_read_tokens || 0;

    const yIn = y(inp), hIn = Math.max(0, (PT + ih) - yIn);
    const xIn = groupLeft;
    barsSvg += `<rect x="${xIn.toFixed(1)}" y="${yIn.toFixed(1)}" width="${subW.toFixed(1)}" height="${hIn.toFixed(1)}" fill="#ff5a5a" rx="1"/>`;

    const yOut = y(outp), hOut = Math.max(0, (PT + ih) - yOut);
    const xOut = groupLeft + (subW + barGap);
    barsSvg += `<rect x="${xOut.toFixed(1)}" y="${yOut.toFixed(1)}" width="${subW.toFixed(1)}" height="${hOut.toFixed(1)}" fill="#5aa9e6" rx="1"/>`;

    if(flowShowCR){
      const yCr = y(cr), hCr = Math.max(0, (PT + ih) - yCr);
      const xCr = groupLeft + 2 * (subW + barGap);
      barsSvg += `<rect x="${xCr.toFixed(1)}" y="${yCr.toFixed(1)}" width="${subW.toFixed(1)}" height="${hCr.toFixed(1)}" fill="#5ad6a0" rx="1"/>`;
    }
  }

  const overlays = buckets.map((b,i)=>{
    const cx = PL + (i + 0.5) * slotW;
    const lbl = buckets.length>14 ? (i%4===0?b.date.slice(5):"") : b.date.slice(5);
    const topY = Math.min(y(b.input_tokens||0), y(b.output_tokens||0), flowShowCR ? y(b.cache_read_tokens||0) : PT + ih);
    return `<text x="${cx.toFixed(1)}" y="${H-6}" fill="#6a6b72" font-size="10" text-anchor="middle">${esc(lbl)}</text>`+
      `<circle data-i="${i}" cx="${cx.toFixed(1)}" cy="${topY.toFixed(1)}" r="10" fill="transparent">`+
      `<title>${esc(b.date)} in ${full(b.input_tokens)} out ${full(b.output_tokens)} cr ${full(b.cache_read_tokens)}</title></circle>`+
      `<rect data-i="${i}" x="${(PL + i * slotW).toFixed(1)}" y="${PT}" width="${slotW.toFixed(1)}" height="${ih}" fill="transparent" style="cursor:crosshair"/>`;
  }).join("");

  svg.innerHTML = g + barsSvg + overlays;

  svg.querySelectorAll("[data-i]").forEach(c=>{
    c.style.cursor="crosshair";
    c.addEventListener("mousemove",(ev)=>{
      const b=buckets[+c.getAttribute("data-i")];
      let costLine;
      // TASK6: claude code hover uses REPORTED by default.
      if(costSource === "claudecode"){
        if(b.has_reported_cost){
          const rv = Number(b.reported_cost_usd||0);
          costLine = rv > 0 ? `≈ ${money(rv)} reported` : `≈ — reported`;
        }else{
          // no cost-state on this day: fall back to estimate with marker.
          const effName = effectiveModelName();
          const rates = effName ? rateFor(effName) : null;
          const dc = rates ? dayCostAtRates(b, rates) : null;
          if(dc === null || !rates) costLine = `≈ — (unpriced)`;
          else costLine = `≈ ${money(dc)} at ${effName} rates (estimate)`;
        }
      }else{
        // daily cost at currently selected projection model's rates
        const effName = effectiveModelName();
        const rates = effName ? rateFor(effName) : null;
        const dc = rates ? dayCostAtRates(b, rates) : null;
        if(dc === null || !rates) costLine = `≈ — (unpriced)`;
        else costLine = `≈ ${money(dc)} at ${effName} rates`;
      }
      tip.style.display="block";
      tip.textContent=`${b.date}\n sessions ${b.sessions}\n in ${full(b.input_tokens)} · out ${full(b.output_tokens)} · cr ${full(b.cache_read_tokens)}\n${costLine}`;
      const r=svg.getBoundingClientRect();
      tip.style.left=Math.min(r.width-220, ev.clientX-r.left+14)+"px";
      tip.style.top=(ev.clientY-r.top-10)+"px";
    });
    c.addEventListener("mouseleave",()=>tip.style.display="none");
  });
}

function renderModels(m){
  const rows = Array.isArray(m) ? m : ((m && m.models) || []);
  const maxT = Math.max(1, ...rows.map(r=>(r.billed_tokens||r.total_tokens)||0));
  const tb = document.querySelector("#models tbody");
  tb.innerHTML = rows.map(r=>{
    const c = costByModel[r.model];
    const eff = effectiveRowCost(r);
    const costTxt = (eff && eff.priced) ? money(eff.cost) : ((c && c.priced) ? money(c.cost_usd) : "—");
    const billed = r.billed_tokens != null ? r.billed_tokens : (r.total_tokens || 0);
    const pct = ((billed)/maxT*100).toFixed(1);
    const prov = r.provider ? ` · <span style="color:var(--faint)">${esc(r.provider)}</span>` : "";
    const cr = r.cache_read_tokens||0;
    const sess = r.sessions != null ? full(r.sessions) : "—";
    const canAdd = (!eff || !eff.priced) && (!c || !c.priced);
    return `<tr><td><span class="num">${esc(r.model)}</span>${prov}</td>`+
      `<td style="min-width:120px"><div class="bar"><i style="width:${pct}%"></i></div></td>`+
      `<td class="num">${sess}</td><td class="num" title="billable = in+out+cache-write · +${compact(cr)} cache re-reads (free)">${compact(billed)}</td>`+
      `<td class="num">${costTxt}</td>`+
      `<td>${canAdd ? `<button class="btn small" data-add="${esc(r.model)}">+</button>` : ""}</td></tr>`;
  }).join("") || `<tr><td colspan="6" style="color:var(--faint)">no models</td></tr>`;
  tb.querySelectorAll("[data-add]").forEach(b=>b.addEventListener("click",()=>{
    openEditor(b.getAttribute("data-add"));
  }));
}

function renderTools(t){
  const items=(t.tools||[]).slice(0,10);
  const maxC=Math.max(1,...items.map(x=>x.count||0));
  $("tools").innerHTML = items.map(x=>{
    const pct=((x.count||0)/maxC*100).toFixed(1);
    return `<div style="display:flex;gap:10px;align-items:center;margin:7px 0">`+
      `<div class="num" style="width:130px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(x.tool)}">${esc(x.tool)}</div>`+
      `<div class="bar steel" style="flex:1"><i style="width:${pct}%"></i></div>`+
      `<div class="num" style="width:64px;text-align:right">${full(x.count)}</div></div>`;
  }).join("") || `<div style="color:var(--faint)">none</div>`;
}

function renderActivity(a){
  const hours=$("hours");
  const maxH=Math.max(1,...(a.by_hour||[]));
  hours.innerHTML=(a.by_hour||[]).map((c,h)=>{
    const pct=(c/maxH*100).toFixed(1);
    const hot = (h===a.busiest_hour)?" hot":"";
    return `<div class="hb${hot}" title="${String(h).padStart(2,"0")}:00 — ${c} sessions" style="height:${Math.max(3,pct)}%"></div>`;
  }).join("");
  const dayNames=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];
  const bd=a.busiest_day||"—";
  $("callouts").innerHTML =
    `<span>busiest day <b>${esc(bd)}</b></span><span>busiest hour <b>${String(a.busiest_hour??0).padStart(2,"0")}:00</b></span>`+
    `<span>active days <b>${full(a.active_days)}</b></span><span>streak <b>${full(a.max_streak)}d</b></span>`+
    `<span>weekday <b>${esc(dayNames[new Date().getDay()==0?6:new Date().getDay()-1]||"")}</b> mix: ${(a.by_day||[]).join("/")}</span>`;
  const tb=document.querySelector("#tops tbody");
  const labelFmt={longest:"longest",most_messages:"most messages",most_tokens:"most tokens",most_tool_calls:"most tool calls"};
  tb.innerHTML=(a.top_sessions||[]).map(t=>{
    let v=t.value;
    if(t.label==="longest"){ v = Math.round(v)+"s"; }
    else v = full(v);
    return `<tr><td class="micro">${esc(labelFmt[t.label]||t.label)}</td><td class="num">${esc(v)}</td><td class="num">${esc(t.date)}</td><td class="trunc" title="${esc(t.title)}">${esc((t.title||"").slice(0,60))}</td></tr>`;
  }).join("") || `<tr><td colspan="4" style="color:var(--faint)">none</td></tr>`;
}

function renderSkills(s){
  const sum=s.summary||{loads:0,edits:0,distinct:0};
  $("skill-summary").innerHTML=`<span>loads <b>${full(sum.loads)}</b></span><span>edits <b>${full(sum.edits)}</b></span><span>distinct <b>${full(sum.distinct)}</b></span>`;
  document.querySelector("#skills tbody").innerHTML=(s.skills||[]).map(r=>{
    const lu = r.last_used_at? ymd(r.last_used_at)+" "+hhmmss(r.last_used_at):"—";
    return `<tr><td class="num">${esc(r.skill)}</td><td class="num">${full(r.view_count)}</td><td class="num">${full(r.manage_count)}</td><td class="num">${esc(lu)}</td></tr>`;
  }).join("") || `<tr><td colspan="4" style="color:var(--faint)">no skill usage</td></tr>`;
}

// Group pricing models by provider for <optgroup>: alphabetical providers,
// within a provider alphabetical model name.
function pricingGroups(){
  const models = pricingCache.models||{};
  const byProv = {};
  for(const [name, e] of Object.entries(models)){
    const p = (e && e.provider) ? String(e.provider) : "(unlabelled)";
    if(!byProv[p]) byProv[p]=[];
    byProv[p].push(name);
  }
  for(const p of Object.keys(byProv)) byProv[p].sort((a,b)=>a.localeCompare(b));
  return Object.keys(byProv).sort((a,b)=>a.localeCompare(b)).map(p=>({provider:p, names:byProv[p]}));
}

function projectSelectHTML(actual){
  const sel = selectedFor(actual);
  const groups = pricingGroups();
  const cc = isClaudecodeModel(actual);
  const row = (typeof costByModel !== "undefined" && costByModel[actual]) || null;
  const rep = row ? Number(row.reported_cost_usd||0) : 0;
  let h = `<select data-proj="${esc(actual)}" title="project usage onto another model's rates">`;
  if(cc){
    // TASK6: claude code dropdown DEFAULT is actual (reported) — the real $.
    // Zero/missing reported still offers "— reported" but defaults to estimate.
    if(rep > 0){
      h += `<option value="${esc(actual)}"${sel===actual?" selected":""}>${esc(actual)} (reported)</option>`;
    }else{
      h += `<option value="${esc(actual)}"${sel===actual?" selected":""}>— reported</option>`;
    }
  }else{
    // If actual model itself is not in pricing, offer it as an explicit
    // (unpriced) default so the row reads "—" until projected.
    const isActualPriced = !!rateFor(actual);
    if(!isActualPriced){
      h += `<option value="${esc(actual)}"${sel===actual?" selected":""}>${esc(actual)} (unpriced)</option>`;
    }
  }
  for(const g of groups){
    h += `<optgroup label="${esc(g.provider)}">`;
    for(const name of g.names){
      const r = rateFor(name);
      const tip = r ? `in $${r.input}/M · out $${r.output}/M` : "";
      h += `<option value="${esc(name)}"${sel===name?" selected":""} title="${esc(tip)}">${esc(name)}</option>`;
    }
    h += `</optgroup>`;
  }
  h += `</select>`;
  return h;
}

function costRowHTML(m){
    const sel = selectedFor(m.model);
    const cc = isClaudecodeModel(m.model);
    const inp = m.input_tokens||0, outp = m.output_tokens||0;
    const cr = m.cache_read_tokens||0;
    let costCell;
    if(cc){
      // TASK6: DEFAULT displayed cost = reported (real $).
      const rep = Number(m.reported_cost_usd||0);
      if(sel === m.model){
        if(rep > 0){
          costCell = `<span class="num" title="reported cost = what Claude Code bills">${money(rep)} · reported</span>`;
        }else{
          costCell = `<span class="num" title="no cost-state data for this model">— reported</span>`;
        }
      }else{
        const pc = projectedCost(m, sel);
        if(!pc.priced){
          costCell = `<span class="num">—</span>`;
        }else{
          const r = pc.rates;
          const tip = `pay-per-token estimate projected at ${sel} rates · in $${r.input}/M · out $${r.output}/M` +
            ((r.cache_read!==undefined)?` · cr $${r.cache_read}/M`:"") +
            ((r.cache_write!==undefined)?` · cw $${r.cache_write}/M`:"");
          costCell = `<span class="num proj" title="${esc(tip)}">${money(pc.cost)} → ${esc(sel)} (estimate)</span>`;
        }
      }
    }else{
      const pc = projectedCost(m, sel);
      const isProj = sel !== m.model;
      if(!pc.priced){
        costCell = `<span class="num">—</span>`;
      }else if(isProj){
        const r = pc.rates;
        const tip = `projected at ${sel} rates · in $${r.input}/M · out $${r.output}/M` +
          ((r.cache_read!==undefined)?` · cr $${r.cache_read}/M`:"") +
          ((r.cache_write!==undefined)?` · cw $${r.cache_write}/M`:"");
        costCell = `<span class="num proj" title="${esc(tip)}">${money(pc.cost)} → ${esc(sel)}</span>`;
      }else{
        const r = pc.rates;
        const tip = `in $${r.input}/M · out $${r.output}/M` +
          ((r.cache_read!==undefined)?` · cr $${r.cache_read}/M`:"") +
          ((r.cache_write!==undefined)?` · cw $${r.cache_write}/M`:"");
        costCell = `<span class="num" title="${esc(tip)}">${money(pc.cost)}</span>`;
      }
    }
    const crCell = `<span class="cr-muted" title="cache re-reads — process traffic, not billable by default">+${compact(cr)} cr</span>`;
    return `<tr><td class="num" title="${esc(m.model)}">${esc(m.model.length>42?m.model.slice(0,42)+"…":m.model)}</td>`+
      `<td class="num">${compact(inp)}</td><td class="num">${compact(outp)}</td>`+
      `<td>${costCell}</td>`+
      `<td>${projectSelectHTML(m.model)}</td>`+
      `<td class="num">${crCell}</td></tr>`;
}

// Section header row for non-C6 usage sources. Antigravity runs on a plan,
// so its section keeps the API-rate-estimate note. Claude Code (TASK6) shows
// reported cost by default.
function sectionHeadHTML(title, planBased){
  // TASK6 claude code header: new note + optional partial flag.
  const low = String(title||"").toLowerCase();
  if(low.includes("claude")){
    let flag = "";
    try{
      const tot = (lastClaudecode && lastClaudecode.total) || {};
      const unk = tot.has_unknown_model_cost || lastClaudecode.has_unknown_model_cost;
      if(unk) flag = ` · partial (unknown-model cost)`;
    }catch{}
    let h = `<tr><td colspan="6" class="micro" style="color:var(--muted)">— ${esc(title)} —${esc(flag)}</td></tr>`;
    h += `<tr><td colspan="6" class="micro" style="color:var(--faint)">reported cost = what Claude Code bills · pick a model in a row to see a pay-per-token estimate</td></tr>`;
    return h;
  }
  let h = `<tr><td colspan="6" class="micro" style="color:var(--muted)">— ${esc(title)} —</td></tr>`;
  if(planBased) h += `<tr><td colspan="6" class="micro" style="color:var(--faint)">plan-based · $ shown = pay-per-token API-rate estimate</td></tr>`;
  return h;
}

function sectionRowsHTML(rows, emptyTxt){
  return rows.map(costRowHTML).join("") || `<tr><td colspan="6" style="color:var(--faint)">${esc(emptyTxt)}</td></tr>`;
}

function renderCost(c){
  // headline from current projections (defaults = actuals), source-filtered
  updateCostHeadline();
  const tb=document.querySelector("#costs tbody");
  const hRows = (c && c.models) || [];
  const oRows = (lastOpencode && lastOpencode.models) || [];
  const ccRows = (lastClaudecode && lastClaudecode.models) || [];
  const agRows = (lastAntigravity && lastAntigravity.models) || [];
  let html = "";
  if(costSource === "c6"){
    html = sectionRowsHTML(hRows, "no usage");
  }else if(costSource === "opencode"){
    const head = `<tr><td colspan="6" class="micro" style="color:var(--muted)">opencode usage — free-tier via opencode-go · project onto a priced model to estimate</td></tr>`;
    html = head + sectionRowsHTML(oRows, "no opencode usage");
  }else if(costSource === "claudecode"){
    html = sectionHeadHTML("claude code usage", true) + sectionRowsHTML(ccRows, "no claude code usage");
  }else if(costSource === "antigravity"){
    html = sectionHeadHTML("antigravity usage", true) + sectionRowsHTML(agRows, "no antigravity usage");
  }else{
    html = sectionRowsHTML(hRows, "no usage")
      + sectionHeadHTML("opencode usage", false) + sectionRowsHTML(oRows, "no opencode usage")
      + sectionHeadHTML("claude code usage", true) + sectionRowsHTML(ccRows, "no claude code usage")
      + sectionHeadHTML("antigravity usage", true) + sectionRowsHTML(agRows, "no antigravity usage");
  }
  tb.innerHTML = html;
  // wire selects (client-side recompute; no refetch)
  tb.querySelectorAll("select[data-proj]").forEach(sel=>{
    sel.addEventListener("change",()=>{
      const actual = sel.getAttribute("data-proj");
      projections[actual] = sel.value;
      renderCost(lastCost);
      updateCostHeadline();
      refreshKPIOnly();
      renderFlowForSource();
      renderModelsForSource();
    });
  });
}

// Refresh only the KPI strip after a projection/toggle change (no refetch).
function refreshKPIOnly(){
  if(!lastCost && !lastOpencode) return;
  const head = updateCostHeadline();
  renderKPIs(summaryForSource(costSource), head);
}

// price editor — must preserve provider (and note/also + future fields)
function openEditor(prefill){
  $("price-editor").style.display="block";
  buildEditorRows(prefill);
  $("price-editor").scrollIntoView({behavior:"smooth",block:"nearest"});
}
function buildEditorRows(prefill){
  const models = pricingCache.models||{};
  // rows: existing pricing entries + all cost models missing pricing
  const names = new Set([...Object.keys(models)]);
  for(const m of Object.keys(costByModel)) names.add(m);
  if(prefill) names.add(prefill);
  const wrap=$("pe-rows"); wrap.innerHTML="";
  for(const name of [...names].sort()){
    if(!name) continue;
    const e=models[name]||{};
    const div=document.createElement("div");
    div.className="formgrid";
    div.innerHTML=`<div><label>${esc(name)}</label><input data-k="name" value="${esc(name)}" ${models[name]?"readonly":""}></div>`+
      `<div><label>input $/M</label><input data-k="input" type="number" step="0.01" min="0" value="${e.input??""}"></div>`+
      `<div><label>output $/M</label><input data-k="output" type="number" step="0.01" min="0" value="${e.output??""}"></div>`+
      `<div><label>cache_read $/M</label><input data-k="cache_read" type="number" step="0.001" min="0" value="${e.cache_read??""}"></div>`+
      `<div><label>cache_write $/M</label><input data-k="cache_write" type="number" step="0.001" min="0" value="${e.cache_write??""}"></div>`+
      `<div><button class="btn small" data-del="${esc(name)}">del</button></div>`;
    // stash extras (provider/note/also/...) so save preserves them
    div.dataset.extras = JSON.stringify(Object.fromEntries(
      Object.entries(e).filter(([k])=>!["input","output","cache_read","cache_write"].includes(k))
    ));
    wrap.appendChild(div);
  }
  // add-new row
  const add=document.createElement("div");
  add.className="formgrid";
  add.innerHTML=`<div><label>new model id</label><input data-k="name" placeholder="model-id"></div>`+
    `<div><label>input $/M</label><input data-k="input" type="number" step="0.01" min="0"></div>`+
    `<div><label>output $/M</label><input data-k="output" type="number" step="0.01" min="0"></div>`+
    `<div><label>cache_read $/M</label><input data-k="cache_read" type="number" step="0.001" min="0"></div>`+
    `<div><label>cache_write $/M</label><input data-k="cache_write" type="number" step="0.001" min="0"></div><div></div>`;
  add.id="pe-add";
  add.dataset.extras = "{}";
  wrap.appendChild(add);
  wrap.querySelectorAll("[data-del]").forEach(b=>b.addEventListener("click",()=>{
    b.closest(".formgrid").remove();
  }));
}

async function savePrices(){
  const rows=[...document.querySelectorAll("#pe-rows .formgrid")];
  const models={};
  for(const r of rows){
    const inp=(sel)=>r.querySelector(`[data-k="${sel}"]`)?.value?.trim()??"";
    const name=inp("name");
    if(!name) continue;
    // skip add-row if empty rates
    const si=inp("input"), so=inp("output"), scr=inp("cache_read"), scw=inp("cache_write");
    if(si==="" && so==="" && scr==="" && scw==="") continue;
    if(si===""||so===""){ $("pe-status").textContent="each kept row needs input+output"; return; }
    const e={input:Number(si), output:Number(so)};
    if(scr!=="") e.cache_read=Number(scr);
    if(scw!=="") e.cache_write=Number(scw);
    if(!(e.input>=0&&e.output>=0)){ $("pe-status").textContent="rates must be >=0"; return; }
    // preserve provider/note/also + any future extras
    try{
      const extras = JSON.parse(r.dataset.extras||"{}");
      for(const [k,v] of Object.entries(extras)) if(!(k in e)) e[k]=v;
    }catch{}
    models[name]=e;
  }
  $("pe-status").textContent="saving…";
  try{
    const r=await fetch("/api/pricing",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({models})});
    const j=await r.json();
    if(!r.ok){ $("pe-status").textContent="error: "+(j.error||r.status); return; }
    $("pe-status").textContent="saved";
    pricingCache={models};
    setTimeout(refresh, 300);
  }catch(e){ $("pe-status").textContent="error: "+e.message; }
}

document.querySelectorAll("#period button").forEach(b=>b.addEventListener("click",()=>{
  document.querySelectorAll("#period button").forEach(x=>x.classList.remove("active"));
  b.classList.add("active");
  DAYS=b.getAttribute("data-days");
  refresh();
}));
$("edit-prices").addEventListener("click",()=>{
  const ed=$("price-editor");
  if(ed.style.display==="none") openEditor();
  else ed.style.display="none";
});
$("pe-save").addEventListener("click", savePrices);
$("pe-cancel").addEventListener("click",()=>{ $("price-editor").style.display="none"; });
const _cr = document.getElementById("include-cr");
if(_cr) _cr.addEventListener("change",()=>{
  includeCR = _cr.checked;
  if(lastCost){ renderCost(lastCost); updateCostHeadline(); refreshKPIOnly(); }
  renderFlowForSource();
  renderModelsForSource();
});
const _flowCR = document.getElementById("flow-show-cr");
if(_flowCR) _flowCR.addEventListener("change",()=>{
  flowShowCR = _flowCR.checked;
  renderFlowForSource();
});
buildSourceBar();

refresh();
setInterval(refresh, 60000);
