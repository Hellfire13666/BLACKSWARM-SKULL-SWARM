'use strict';
// SWARM COCKPIT: all user-controlled output is rendered with textContent.
// The local server performs the actual research. No third-party client scripts.
const $ = id => document.getElementById(id);
const create = (tag, cls='', value=undefined) => {
  const node=document.createElement(tag);
  if(cls) node.className=cls;
  if(value!==undefined) node.textContent=String(value);
  return node;
};
let activeId=null, activeResults=[], activeMode='live', bookmarked=new Set();
let eventsAfter=0, currentPage=1, pagesize=20, busy=false, poller=null;
const niceDate = t => {try{return new Date(t).toLocaleString()}catch(_){return String(t)}};
async function get(url){
  const response=await fetch(url,{cache:'no-store'});
  const data=await response.json();
  if(!response.ok) throw Error(data.error||'Local service unavailable');
  return data;
}
async function post(url,payload){
  const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const data=await response.json();
  if(!response.ok) throw Error(data.error||'Local request failed');
  return data;
}
function status(message,state='ready'){
  $('statState').textContent=state.toUpperCase();
  $('statusNote').textContent=message;
  $('statState').style.color=state==='error'?'#ff8b95':state==='running'?'#ffcd54':'#98ff39';
}
function showProviders(reports={}){
  const el=$('providerList');el.replaceChildren();
  const rows=Object.entries(reports);
  $('statProviders').textContent=String(rows.length);
  if(!rows.length){el.append(create('p','side-hint','Provider signals appear after you launch a search.'));return;}
  rows.forEach(([name,record])=>{
    const row=create('div','provider '+(record.status==='ok'?'ok':record.status==='error'?'error':''));
    const left=create('div');left.append(create('b','',name.toUpperCase()));
    if(record.detail)left.append(create('span','detail',record.detail));
    const right=create('small','',record.status==='ok'?`${record.found} LINKS`:record.status==='empty'?'EMPTY':'UNAVAILABLE');
    row.append(left,right);el.append(row);
  });
}
function domainNebula(){
  const el=$('domainMap');el.replaceChildren();const bins=new Map();
  activeResults.forEach(r=>{try{const host=new URL(r.url).hostname.toLowerCase();bins.set(host,(bins.get(host)||0)+1)}catch(_){}});
  const rows=[...bins.entries()].sort((a,b)=>b[1]-a[1]).slice(0,8);
  if(!rows.length){el.append(create('p','side-hint','Domains appear when you choose a saved session.'));return;}
  const max=rows[0][1];
  rows.forEach(([host,count])=>{
    const row=create('div','domain-row'),header=create('div','domain-label');
    header.append(create('span','',host),create('b','',count));
    const track=create('div','domain-track'),bar=create('div','domain-bar');
    bar.style.width=(100*count/max).toFixed(1)+'%';track.append(bar);row.append(header,track);el.append(row);
  });
}
function updateSourceOptions(){
  const old=$('sourceFilter').value;
  const list=[...new Set(activeResults.flatMap(x=>x.sources))].sort();
  $('sourceFilter').replaceChildren(create('option','','All sources'));
  $('sourceFilter').firstChild.value='';
  list.forEach(name=>{const op=create('option','',name);op.value=name;$('sourceFilter').append(op)});
  if(list.includes(old))$('sourceFilter').value=old;
}
function matchingResults(){
  const text=$('filter').value.trim().toLowerCase();
  const source=$('sourceFilter').value;
  const relevance=$('relevanceFilter').value;
  return activeResults.filter(row=>{
    if(source && !row.sources.includes(source))return false;
    if(relevance && row.relevance!==relevance)return false;
    return !text||[row.title,row.url,row.snippet,row.sources.join(' ')].join(' ').toLowerCase().includes(text);
  });
}
function resultList(){
  const matched=matchingResults(), total=matched.length;
  const maxpage=Math.max(1,Math.ceil(total/pagesize));
  currentPage=Math.max(1,Math.min(maxpage,currentPage));
  const begin=(currentPage-1)*pagesize;
  const slot=$('results');slot.replaceChildren();
  $('resultSummary').textContent=`${total} MATCHING LINKS · ${activeResults.length} IN SESSION`;
  $('pagePrev').disabled=currentPage<=1||!total;
  $('pageNext').disabled=currentPage>=maxpage||!total;
  $('countFooter').textContent=total?`${begin+1}–${Math.min(begin+pagesize,total)} OF ${total}  /  PAGE ${currentPage} OF ${maxpage}`:'NO MATCHING LINKS';
  if(!total){const box=create('div','empty');box.append(create('strong','','⌕'),create('b','','NO MATCHING SIGNALS'),create('p','','Try another keyword, source or saved session.'));slot.append(box);return;}
  const fragment=document.createDocumentFragment();
  matched.slice(begin,begin+pagesize).forEach((r,i)=>{
    const entry=create('article','result');
    const number=create('div','result-index',String(begin+i+1).padStart(2,'0'));
    const contents=create('div');
    const link=create('a','result-title',r.title||r.url);link.href=r.url;link.target='_blank';link.rel='noopener noreferrer';link.referrerPolicy='no-referrer';
    contents.append(link);
    if(r.snippet)contents.append(create('p','snippet',r.snippet));
    contents.append(create('span','url',r.url));
    const badges=create('div','source-badges');
    r.sources.forEach(src=>badges.append(create('span','',src)));
    if(r.relevance&&r.relevance!=='unscored')badges.append(create('span',`quality-${r.relevance}`,`${r.relevance.toUpperCase()} · ${r.score}/100`));
    contents.append(badges);
    const star=create('button','star-button'+(bookmarked.has(r.url)?' saved':''),bookmarked.has(r.url)?'★':'☆');
    star.type='button';star.title=bookmarked.has(r.url)?'Already bookmarked':'Save public link to local bookmarks';
    if(activeMode==='demo'){star.disabled=true;star.title='Offline demo links cannot be bookmarked';}
    star.setAttribute('aria-label',star.title);
    star.addEventListener('click',async()=>{
      if(!activeId)return;
      star.disabled=true;
      try{
        await post('/api/bookmark',{run_id:activeId,url:r.url});
        bookmarked.add(r.url);star.classList.add('saved');star.textContent='★';star.title='Bookmarked';
        status('Link starred in private bookmark shelf','saved');await refreshBookmarks();
      }catch(err){status('Bookmark failed: '+err.message,'error')}
      finally{star.disabled=false;}
    });
    entry.append(number,contents,star);fragment.append(entry);
  });
  slot.append(fragment);
}
function filterChanged(){currentPage=1;resultList();}
async function refreshBookmarks(){
  const data=await get('/api/bookmarks');const items=data.items||[];
  bookmarked=new Set(items.map(x=>x.url));
  $('bookmarkCount').textContent=`${items.length} SAVED`;
  const slot=$('bookmarks');slot.replaceChildren();
  if(!items.length){slot.append(create('p','side-hint','Tap ☆ beside an interesting public link to save it here.'));return;}
  items.slice(0,45).forEach(item=>{
    const wrapper=create('div','bookmark');
    const a=create('a','',item.title||item.url);a.href=item.url;a.target='_blank';a.rel='noopener noreferrer';a.referrerPolicy='no-referrer';
    wrapper.append(a,create('small','',`★ #${item.id} · SESSION ${item.session_id}`));slot.append(wrapper);
  });
}
async function openSession(id){
  const data=await get('/api/results?id='+encodeURIComponent(id));
  activeId=Number(id);activeResults=data.results||[];activeMode=data.run.mode;
  $('statCount').textContent=String(activeResults.length);
  $('resultsMeta').textContent=`SESSION #${id} · ${String(data.run.mode).toUpperCase()}`;
  let reports={};try{reports=JSON.parse(data.run.reports)||{}}catch(_){};
  showProviders(reports);updateSourceOptions();domainNebula();
  $('filter').value='';$('sourceFilter').value='';$('relevanceFilter').value='';currentPage=1;
  resultList();
  $('compareOutput').textContent='Select a different session to compare saved public links.';
  ['CSV','JSON','HTML'].forEach(fmt=>{
    const el=$('exp'+fmt);el.href=`/api/export?id=${encodeURIComponent(id)}&format=${fmt.toLowerCase()}`;
    el.setAttribute('download',`BLACKSWARM-run-${id}.${fmt.toLowerCase()}`);el.classList.remove('disabled');
  });
  if(data.run.mode==='demo')status('Offline sample session: fictional links','demo');
  else status('Exploring saved public links','saved');
  document.querySelectorAll('.session').forEach(el=>el.classList.toggle('selected',Number(el.dataset.id)===Number(id)));
}
async function refreshSessions(){
  const data=await get('/api/runs');
  $('statSessions').textContent=String(data.count);
  const slot=$('sessions');slot.replaceChildren();
  const select=$('compareSelect'),previous=select.value;
  select.replaceChildren();const first=create('option','','Choose a previous session');first.value='';select.append(first);
  if(!data.runs.length){slot.append(create('p','side-hint','No saved sessions. Launch the swarm to collect public links.'));return []}
  data.runs.forEach(row=>{
    const opt=create('option','',`#${row.id} · ${row.query.slice(0,32)}`);opt.value=String(row.id);select.append(opt);
    const btn=create('button','session'+(row.id===activeId?' selected':''));btn.type='button';btn.dataset.id=row.id;
    btn.append(create('b','',`#${row.id} · ${row.query}`),create('small','',`${row.total} LINKS · ${String(row.mode).toUpperCase()} · ${niceDate(row.stamp)}`));
    btn.addEventListener('click',()=>openSession(row.id).catch(e=>status(e.message,'error')));
    slot.append(btn);
  });
  if([...select.options].some(e=>e.value===previous))select.value=previous;
  return data.runs;
}
async function compare(){
  const other=$('compareSelect').value;
  if(!activeId||!other){$('compareOutput').textContent='Load a session and select another to compare.';return;}
  try{
    const data=await get(`/api/compare?current=${activeId}&previous=${encodeURIComponent(other)}`);
    const slot=$('compareOutput');slot.replaceChildren();
    slot.append(create('b','delta-stats',`+${data.added} NEW · −${data.removed} MISSING · ${data.unchanged} SHARED`));
    for(const [type,items] of [['new',data.new_links],['missing',data.missing_links]]){
      for(const item of items.slice(0,12)){
        const row=create('div','delta-link'),marker=create('span',type,type==='new'?'+':'−');
        const a=create('a','',item.url);a.href=item.url;a.target='_blank';a.rel='noopener noreferrer';a.referrerPolicy='no-referrer';
        row.append(marker,a);slot.append(row);
      }
    }
  }catch(e){$('compareOutput').textContent=e.message;}
}
async function refreshEvents(){
  try{
    const payload=await get(`/api/events?after=${eventsAfter}`);
    if(payload.events.length){
      const log=$('liveLog');
      if(eventsAfter===0)log.replaceChildren();
      const nearBottom=log.scrollHeight-log.scrollTop-log.clientHeight<120;
      payload.events.forEach(event=>log.append(create('div','line '+event.kind,event.text)));
      while(log.childElementCount>170)log.firstElementChild.remove();
      if(nearBottom)log.scrollTop=log.scrollHeight;
    }
    eventsAfter=payload.latest;
  }catch(_){/* Retain loaded local links during temporary connection issues. */}
}
function lockControls(value){busy=value;$('searchBtn').disabled=value;$('demoBtn').disabled=value;}
async function pollJob(){
  try{
    const job=await get('/api/state');
    if(job.phase==='running'){
      status(job.message||'Checking public sources','running');showProviders(job.reports||{});return;
    }
    clearInterval(poller);poller=null;lockControls(false);
    if(job.phase==='done'){
      await refreshSessions();await refreshBookmarks();await openSession(job.run_id);
      status('Search complete; public links saved locally','saved');
    }else if(job.phase==='error')status(job.message||'Provider search failed','error');
  }catch(e){clearInterval(poller);poller=null;lockControls(false);status(e.message,'error')}
}
async function startSearch(demo){
  if(busy)return;
  const query=$('q').value.trim() || (demo?'demo: public research':'');
  const sources=[...document.querySelectorAll('input[name=source]:checked')].map(x=>x.value);
  if(!query){status('Enter your research search phrase','error');$('q').focus();return;}
  if(!demo&&!sources.length){status('Select at least one public provider','error');return;}
  lockControls(true);status('Connecting to public sources','running');
  try{
    await post('/api/start',{query,sources,limit:Number($('limit').value),instance:$('searx').value.trim(),quality:$('quality').value,demo});
    if(poller)clearInterval(poller);poller=setInterval(pollJob,850);await pollJob();
  }catch(e){lockControls(false);status(e.message,'error')}
}
function selectSources(names){
  document.querySelectorAll('input[name=source]').forEach(el=>{el.checked=names.has(el.value)});
}
$('searchForm').addEventListener('submit',e=>{e.preventDefault();startSearch(false)});
$('demoBtn').addEventListener('click',()=>startSearch(true));
$('filter').addEventListener('input',filterChanged);
$('sourceFilter').addEventListener('change',filterChanged);
$('relevanceFilter').addEventListener('change',filterChanged);
$('pagePrev').addEventListener('click',()=>{if(currentPage>1){currentPage--;resultList();}});
$('pageNext').addEventListener('click',()=>{currentPage++;resultList();});
$('compareBtn').addEventListener('click',compare);
$('selectDefault').addEventListener('click',()=>selectSources(new Set(['wikipedia','crossref','openlibrary','archive','europepmc','arxiv','wikidata','loc','pubmed'])));
$('selectAll').addEventListener('click',()=>selectSources(new Set([...document.querySelectorAll('input[name=source]')].map(x=>x.value))));
$('clearSources').addEventListener('click',()=>selectSources(new Set()));
setInterval(refreshEvents,1050);refreshEvents();
(async()=>{
  try{
    await refreshBookmarks();const runs=await refreshSessions();
    const job=await get('/api/state');
    if(job.phase==='running'){lockControls(true);poller=setInterval(pollJob,850);await pollJob();}
    else if(runs.length)await openSession(runs[0].id);
  }catch(e){status(e.message,'error')}
})();
