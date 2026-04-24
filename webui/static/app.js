let autoScroll = true;
const log = document.getElementById('log');
const scrollBtn = document.getElementById('scroll-btn');

const cmEditor = CodeMirror.fromTextArea(document.getElementById('config-editor'), {
    mode: 'properties',
    theme: 'soularr',
    lineNumbers: true,
    indentWithTabs: false,
    lineWrapping: false,
    extraKeys: { Tab: false },
});

const mobileQuery = window.matchMedia('(pointer: coarse) and (hover: none), (max-width: 768px)');

function toggleSidebar() {
    const sidebar = document.querySelector('.sidebar');
    const overlay = document.querySelector('.sidebar-overlay');
    const opening = !sidebar.classList.contains('open');
    sidebar.classList.toggle('open', opening);
    overlay.classList.toggle('visible', opening);
}

function closeSidebar() {
    document.querySelector('.sidebar').classList.remove('open');
    document.querySelector('.sidebar-overlay').classList.remove('visible');
}

function showView(name, btn) {
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('view-' + name).classList.add('active');
    btn.classList.add('active');
    if (name === 'settings') {
        loadConfig();
        cmEditor.refresh();
    }
    if (name === 'failed-imports') {
        loadFailedImports();
    }
    if (mobileQuery.matches) closeSidebar();
}

function loadConfig() {
    fetch('/api/config')
        .then(r => r.json())
        .then(data => {
            document.getElementById('config-path').textContent = data.path;
            cmEditor.setValue(data.content);
            if (!data.exists) {
                cmEditor.setOption('placeholder', 'Config file not found at the path above.');
            }
        });
}

function saveConfig() {
    const btn = document.getElementById('save-btn');
    const content = cmEditor.getValue();
    btn.disabled = true;

    let dotCount = 1;
    btn.textContent = 'Saving.';
    btn.classList.add('saving');
    const dotAnim = setInterval(() => {
        if (dotCount < 3) {
            dotCount++;
            btn.textContent = 'Saving' + '.'.repeat(dotCount);
        }
    }, 400);

    const minDelay = new Promise(resolve => setTimeout(resolve, 1200));
    const request = fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content })
    }).then(r => r.json());

    Promise.all([request, minDelay])
        .then(([data]) => {
            clearInterval(dotAnim);
            btn.classList.remove('saving');
            btn.textContent = data.ok ? 'Saved' : 'Error';
            btn.classList.toggle('active', data.ok);
            btn.classList.toggle('save-error', !data.ok);
            setTimeout(() => {
                btn.textContent = 'Save';
                btn.disabled = false;
                btn.classList.remove('active', 'save-error');
            }, 1000);
        })
        .catch(() => {
            clearInterval(dotAnim);
            btn.classList.remove('saving');
            btn.textContent = 'Error';
            btn.classList.add('save-error');
            setTimeout(() => {
                btn.textContent = 'Save';
                btn.disabled = false;
                btn.classList.remove('save-error');
            }, 1000);
        });
}

function toggleScroll() {
    autoScroll = !autoScroll;
    scrollBtn.classList.toggle('active', autoScroll);
    if (autoScroll) log.scrollTop = log.scrollHeight;
}

function clearLog() {
    log.innerHTML = '';
}

const LOG_FONT_MIN = 4;
const LOG_FONT_MAX = 28;
let logFontSize = parseFloat(localStorage.getItem('soularr-log-font-size') || (mobileQuery.matches ? '7' : '12'));

function applyLogZoom() {
    log.style.fontSize = logFontSize + 'px';
    localStorage.setItem('soularr-log-font-size', logFontSize);
}

log.addEventListener('wheel', e => {
    if (!e.ctrlKey) return;
    e.preventDefault();
    logFontSize = Math.min(LOG_FONT_MAX, Math.max(LOG_FONT_MIN, logFontSize + (e.deltaY > 0 ? -0.5 : 0.5)));
    applyLogZoom();
}, { passive: false });

let lastPinchDist = null;
log.addEventListener('touchstart', e => {
    if (e.touches.length === 2)
        lastPinchDist = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY);
}, { passive: true });
log.addEventListener('touchmove', e => {
    if (e.touches.length !== 2 || lastPinchDist === null) return;
    e.preventDefault();
    const dist = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY);
    logFontSize = Math.min(LOG_FONT_MAX, Math.max(LOG_FONT_MIN, logFontSize * (dist / lastPinchDist)));
    lastPinchDist = dist;
    applyLogZoom();
}, { passive: false });
log.addEventListener('touchend', () => { lastPinchDist = null; });

applyLogZoom();

function classify(line) {
    if (line.includes('[ERROR|'))   return 'level-error';
    if (line.includes('[WARNING|')) return 'level-warn';
    if (line.includes('[DEBUG|'))   return 'level-debug';
    return 'level-info';
}

const lineQueue = [];
let flushScheduled = false;

function flushQueue() {
    if (lineQueue.length === 0) {
        flushScheduled = false;
        return;
    }
    const fragment = document.createDocumentFragment();
    while (lineQueue.length > 0) {
        const text = lineQueue.shift();
        const div = document.createElement('div');
        div.className = 'log-line ' + classify(text);
        div.textContent = text;
        fragment.appendChild(div);
    }
    log.appendChild(fragment);
    if (autoScroll) log.scrollTop = log.scrollHeight;
    flushScheduled = false;
}

function appendLine(text) {
    lineQueue.push(text);
    if (!flushScheduled) {
        flushScheduled = true;
        requestAnimationFrame(flushQueue);
    }
}

function loadFailedImports() {
    fetch('/api/failed-imports')
        .then(r => r.json())
        .then(data => {
            const tbody = document.getElementById('failed-imports-body');
            const empty = document.getElementById('failed-imports-empty');
            const count = document.getElementById('failed-imports-count');
            tbody.innerHTML = '';
            if (!Array.isArray(data) || data.length === 0) {
                empty.style.display = 'block';
                count.textContent = '';
            } else {
                empty.style.display = 'none';
                count.textContent = `${data.length} entr${data.length === 1 ? 'y' : 'ies'}`;
                data.forEach(entry => {
                    const tr = document.createElement('tr');
                    tr.innerHTML = `
                        <td>${entry.artist || '—'}</td>
                        <td>
                            <div>${entry.title || '—'}</div>
                            <button class="toolbar-btn remove-btn fi-remove-mobile" onclick="removeFailedImport(${entry.album_id})">Delete</button>
                        </td>
                        <td>
                            <div class="failed-imports-date-cell">
                                <span class="failed-imports-date">${entry.failed_at || '—'}</span>
                                <span class="failed-imports-sep"></span>
                                <button class="toolbar-btn remove-btn fi-remove-desktop" onclick="removeFailedImport(${entry.album_id})">Delete</button>
                            </div>
                        </td>
                    `;
                    tbody.appendChild(tr);
                });
            }
        });
}

function removeFailedImport(albumId) {
    fetch(`/api/failed-imports/${albumId}`, { method: 'DELETE' })
        .then(r => r.json())
        .then(() => loadFailedImports());
}

const es = new EventSource('/stream');
es.onmessage = e => appendLine(e.data);
es.onerror = () => appendLine('--- connection lost, retrying... ---');
