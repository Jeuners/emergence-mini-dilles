// Emergence-Mini live view
const canvas = document.getElementById('world');
const ctx = canvas.getContext('2d');
const GRID = 240;
let snapshot = null;
let actions = [];
const AGENT_COLORS = {
  anchor: '#ffd166',
  flora:  '#6cf0c2',
  lovely: '#ff8fb1',
  spark:  '#82aaff',
};
const LANDMARK_COLORS = {
  town_hall: '#ff6c6c',
  library:   '#82aaff',
  plaza:     '#ff8fb1',
  park:      '#6cf08a',
  victory_arch: '#ffd166',
  police:    '#cccccc',
  bookworm:  '#a47cff',
  cafe:      '#ffb066',
  billboard: '#dddddd',
  techhub:   '#6cf0c2',
  home_anchor: '#3a3a3a',
  home_flora:  '#3a3a3a',
  home_lovely: '#3a3a3a',
  home_spark:  '#3a3a3a',
};

function draw() {
  if (!snapshot) return;
  const W = canvas.width, H = canvas.height;
  ctx.fillStyle = '#060a0e';
  ctx.fillRect(0, 0, W, H);

  // grid
  ctx.strokeStyle = '#0e1620';
  ctx.lineWidth = 1;
  for (let i = 0; i <= GRID; i += 30) {
    const px = (i / GRID) * W;
    ctx.beginPath(); ctx.moveTo(px, 0); ctx.lineTo(px, H); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0, px); ctx.lineTo(W, px); ctx.stroke();
  }

  // landmarks
  for (const lm of snapshot.landmarks) {
    const x = (lm.x / GRID) * W;
    const y = (lm.y / GRID) * H;
    const isHome = lm.id.startsWith('home_');
    ctx.fillStyle = LANDMARK_COLORS[lm.id] || '#888';
    ctx.beginPath();
    ctx.arc(x, y, isHome ? 5 : 7, 0, Math.PI * 2);
    ctx.fill();
    if (!isHome) {
      ctx.fillStyle = '#0a1018';
      ctx.font = '10px ui-monospace';
      ctx.textAlign = 'center';
      ctx.fillText(lm.name, x, y - 9);
    }
  }

  // agents
  for (const a of snapshot.agents) {
    const x = (a.x / GRID) * W;
    const y = (a.y / GRID) * H;
    ctx.fillStyle = AGENT_COLORS[a.id] || '#fff';
    ctx.beginPath();
    ctx.arc(x, y, 8, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#0a1018';
    ctx.font = 'bold 10px ui-monospace';
    ctx.textAlign = 'center';
    ctx.fillText(a.name[0], x, y + 3);
    // energy halo
    ctx.strokeStyle = '#ffd166';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(x, y, 8 + (100 - a.energy) * 0.06, 0, Math.PI * 2);
    ctx.stroke();
  }
}

function refreshAgentCards() {
  const wrap = document.getElementById('agentList');
  wrap.innerHTML = '';
  for (const a of snapshot.agents) {
    const div = document.createElement('div');
    div.className = 'agent-card';
    div.innerHTML = `
      <h3>${a.name} <small>· ${a.role}</small></h3>
      <div>at (${a.x}, ${a.y}) · ${a.mood}</div>
      <div class="bar energy"><i style="width:${a.energy}%"></i></div>
      <div class="bar knowledge"><i style="width:${a.knowledge}%"></i></div>
      <div class="bar influence"><i style="width:${a.influence}%"></i></div>
      <div class="bar credits"><i style="width:${Math.min(100, a.credits * 5)}%"></i></div>
      <small>${a.energy.toFixed(0)}E · ${a.knowledge.toFixed(0)}K · ${a.influence.toFixed(0)}I · ${a.credits.toFixed(1)} CC</small>
    `;
    wrap.appendChild(div);
  }
}

function refreshProposals() {
  const wrap = document.getElementById('proposals');
  wrap.innerHTML = '';
  fetch('/api/proposals').then(r => r.json()).then(d => {
    if (!d.active.length) {
      wrap.innerHTML = '<small>No active proposals.</small>';
      return;
    }
    for (const p of d.active) {
      const el = document.createElement('div');
      el.className = 'proposal';
      el.innerHTML = `<h4>#${p.id} ${p.title}</h4>
        <small>by ${p.author} · ${p.category} · ${p.votes} votes</small>
        <p>${p.body}</p>`;
      wrap.appendChild(el);
    }
  });
}

