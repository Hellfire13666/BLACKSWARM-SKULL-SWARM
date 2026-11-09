'use strict';
const $ = x => document.getElementById(x);
let activeId = null, activeResults = [], polling = null, eventsAfter = 0;
const niceDate = iso => {try {return new Date(iso).toLocaleString()} catch(_) {return iso}};
function element(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = String(text);
  return el;
}
async function get(path) {
  const resp = await fetch(path, {cache:'no-store'});
  const data = await resp.json();
  if (!resp.ok) throw Error(data.error || 'Service request failed');
  return data;
}
function setStatus(text, type='ready') {
  $('statState').textContent = type.toUpperCase();
  $('statusNote').textContent = text;
  $('statState').style.color = type==='error' ? '#ffa5a5' : type==='running' ? '#c8a0ff' : '#6de9ff';
}
function showProviders(reports={}) {
  const slot = $('providerList'); slot.replaceChildren();
  if (!Object.keys(reports).length) {
    slot.append(element('p','side-hint','Source health appears after a search.'));
    return;
  }
  Object.entries(reports).forEach(([source, record]) => {
    const box = element('div','provider '+ (record.status==='ok'?'ok':record.status==='error'?'error':''));
    const left = element('div'); left.append(element('b','',source.toUpperCase()));
    if (record.detail) left.append(element('span','detail', record.detail));
    const count = element('small','',record.status==='ok' ? `${record.found} found` : record.status==='error' ? 'ERROR' : record.status);
    box.append(left,count); slot.append(box);
  });
  $('statProviders').textContent = String(Object.keys(reports).length);
}
function showResults() {
  const text = $('filter').value.trim().toLowerCase();
  const visible = activeResults.filter(r => [r.title, r.url, r.snippet, r.sources.join(' ')].join(' ').toLowerCase().includes(text));
  const slot = $('results');slot.replaceChildren();
  if (!visible.length) {
    const box=element('div','empty'); box.append(element('div','','⌕'),element('b','','NO MATCHING LINKS'),element('p','','Run a search, select a saved session or change the filter.'));
    slot.append(box);
  }
  const fragment=document.createDocumentFragment();
  visible.forEach(r=>{
    const entry=element('article','result'); const top=element('div','resulttop');
    const link=element('a','',r.title);link.href=r.url;link.target='_blank';link.rel='noopener noreferrer';link.referrerPolicy='no-referrer';
    const badges=element('div','source-badges');
    r.sources.forEach(name => badges.append(element('span','',name)));
    if(r.relevance && r.relevance!=='unscored') badges.append(element('span','',r.relevance.toUpperCase()+' · '+r.score));
    top.append(link,badges);entry.append(top,element('p','',r.snippet),element('small','',r.url));fragment.append(entry);
  });
  slot.append(fragment);$('countFooter').textContent=`Showing ${visible.length} of ${activeResults.length} unique stored links`;
}
async function openRun(id) {
  const data=await get('/api/results?id='+encodeURIComponent(id));
  activeId=id; activeResults=data.results;
  $('statCount').textContent=String(activeResults.length);
  $('resultsMeta').textContent=`SESSION #${id} / ${data.run.mode.toUpperCase()}`;
  const reports=JSON.parse(data.run.reports);showProviders(reports);
  if (data.run.mode==='demo') setStatus('Fictional sample links, not live search','demo');
  else setStatus('Public-provider results saved locally','saved');
  $('filter').value='';showResults();showDomainMap();
  $('compareOutput').textContent='Select another session, then compare link changes.';
  ['CSV','JSON','HTML'].forEach(format=>{
    const a=$('exp'+format); a.href='/api/export?id='+encodeURIComponent(id)+'&format='+format.toLowerCase();
    a.classList.remove('disabled');a.setAttribute('download','BLACKSWARM-run-'+id+'.'+format.toLowerCase());
  });
  document.querySelectorAll('.session').forEach(b=>b.classList.toggle('selected',Number(b.dataset.id)===id));
}
async function refreshRuns() {
  const data=await get('/api/runs');
  $('statSessions').textContent=String(data.count); // full vault count
  const list=$('sessions');list.replaceChildren();
  if (!data.runs.length) {list.append(element('p','side-hint','No saved sessions yet.'));return;}
  const compareSelect=$('compareSelect'), oldSelection=compareSelect.value;
  compareSelect.replaceChildren(element('option','','Choose previous session'));
  data.runs.forEach(run=>{
    const opt=element('option','',`#${run.id} · ${run.query.slice(0,42)}`);opt.value=String(run.id);compareSelect.append(opt);
    const button=element('button','session'+(run.id===activeId?' selected':''));
    button.type='button';button.dataset.id=run.id;
    button.append(element('b','',run.query),element('small','',`${niceDate(run.stamp)}  ·  ${run.total} links  ·  ${run.mode.toUpperCase()}`));
    button.addEventListener('click',()=>openRun(run.id).catch(e=>setStatus(e.message,'error')));
    list.append(button);
  });
  if ([...compareSelect.options].some(x=>x.value===oldSelection)) compareSelect.value=oldSelection;
}
async function pollJob() {
  try {
    const state=await get('/api/state');
    if (state.phase==='running') {
      setStatus(state.message,'running'); showProviders(state.reports || {});
      return;
    }
    clearInterval(polling);polling=null; $('searchBtn').disabled=false;$('demoBtn').disabled=false;
    if (state.phase==='done') {
      await refreshRuns();await openRun(state.run_id);
      document.querySelector('.results-panel').scrollIntoView({behavior:'smooth',block:'nearest'});
    } else if (state.phase==='error') {setStatus(state.message || 'Search failed','error');}
  } catch(e) {clearInterval(polling); polling=null; $('searchBtn').disabled=false;$('demoBtn').disabled=false;setStatus(e.message,'error');}
}
async function start(demo) {
  const sources=Array.from(document.querySelectorAll('input[name=source]:checked')).map(c=>c.value);
  const body={query:$('q').value.trim(),sources,limit:Number($('limit').value),instance:$('searx').value.trim(),quality:'focused',demo};
  if (!body.query) {setStatus('Enter a topic or phrase','error');$('q').focus();return;}
  if (!demo && !sources.length) {setStatus('Choose at least one source','error');return;}
  $('searchBtn').disabled=true;$('demoBtn').disabled=true;setStatus('Launching source checks','running');
  try {
    const resp=await fetch('/api/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data=await resp.json();if (!resp.ok) throw Error(data.error || 'Could not start');
    if (polling) clearInterval(polling);polling=setInterval(pollJob,900);await pollJob();
  } catch(e) {$('searchBtn').disabled=false;$('demoBtn').disabled=false;setStatus(e.message,'error');}
}
function showDomainMap(){
  const slot=$('domainMap');slot.replaceChildren();
  const domains=new Map();
  activeResults.forEach(r=>{try{const d=new URL(r.url).hostname.toLowerCase();domains.set(d,(domains.get(d)||0)+1)}catch(_){}});
  const top=[...domains.entries()].sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0])).slice(0,8);
  if(!top.length){slot.append(element('p','side-hint','No domains to show.'));return;}
  const max=top[0][1];
  top.forEach(([host,count])=>{
    const row=element('div','domain-row');const header=element('div','domain-label');
    header.append(element('span','',host),element('b','',count));
    const track=element('div','domain-track'),bar=element('div','domain-bar');
    bar.style.width=(100*count/max).toFixed(1)+'%';track.append(bar);row.append(header,track);slot.append(row);
  });
}
async function showComparison(){
  const other=$('compareSelect').value;
  if(!activeId||!other){$('compareOutput').textContent='Open a session and select another to compare.';return;}
  try{
    const d=await get('/api/compare?current='+encodeURIComponent(activeId)+'&previous='+encodeURIComponent(other));
    const slot=$('compareOutput');slot.replaceChildren();
    slot.append(element('b','delta-stats',`+${d.added} NEW  /  −${d.removed} MISSING  /  ${d.unchanged} SHARED`));
    const title=element('div','delta-caption','Sample changed links (up to 20 per category)');slot.append(title);
    for(const [kind,arr] of [['new',d.new_links],['missing',d.missing_links]]){
      arr.slice(0,20).forEach(item=>{
        const row=element('div','delta-link');row.append(element('span',kind,kind==='new'?'+':'−'));
        const a=element('a','',item.url);a.href=item.url;a.target='_blank';a.rel='noopener noreferrer';a.referrerPolicy='no-referrer';row.append(a);slot.append(row);
      });
    }
  }catch(e){$('compareOutput').textContent=e.message;}
}
async function refreshEvents(){
  try{
    const payload=await get('/api/events?after='+eventsAfter);
    if(payload.events.length){
      const log=$('liveLog');if(log.querySelector('.line.note')&&eventsAfter===0)log.replaceChildren();
      payload.events.forEach(item=>{
        const div=element('div','line '+item.kind,item.text);
        log.append(div);
      });
      while(log.childElementCount>160) log.firstElementChild.remove();
      if(log.scrollHeight-log.scrollTop-log.clientHeight<380)log.scrollTop=log.scrollHeight;
    }
    eventsAfter=payload.latest;
  }catch(_){/* Source status remains visible if console mirror temporarily fails */}
}
$('compareBtn').addEventListener('click',showComparison);
setInterval(refreshEvents,1100);refreshEvents();
$('searchForm').addEventListener('submit',e=>{e.preventDefault();start(false)});
$('demoBtn').addEventListener('click',()=>start(true));
$('filter').addEventListener('input',showResults);
refreshRuns().then(async ()=>{
  const state=await get('/api/state');
  if (state.phase==='running') {polling=setInterval(pollJob,900); await pollJob();return;}
  const rows=await get('/api/runs');
  if (rows.runs.length) await openRun(rows.runs[0].id);
}).catch(e=>setStatus(e.message,'error'));
