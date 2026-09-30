'use strict';
let session = null, view = 'requests', runs = [], selected = null, detail = null, records = null, report = null;
let busy = false, stale = false;
let publicSample = null;
const $ = selector => document.querySelector(selector);
const e = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pretty = value => e(JSON.stringify(value, null, 2));
const words = value => String(value ?? '').replaceAll('_', ' ');
const money = (amount, currency = 'INR') => new Intl.NumberFormat('en-IN', {style:'currency',currency}).format(amount/100);
const stamp = value => value ? new Date(value).toLocaleString('en-IN', {dateStyle:'medium',timeStyle:'short'}) : '—';
const pill = mode => `<span class="pill ${e(mode)}">${e(mode === 'provider' ? 'LIVE PROVIDER' : mode.toUpperCase())}</span>`;
const status = state => `<span class="status ${e(state)}">${e(words(state))}</span>`;
function toast(message) { $('#toast').textContent = message; $('#toast').hidden = false; setTimeout(() => $('#toast').hidden = true, 6000); }
async function api(path, options = {}) {
  const response = await fetch('/api/v1' + path, {...options, headers:{'Content-Type':'application/json', ...(session ? {'X-CSRF-Token':session.csrf} : {}), ...options.headers}});
  const data = await response.json();
  if (!response.ok) { const error = new Error(data.error?.message || 'Service unavailable'); error.status = response.status; throw error; }
  return data;
}
async function login(role, password) {
  try { session = await api(password ? '/auth/login' : '/auth/demo/'+role, {method:'POST', body:password ? JSON.stringify({role,password}) : undefined}); $('#login-dialog').close(); detail = null; selected = null; updateAccount(); await refresh(); render(); } catch(error) { toast(error.message); }
}
function updateAccount() { $('#role-label').innerHTML = `${e(session?.role || 'Sign in')}<small>${session?.demo ? 'Isolated demo session' : 'Authenticated session'}</small>`; $('.avatar').textContent = session?.role?.slice(0,2).toUpperCase() || '?'; }
async function refresh() {
  if (!session) return;
  try {
    const [list, sandbox] = await Promise.all([api('/runs'), api('/sandbox')]);
    runs = list.items; records = sandbox; stale = false;
    $('#request-count').textContent = runs.length || '';
    $('#approval-count').textContent = runs.filter(r => r.status === 'awaiting_approval').length || '';
    if (selected) detail = await api('/runs/'+selected);
    $('#connection').textContent = '● Database connected';
  } catch(error) { stale = true; $('#connection').textContent = 'Stale data · retrying'; if(error.status === 401) { session = null; $('#login-dialog').showModal(); } }
}
function title(eyebrow, heading, subtitle, button = '') { return `<div class="page-title"><div><span class="eyebrow">${eyebrow}</span><h1>${heading}</h1><p>${subtitle}</p></div>${button}</div>`; }
function empty(heading, message, icon = '↗') { return `<div class="empty"><div class="empty-icon">${icon}</div><h3>${heading}</h3><p>${message}</p></div>`; }
function stat(label, value, note) { return `<div class="stat"><span class="stat-label">${label}<span>↗</span></span><strong>${e(value)}</strong><small>${note}</small></div>`; }
function render() {
  $('.nav.active')?.classList.remove('active'); $(`[data-view="${view}"]`)?.classList.add('active');
  $('#breadcrumb').innerHTML = `Workspace <span>/</span> ${e({requests:'Requests',approvals:'Approvals',sandbox:'Sandbox records',evaluation:'Evaluation'}[view])}`;
  if (!session) { $('#connection').textContent = publicSample ? 'Read-only public example' : 'Sign in to begin'; $('#content').innerHTML = title('SUPPORT, WITH CERTAINTY','Every resolution starts with evidence.','A reliable support operations agent. Inspect, clarify, review, resolve.') + (publicSample ? `<section class="panel"><div class="panel-head"><h3>Public example</h3>${pill(publicSample.mode)}</div><div class="panel-body"><div class="callout">Read-only walkthrough of fictional data. No investigation has been executed here.</div><div class="request-quote">${e(publicSample.example.request)}</div>${publicSample.example.steps.map((step,i)=>`<div class="observation"><div><small>STEP ${i+1}</small><h3>${e(words(step))}</h3></div></div>`).join('')}<button class="primary" data-signin>Sign in to run an investigation →</button></div></section>` : `<div class="panel">${empty('Your workspace is ready','Sign in to investigate fictional requests, or explore the public walkthrough.')}<div class="panel-body"><button class="primary" data-signin>Enter workspace →</button> <button class="secondary" data-sample>View public example →</button></div></div>`); return; }
  const warning = stale ? `<div class="callout">Connection interrupted. Showing the last observed state; actions will be revalidated by the server.</div>` : '';
  $('#content').innerHTML = warning + ({requests:renderRequests,approvals:renderApprovals,sandbox:renderSandbox,evaluation:renderEvaluation}[view])();
}
function renderRequests() {
  const waiting = runs.filter(r => ['awaiting_information','awaiting_approval'].includes(r.status)).length;
  return title('SUPPORT OPERATIONS','From request to resolution.','Investigate with evidence. Make every action reviewable.') +
    `<div class="stats">${stat('Requests in workspace',runs.length,'Actual persisted requests')}${stat('Awaiting a decision',waiting,'Information or supervisor approval')}${stat('Completed',runs.filter(r=>r.status==='completed').length,'Includes correct policy rejections')}${stat('Simulated effects',records?.effects.length || 0,'Committed sandbox ledger entries')}</div>
    <div class="split"><div><section class="panel"><div class="panel-head"><h3>New investigation</h3><span class="label-meta">01 / INTAKE</span></div><form id="new-request" class="panel-body">
    <div class="form-row"><label>Assigned customer<select name="customer_id">${(records?.customers||[]).map(c=>`<option value="${e(c.id)}">${e(c.name)}</option>`).join('')}</select></label><label>Execution mode<select name="mode"><option value="fixture">Fixture · scripted demo</option><option value="baseline">Baseline · fixed workflow</option><option value="provider" ${session.provider_enabled ? '' : 'disabled'}>Provider · real model</option></select></label></div>
    <label>Customer request<textarea name="message" required maxlength="4000" placeholder="My order ORD-1001 arrived damaged. Can I get a replacement?"></textarea></label>
    <details><summary>Add operator-recorded damage evidence</summary><div id="damage-fields"><label>Reported damage description<input name="damage_description" placeholder="Cracked lamp shade" maxlength="1000"></label><label>Report timestamp (ISO 8601)<input name="damage_reported_at" placeholder="2026-09-10T10:00:00+00:00"></label><label class="inline-check"><input name="photo_reviewed" type="checkbox">I reviewed a photo in the fictional sandbox</label></div></details>
    <div class="hint">The fixture replays scripted decisions. It demonstrates the workflow and makes no claim about model quality.</div><div class="form-footer"><span class="muted">All business effects are simulated</span><button class="primary" type="submit">Investigate <span>↗</span></button></div></form></section>
    <section class="panel"><div class="panel-head"><h3>Recent requests</h3><small>${runs.length} in this workspace</small></div><div class="request-list">${runs.length ? runs.map(r=>`<button class="request-row ${selected===r.id?'selected':''}" data-run="${e(r.id)}"><div><small class="code">RF-${e(r.id.slice(0,8))}</small>${pill(r.mode)}</div><p>${e(r.request)}</p><div>${status(r.status)}<small>${e(stamp(r.created_at))}</small></div></button>`).join('') : empty('No requests yet','Submit a request above. Each investigation will appear here.','▤')}</div></section></div>
    <section class="panel"><div class="panel-head"><h3>Investigation detail</h3>${detail ? `<button class="icon-button" data-refresh>Refresh ↻</button>` : '<span class="label-meta">02 / EVIDENCE & ACTION</span>'}</div>${detail ? renderDetail() : empty('Follow the evidence','Select a request to inspect observations, policy rules, and the exact proposed action.','◈')}</section></div>`;
}
const toolTitles = {get_order:'Order verified',get_tracking:'Shipment observed',search_policy:'Applicable policy retrieved',check_resolution_eligibility:'Deterministic eligibility checked',create_case:'Sandbox case created',propose_resolution:'Exact resolution proposed',request_clarification:'Missing information requested'};
function observationSummary(o) {
  const d = o.data;
  if(o.tool==='get_order') return `${d.id} · ${d.product} · paid ${money(d.paid_minor,d.currency)} · revision ${d.revision}`;
  if(o.tool==='search_policy') return `${d.id} · applies by purchase date · ${(d.rules?.passages||[]).join(' ')}`;
  if(o.tool==='get_tracking') return `Delivery: ${d.delivered_at ? stamp(d.delivered_at) : 'not confirmed'} · business record revision ${d.order_revision}`;
  if(o.tool==='check_resolution_eligibility') return `${words(d.status)} · ${(d.reasons||[]).join('; ') || (d.rule_ids||[]).join(', ')}`;
  if(o.tool==='create_case') return `Case ${d.id.slice(0,8)} · category ${d.category}`;
  if(o.tool==='request_clarification') return d.question;
  return `Proposal ${d.id?.slice(0,8)} · pending review`;
}
function renderDetail() {
  const r = detail;
  return `<div class="panel-body"><span class="label-meta code">RF-${e(r.id.slice(0,8))}</span><h2 class="detail-title">Investigation, with a record.</h2><div class="detail-meta">${status(r.status)}${pill(r.mode)}</div><div class="request-quote">${e(r.request)}</div>
    ${r.final?.explanation ? `<div class="result ${['awaiting_approval','awaiting_information'].includes(r.status)?'warning':['failed','rejected'].includes(r.status)?'error':''}"><strong>${e(words(r.final.outcome))}</strong><p>${e(r.final.explanation)}</p><span class="muted">${r.committed_effects.length} protected effect(s) committed · ${e(r.mode)} mode</span></div>` : `<div class="callout">${e(words(r.status))}. Progress will appear as the worker records real observations.</div>`}
    ${r.status==='awaiting_information' ? clarificationForm(r) : ''}
    <div class="section-label">Observed facts & policy</div>${r.observations?.length ? r.observations.map(o=>`<div class="observation"><div><h3>${e(toolTitles[o.tool]||o.tool)}</h3><small>${e(o.observation_id)}</small><p>${e(observationSummary(o))}</p><details><summary>Inspect source observation</summary><pre>${pretty(o)}</pre></details></div></div>`).join('') : '<p class="muted">No tool observations yet. A separate worker processes queued runs.</p>'}
    ${r.proposal ? `<div class="section-label">Proposed effect</div>${proposalCard(r.proposal)}` : ''}
    ${r.committed_effects.length ? `<div class="section-label">Committed sandbox state</div>${r.committed_effects.map(effect=>`<div class="result"><strong>Simulated ${e(effect.action)} committed</strong><p>${effect.action==='refund'?money(effect.amount_minor,effect.currency):effect.action==='replacement'?`${effect.quantity} replacement item(s)`:'Order cancelled'} · ${e(effect.order_id)}</p><small class="code">Effect ${e(effect.id)}</small></div>`).join('')}` : ''}
    <div class="section-label">Execution</div><p class="muted">${r.timing.tool_calls} tool calls · ${r.timing.model_calls} model calls · ${r.timing.active_seconds?.toFixed(2) || '—'}s active · tokens ${r.timing.tokens ?? 'unknown / not applicable'}</p>
    ${!['completed','failed','rejected','escalated','cancelled'].includes(r.status)?`<button class="secondary danger" data-cancel="${e(r.id)}">Cancel investigation</button>`:''}${session.role==='developer'?` <button class="secondary" data-trace="${e(r.id)}">Inspect protected trace</button><div id="trace-output"></div>`:''}</div>`;
}
function clarificationForm(r) { return `<form id="clarification" class="proposal"><h3>Supply the requested facts</h3><p class="muted">Operator input is recorded as reported evidence, with photo review attested separately.</p>${r.clarification.fields.map(f=>f==='photo_reviewed'?'<label class="inline-check"><input type="checkbox" name="photo_reviewed">Sandbox photo reviewed by operator</label>':`<label>${e(words(f))}<input name="${e(f)}" required maxlength="1000" placeholder="${f==='damage_reported_at'?'2026-09-10T10:00:00+00:00':f==='order_id'?'ORD-1001':''}"></label>`).join('')}<button class="primary">Save facts & resume →</button></form>`; }
function proposalCard(p) {
  const d = p.payload, exact = d.action==='refund'?money(d.amount_minor,d.currency):d.action==='replacement'?`${d.quantity} item${d.quantity===1?'':'s'} replacement`:words(d.action);
  return `<div class="proposal"><div class="proposal-top"><span class="eyebrow">SIMULATED ${e(d.action.toUpperCase())}</span><span class="pill">${e(p.status)}</span></div><div class="proposal-effect">${e(exact)}</div><div class="proposal-grid"><div><small>Order / customer</small>${e(d.order_id)} / ${e(d.customer_id)}</div><div><small>Business record revision</small>${d.order_revision}</div><div><small>Policy / rules</small>${e(d.policy_id)} · ${e(d.rule_ids.join(', '))}</div><div><small>Approval expiry</small>${e(stamp(p.expires_at))}</div></div><details class="muted"><summary>Inspect immutable payload & hash</summary><pre>${pretty(p)}</pre></details>${p.status==='pending' ? `<div class="proposal-actions"><button class="primary" data-decision="approve" data-proposal="${e(p.id)}" ${['supervisor','developer'].includes(session.role)?'':'disabled'}>Approve exact effect ✓</button><button class="secondary danger" data-decision="reject" data-proposal="${e(p.id)}" ${['supervisor','developer'].includes(session.role)?'':'disabled'}>Reject</button></div><p class="muted">${session.role==='operator'?'Switch to a supervisor session to decide.':'Approval binds to this payload, hash and revision. Changed facts require a new proposal.'}</p>`:''}</div>`;
}
function renderApprovals() {
  const all = runs.filter(r=>r.proposal_id), pending = all.filter(r=>r.status==='awaiting_approval');
  return title('HUMAN REVIEW','The exact effect. Your decision.','Approval cannot override policy or expand workspace access.') + `<div class="callout">${pending.length} proposal(s) awaiting review. Inspect the amount, quantity, sources, and business revision before approving.</div><div class="split"><section class="panel"><div class="panel-head"><h3>Proposal queue</h3><small>${all.length} proposals</small></div>${all.length?all.map(r=>`<button class="request-row" data-run="${e(r.id)}"><div><span class="code">RF-${e(r.id.slice(0,8))}</span>${status(r.status)}</div><p>${e(r.request)}</p>${pill(r.mode)}</button>`).join(''):empty('No proposals to review','An eligible investigation creates an exact proposal here.','✓')}</section><section class="panel"><div class="panel-head"><h3>Proposal & supporting evidence</h3></div>${detail?renderDetail():empty('Review before committing','Select a request to inspect its proposed effect and policy evidence.','✓')}</section></div>`;
}
function renderSandbox() {
  const data = records || {orders:[],cases:[],effects:[],policies:[]};
  return title('BUSINESS RECORDS','A sandbox you can inspect.','Real persisted state for fictional orders, cases, policies, and effects.') + `<section class="panel"><div class="panel-head"><h3>Orders</h3><span class="pill">FICTIONAL DATA</span></div><div class="table-wrap"><table><thead><tr><th>Order</th><th>Paid</th><th>Refunded</th><th>Replacements</th><th>State</th><th>Revision</th></tr></thead><tbody>${data.orders.map(o=>`<tr><td>${e(o.id)}<small>${e(o.product)}</small></td><td>${money(o.paid_minor,o.currency)}</td><td>${money(o.refunded_minor,o.currency)}</td><td>${o.replaced_qty} / ${o.quantity}</td><td>${o.cancelled?'Cancelled':o.delivered_at?'Delivered':o.shipped?'In transit':'Unshipped'}</td><td>${o.revision}</td></tr>`).join('')}</tbody></table></div></section>
    <section class="panel"><div class="panel-head"><h3>Committed effects</h3><small>${data.effects.length} ledger entries</small></div>${data.effects.length?`<div class="table-wrap"><table><thead><tr><th>Action</th><th>Order</th><th>Exact effect</th><th>Approval linkage</th><th>Committed</th></tr></thead><tbody>${data.effects.map(x=>`<tr><td class="ledger">Simulated ${e(x.action)}</td><td>${e(x.order_id)}</td><td>${x.action==='refund'?money(x.amount_minor,x.currency):x.action==='replacement'?x.quantity+' item(s)':'cancelled'}</td><td class="code">${e(x.approval_id.slice(0,8))}<small>Proposal ${e(x.proposal_id.slice(0,8))}</small></td><td>${e(stamp(x.created_at))}</td></tr>`).join('')}</tbody></table></div>`:empty('No protected effects committed','Approving an eligible proposal creates a uniquely linked ledger record.','▦')}</section>
    <div class="split"><section class="panel"><div class="panel-head"><h3>Support cases</h3></div>${data.cases.length?data.cases.map(c=>`<div class="request-row"><div><span class="code">${e(c.id.slice(0,8))}</span><span class="pill">${e(c.category)}</span></div><p>${e(c.order_id)} · ${e(c.customer_id)}</p></div>`).join(''):empty('No cases yet','Cases are created through the same typed tool contracts.')}</section><section class="panel"><div class="panel-head"><h3>Immutable policy versions</h3></div><div class="panel-body">${data.policies.map(p=>`<details><summary>${e(p.id)} · ${e(p.title)}</summary><p class="muted">Effective ${e(p.effective_from.slice(0,10))} to ${e(p.effective_until.slice(0,10))} · selected by purchase date</p><pre>${pretty(p.rules)}</pre><p class="code">SHA-256 ${e(p.source_hash)}</p></details>`).join('<br>')}</div></section></div>`;
}
function renderEvaluation() {
  if(session.role!=='developer') return title('DEVELOPER EVIDENCE','Evaluation, with provenance.','This area is restricted to developer sessions.')+empty('Developer access required','Switch to the developer role to inspect benchmark reports, assertions, and failures.','◴');
  if(!report) return title('DEVELOPER EVIDENCE','Measure what actually happened.','Frozen scenarios, inspectable assertions, honest denominators.')+`<div class="panel">${empty('Load evaluation evidence','Reports are generated by the evaluation runner, never synthesized in the interface.','◴')}<div class="panel-body"><button class="primary" data-evaluation>Load reports →</button></div></div>`;
  return title('DEVELOPER EVIDENCE','Measure what actually happened.','Frozen scenarios, inspectable assertions, honest denominators.') + `<div class="callout">Fixture comparisons demonstrate plumbing, not model intelligence. Live model quality and human semantic review are ${e(report.live_provider_status||'unverified')}.</div>${report.systems ? `<div class="metric-grid">${Object.entries(report.systems).map(([mode,m])=>`<section class="panel"><div class="panel-head"><h3>${e(words(mode))}</h3>${pill(mode)}</div><div class="panel-body"><h2>${m.task_completion.numerator} / ${m.task_completion.denominator}</h2><p class="muted">Observable scenario assertions passed</p><p>${m.policy_violations.numerator} / ${m.policy_violations.denominator} forbidden effects</p><p class="muted">p50 ${m.latency_p50_seconds?.toFixed(3)}s · p95 ${m.latency_p95_seconds?.toFixed(3)}s</p></div></section>`).join('')}</div>`:''}<section class="panel"><div class="panel-head"><h3>Inspectable report</h3></div><div class="panel-body"><pre>${pretty(report)}</pre></div></section>`;
}
document.addEventListener('click', async event => {
  if(event.target.closest('[data-sample]')) { try { publicSample=await api('/sample'); $('#login-dialog').close(); render(); } catch(err) { toast(err.message); } return; }
  const button = event.target.closest('button'); if(!button) return;
  if(button.dataset.login) return login(button.dataset.login);
  if(button.id==='account' || button.hasAttribute('data-signin')) return $('#login-dialog').showModal();
  if(button.dataset.view) { view=button.dataset.view; render(); return; }
  if(button.dataset.run) { try { selected=button.dataset.run; detail=await api('/runs/'+selected); render(); } catch(err) {toast(err.message);} return; }
  if(button.hasAttribute('data-refresh')) { await refresh(); render(); return; }
  if(button.dataset.decision) {
    const p=detail?.proposal; if(!p || p.id!==button.dataset.proposal) return;
    button.disabled=true;
    try { await api('/proposals/'+p.id+'/decision',{method:'POST',body:JSON.stringify({decision:button.dataset.decision,expected_revision:p.revision,expected_hash:p.payload_hash})}); toast('Decision recorded. The worker will revalidate before executing.'); await refresh(); render(); } catch(err) {toast(err.message); button.disabled=false;}
  }
  if(button.dataset.cancel) { try {await api('/runs/'+button.dataset.cancel+'/cancel',{method:'POST'}); await refresh(); render();} catch(err) {toast(err.message);} }
  if(button.dataset.trace) { try {const trace=await api('/runs/'+button.dataset.trace+'/trace'); $('#trace-output').innerHTML='<pre>'+pretty(trace)+'</pre>';} catch(err) {toast(err.message);} }
  if(button.hasAttribute('data-evaluation')) {try {const response=await api('/evaluations'); report=response.items[0]; if(!report) toast('No report generated yet. Run the documented evaluation command.'); render();} catch(err) {toast(err.message);} }
});
document.addEventListener('submit', async event => {
  event.preventDefault(); const form=event.target, data=new FormData(form);
  if(form.id==='credentials') return login(data.get('role'),data.get('password'));
  const submit=form.querySelector('button[type="submit"], button.primary'); if(submit) submit.disabled=true;
  try {
    if(form.id==='new-request') {
      const facts={}; for(const f of ['damage_description','damage_reported_at']) if(data.get(f)) facts[f]=data.get(f);
      if(data.get('photo_reviewed')) facts.photo_reviewed=true;
      const run=await api('/runs',{method:'POST',body:JSON.stringify({customer_id:data.get('customer_id'),message:data.get('message'),mode:data.get('mode'),idempotency_key:crypto.randomUUID(),facts})});
      selected=run.id; detail=await api('/runs/'+selected); await refresh(); render(); toast('Investigation queued.');
    }
    if(form.id==='clarification') {
      const facts={}; for(const f of detail.clarification.fields) facts[f]=f==='photo_reviewed'?data.has(f):data.get(f);
      await api('/runs/'+selected+'/clarification',{method:'POST',body:JSON.stringify({facts,idempotency_key:crypto.randomUUID()})}); await refresh(); render(); toast('Facts saved. Investigation resumed.');
    }
  } catch(err) {toast(err.message); if(submit) submit.disabled=false;}
});
async function boot() {try {session=await api('/auth/me'); updateAccount(); await refresh();} catch {if(document.body.dataset.demoMode==='true') setTimeout(()=>$('#login-dialog').showModal(),100);} render();}
boot();
setInterval(async()=>{ if(!session || busy || document.hidden) return; busy=true; const prior=JSON.stringify([runs.map(r=>[r.id,r.status]),detail?.observations?.length]); await refresh(); const next=JSON.stringify([runs.map(r=>[r.id,r.status]),detail?.observations?.length]); if(prior!==next && !document.activeElement?.closest('form')) render(); busy=false; },2000);