function refreshConstitution() {
  const wrap = document.getElementById('constitution');
  wrap.innerHTML = '';
  fetch('/api/constitution').then(r => r.json()).then(c => {
    for (const a of c.articles) {
      const el = document.createElement('div');
      el.className = 'article';
      el.innerHTML = `<b>Article ${a.id} — ${a.title}</b><p>${a.body}</p>`;
      wrap.appendChild(el);
    }
  });
}

function addFeed(entry) {
  const ul = document.getElementById('feed');
  const li = document.createElement('li');
  const t = new Date().toLocaleTimeString();
  if (entry.type === 'action') {
    li.innerHTML = `<span class="who">${entry.name}</span>
      <span class="tool">${entry.tool}</span>
      <span class="why">— ${entry.rationale || ''}</span>
      <small> · ${t}</small>`;
  } else {
    li.innerHTML = `<small>${entry.type} · ${t}</small>`;
  }
  ul.prepend(li);
  while (ul.children.length > 80) ul.removeChild(ul.lastChild);
}

function refreshHeader() {
  document.getElementById('tick').textContent = snapshot?.tick || 0;
  document.getElementById('agentCount').textContent = snapshot?.agents.length || 0;
}

async function refreshAll() {
  const r = await fetch('/api/state');
  snapshot = await r.json();
  draw();
  refreshHeader();
  refreshAgentCards();
  refreshProposals();
  refreshConstitution();
}

function connectWS() {
  const ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws');
  const status = document.getElementById('wsStatus');
  ws.onopen = () => { status.textContent = 'live'; status.className = 'ws-status connected'; };
  ws.onclose = () => {
    status.textContent = 'disconnected — retrying'; status.className = 'ws-status disconnected';
    setTimeout(connectWS, 2000);
  };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === 'snapshot') {
      snapshot = msg.data;
      draw(); refreshHeader(); refreshAgentCards();
    } else if (msg.type === 'action') {
      // update local agent snapshot
      if (snapshot) {
        const a = snapshot.agents.find(x => x.id === msg.agent);
        if (a) {
          a.x = msg.x; a.y = msg.y;
          a.energy = msg.energy; a.knowledge = msg.knowledge;
          a.influence = msg.influence; a.credits = msg.credits;
          a.mood = msg.mood;
        }
        draw(); refreshAgentCards();
      }
      addFeed(msg);
      // refresh proposals / constitution occasionally
      if (msg.tool && msg.tool.startsWith('vote_on') || msg.tool === 'submit_townhall_proposal') {
        refreshProposals();
      }
      if (msg.tool === 'submit_townhall_proposal') {
        setTimeout(refreshConstitution, 500);
      }
    } else if (msg.type === 'tick') {
      document.getElementById('tick').textContent = msg.tick;
    }
  };
}

async function populateManual() {
  const a = await (await fetch('/api/agents')).json();
  const selA = document.querySelector('#manual select[name=agent]');
  for (const ag of a) {
    const o = document.createElement('option');
    o.value = ag.id; o.textContent = ag.name; selA.appendChild(o);
  }
  const tools = [
    'go_to_place','go_home','say_to_agent','speak_to_all',
    'show_emoticon','recharge_energy','add_to_longterm_memory',
    'write_blog','add_to_billboard','submit_townhall_proposal',
    'vote_on_proposal','idle',
  ];
  const selT = document.querySelector('#manual select[name=tool]');
  for (const t of tools) {
    const o = document.createElement('option');
    o.value = t; o.textContent = t; selT.appendChild(o);
  }
}

document.getElementById('manual').addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = e.target;
  let args = {};
  try { args = JSON.parse(f.args.value || '{}'); } catch { alert('args must be JSON'); return; }
  const body = { tool: f.tool.value, args };
  const r = await fetch(`/api/turn/${f.agent.value}`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  const out = await r.json();
  console.log('manual turn result', out);
});

refreshAll();
populateManual();
connectWS();
setInterval(refreshProposals, 5000);
