'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const paths = {web:'M3 4h18v16H3z M3 9h18',mail:'M3 5h18v14H3z M3 5l9 7 9-7',activity:'M2 12h4l3-8 6 16 3-8h4',cart:'M2 3h3l3 12h11l3-9H6 M9 20h.01 M18 20h.01',card:'M3 5h18v14H3z M3 9h18 M6 15h4',tag:'M3 3h8l10 10-8 8L3 11z M7 7h.01',truck:'M2 5h12v12H2z M14 10h4l4 4v3h-8 M6 17a2 2 0 1 0 .01 0 M18 17a2 2 0 1 0 .01 0',coins:'M4 5c0-4 16-4 16 0s-16 4-16 0 M4 5v13c0 4 16 4 16 0V5 M4 10c0 4 16 4 16 0 M4 14c0 4 16 4 16 0',star:'m12 2 3 6 7 1-5 5 1 7-6-3-6 3 1-7-5-5 7-1z'};
const states = {injecting:'Preparando',active:'Fallo activo',effect_pending:'Esperando efecto',effect_observed:'Efecto observado',restoring:'Restaurando',verifying:'Verificando recuperación',verifying_recovery:'Verificando recuperación',recovery_unverified:'Recuperación pendiente',conflict:'Cambio ajeno: requiere revisión',completed:'Recuperado',cancelled:'Cancelado'};
const results = {effect_observed:'Efecto observado',effect_not_observed:'No se observó el efecto',interrupted:'Exposición interrumpida',write_uncertain:'Escritura incierta',admission_changed:'Admisión modificó los parámetros'};
const parameterNames = {port:'Puerto incorrecto',latency_ms:'Retraso (ms)',jitter_ms:'Variación (ms)',millicores:'Límite de CPU (millicores)'};
let state = null, duration = 60, mechanism = 'scale_zero', parameters = {}, busy = false, connected = false, offset = 0;
const time = stamp => new Date(stamp * 1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});
function notice(message) { $('notice').textContent = message; $('notice').hidden = !message; }
function label(name) { return state.services.find(s => s.name === name)?.label || name; }
function render() {
 if (!state) return;
 const active = state.active, locked = busy || !connected;
 const selected = state.mechanisms.find(m=>m.mechanism===(active?.mechanism || mechanism));
 if(!selected.durations.includes(duration)) duration=selected.durations[0];
 $('mechanism').innerHTML=state.mechanisms.map(m=>`<option value="${esc(m.mechanism)}" ${selected.mechanism===m.mechanism?'selected':''}>${esc(m.label)}${m.enabled?'':' · preparación pendiente'}</option>`).join('');
 $('mechanism').disabled=!!active || locked;
 $('mechanism-help').textContent=selected.reason;
 $('parameters').innerHTML=Object.entries(selected.defaults).map(([key,value])=>`<label>${esc(parameterNames[key])}<input type="number" data-parameter="${esc(key)}" value="${esc(parameters[key] ?? value)}" ${active||locked?'disabled':''}></label>`).join('');
 $('durations').querySelector('.duration-options').innerHTML=selected.durations.map(d=>`<button data-duration="${d}" aria-pressed="${d===duration}">${d} s</button>`).join('');
 $('mode').textContent = state.mode;
 $('service-count').textContent = `${state.services.length} componentes · boutique`;
 $('restore-all').disabled = !active || locked;
 $('cards').innerHTML = state.services.map(s => {
  const affected = active?.service === s.name;
  const healthy = !s.error && s.replicas > 0 && s.ready === s.replicas;
  const status = s.error ? 'No disponible' : affected ? states[active.state] : healthy ? 'Disponible' : 'Sin disponibilidad';
  const compatible=selected.enabled && selected.targets.includes(s.name);
  return `<article class="card ${affected ? 'affected':''}"><div class="card-top"><div class="icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[s.icon]}"/></svg></div><div><h3>${esc(s.label)}</h3><p>${esc(s.description)}</p><small class="service-name">${esc(s.name)}</small></div></div><span class="status ${s.error?'unknown':affected||!healthy?'warn':''}">${esc(status)}</span><div class="card-bottom"><span>${s.error?'Estado no disponible':`${s.ready} / ${s.replicas} disponibles`}</span><button data-${affected?'restore':'start'}="${s.name}" ${locked || (!affected && (active || !healthy || !compatible)) ? 'disabled':''}>${affected?'↻ Restaurar':compatible?'Provocar fallo':'No habilitado'}</button></div>${s.error?`<p>${esc(s.error)}</p>`:''}</article>`;
 }).join('');
 $('experiment').innerHTML = active ? `<h2>${esc(selected.label)} · ${esc(label(active.service))}</h2><p>${esc(states[active.state])}</p>${active.issue?`<div class="issue">${esc(active.issue)}</div>`:''}` : '<h2>Listo para experimentar</h2><p>Elige un mecanismo y un objetivo compatible. La línea base se comprueba antes de modificarlo.</p>';
 document.querySelectorAll('[data-duration]').forEach(b => {b.disabled = !!active || locked; b.setAttribute('aria-pressed', String(Number(b.dataset.duration) === (active?.duration || duration)));});
 $('timer').innerHTML = active ? `<div class="countdown"><div><strong id="clock">—</strong><small>${active.state === 'active'?'Hasta solicitar restauración':'Comprobando la recuperación'}</small></div><button data-restore ${locked?'disabled':''}>↻ Restaurar ahora</button></div>` : '<div class="empty">Sin fallos activos</div>';
 const experiment = active ? state.history.find(e=>e.id===active.id) : null;
 const observations = experiment?.events.filter(e=>e.kind==='observation') || [];
 const latest = active?.mechanism!=='scale_zero' && state.operational?.length ? {data:state.operational.at(-1)} : observations.at(-1);
 $('observations').innerHTML = active ? `<div class="checks"><div class="check">Disponibilidad del servicio<b>${latest?.data?.deployment ? `${latest.data.deployment.ready} / ${active.original} réplicas` : 'Por comprobar'}</b></div><div class="check">Sondas HTTP de tienda<b>${latest?.data?.http ? latest.data.http.map(p=>`${esc(p.path)}: ${p.status ?? 'sin respuesta'}`).join(' · ') : 'Por comprobar'}</b></div></div>` : '';
 if(active && latest?.data?.http) $('observations').innerHTML += `<p>Tiempo observado: ${latest.data.http.map(p=>`${esc(p.path)} ${p.elapsed_ms ?? '—'} ms`).join(' · ')}</p>`;
 const titles = {recorded:'Inicio persistido',scale_requested:'Escalado solicitado',deadline:'Plazo alcanzado',restore_requested:'Restauración solicitada',restart_recovery:'Recuperación tras reinicio',replicas_restored:'Réplicas solicitadas restauradas',recovered:'Recuperación verificada',attention:'Requiere atención'};
 const events = experiment?.events.filter(e=>e.kind!=='observation') || [];
 const failure = observations.find(e=>e.data.http?.some(p=>p.status!==200));
 if(failure) events.push({...failure,kind:'http_failure'});
 events.sort((a,b)=>a.at-b.at);
 $('timeline').innerHTML = events.slice(-9).map(e=>`<li><time>${time(e.at)}</time><b>${esc(e.kind==='http_failure'?'Fallo HTTP observado':titles[e.kind]||e.kind)}</b><p>${esc(e.kind==='http_failure'?e.data.http.map(p=>`${p.path}: ${p.status ?? 'sin respuesta'}`).join(', '):e.data.message || (e.kind==='recorded'?'Estado guardado antes de modificar Kubernetes.':e.kind==='scale_requested'?'Solicitud aceptada; la detención se observa por separado.':e.kind==='replicas_restored'?'Pendiente de disponibilidad y HTTP.':''))}</p></li>`).join('');
 $('history-count').textContent = `${state.history.length} registros`;
 $('history').innerHTML = state.history.length ? state.history.map(e=>`<div class="history-row"><div><b>${esc(label(e.service))}</b><small>${esc(state.mechanisms.find(m=>m.mechanism===e.mechanism)?.label || e.mechanism)} · ${e.duration} s</small><small>${esc(results[e.result] || '')}</small></div><div><span class="status ${e.state==='completed'?'':'warn'}">${esc(states[e.state])}</span></div><span>${esc(new Date(e.started*1000).toLocaleString())}</span><a href="/api/evidence/${e.id}" target="_blank" rel="noopener">Ver evidencia ↗</a></div>`).join('') : '<div class="empty">Los experimentos aparecerán aquí con sus observaciones y tiempos reales.</div>';
 $('telemetry').innerHTML = Object.values(state.telemetry).map(t=>`<p>${esc(t)}</p>`).join('');
 countdown();
}
function countdown() {
 if (!$('clock') || !state?.active) return;
 const end = state.active.effect_at ? Math.min(state.active.deadline, state.active.effect_at+state.active.duration) : state.active.deadline;
 const remaining = Math.max(0, Math.ceil(end - (Date.now()/1000+offset)));
 $('clock').textContent = ['active','effect_pending','effect_observed'].includes(state.active.state) ? `${String(Math.floor(remaining/60)).padStart(2,'0')}:${String(remaining%60).padStart(2,'0')}` : 'En curso';
}
async function refresh() {
 try {
  const res = await fetch('/api/state', {signal:AbortSignal.timeout(30000)});
  if(!res.ok) throw new Error('El servidor no pudo leer el estado.');
  state = await res.json(); offset = state.server_time-Date.now()/1000; connected=true;
  $('connection').textContent = `Actualizado ${time(state.server_time)}`;
 } catch(e) { connected=false; $('connection').textContent='Sin conexión · estado anterior, controles bloqueados'; }
 render();
}
async function action(path, body) {
 if(busy || !connected) return;
 busy=true; notice(''); render();
 try {
  const res = await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-ChaosForge-Token':state.csrf},body:JSON.stringify(body),signal:AbortSignal.timeout(30000)});
  const data=await res.json(); if(!res.ok) throw new Error(data.error);
 } catch(e) {notice(`${e.message} Revisa el estado actualizado antes de repetir la acción.`);}
 finally {busy=false; await refresh();}
}
document.addEventListener('click', e=>{
 const button=e.target.closest('button'); if(!button || button.disabled) return;
 if(button.dataset.duration) {duration=Number(button.dataset.duration);render();}
 else if(button.hasAttribute('data-start')) action('/api/start',{service:button.dataset.start,duration,mechanism,parameters});
 else if(button.hasAttribute('data-restore') || button.id==='restore-all') action('/api/restore',{});
});
document.addEventListener('change', e=>{
 if(e.target.id==='mechanism') {mechanism=e.target.value;parameters={};render();}
 if(e.target.dataset.parameter) parameters[e.target.dataset.parameter]=Number(e.target.value);
});
document.addEventListener('input', e=>{if(e.target.dataset.parameter) parameters[e.target.dataset.parameter]=Number(e.target.value);});
(async function poll(){await refresh();setTimeout(poll,3000);})();
setInterval(countdown,250);
