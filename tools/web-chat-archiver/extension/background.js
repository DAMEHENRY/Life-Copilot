// Life Copilot Web Chat Archiver — MV3 service worker.
//
// The local native host (com.lifecopilot.web_chats) owns the archive on disk
// and decides when to sync. This worker only reads conversations with the
// browser's existing claude.ai / chatgpt.com / chat.deepseek.com / gemini.google.com
// login and streams raw JSON back.
// Session cookies and access tokens never leave the browser.

const HOST_NAME = 'com.lifecopilot.web_chats';
const TAB_LOAD_TIMEOUT_MS = 45000;
const RATE_LIMIT_WAIT_MS = 20000;

const PROVIDERS = {
  claude: {
    origin: 'https://claude.ai',
    bootstrapPath: '/robots.txt',
    fullPagePath: '/recents',
    requestGapMs: 120,
  },
  chatgpt: {
    origin: 'https://chatgpt.com',
    bootstrapPath: '/robots.txt',
    fullPagePath: '/',
    // ChatGPT answers bursts of conversation downloads with HTTP 429.
    requestGapMs: 600,
  },
  deepseek: {
    origin: 'https://chat.deepseek.com',
    bootstrapPath: '/robots.txt',
    fullPagePath: '/',
    requestGapMs: 300,
  },
  gemini: {
    origin: 'https://gemini.google.com',
    bootstrapPath: '/robots.txt',
    fullPagePath: '/app',
    requestGapMs: 250,
  },
};

let port = null;
let activeSync = null;

class SyncError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// ---------------------------------------------------------------------------
// Native host connection
// ---------------------------------------------------------------------------
function connect() {
  if (port) return;
  try {
    port = chrome.runtime.connectNative(HOST_NAME);
  } catch (error) {
    port = null;
    setStatus('error', `Native host unavailable: ${error.message || error}`);
    return;
  }
  port.onMessage.addListener(onHostMessage);
  port.onDisconnect.addListener(() => {
    const reason = chrome.runtime.lastError ? chrome.runtime.lastError.message : 'disconnected';
    port = null;
    setStatus('error', `Native host disconnected: ${reason}`);
  });
  post({ type: 'hello', extension_version: chrome.runtime.getManifest().version });
}

function post(message) {
  if (!port) throw new SyncError('host_disconnected', 'Native host is not connected');
  port.postMessage(message);
}

function log(level, message) {
  try {
    post({ type: 'log', level, message });
  } catch (_) {
    // Logging must never break a sync.
  }
}

function onHostMessage(message) {
  if (!message || typeof message !== 'object') return;
  if (message.type === 'sync') {
    runSync(message);
  } else if (message.type === 'reload') {
    // Chrome keeps running a cached worker script across restarts, so
    // `install-web-chats` asks the extension to reload after copying new code.
    chrome.runtime.reload();
  } else if (message.type === 'ping') {
    post({ type: 'pong', extension_version: chrome.runtime.getManifest().version, syncing: Boolean(activeSync) });
  }
}

function requestSync(reason) {
  connect();
  try {
    post({ type: 'want_sync', reason });
  } catch (error) {
    setStatus('error', error.message);
  }
}

function setStatus(kind, title) {
  chrome.action.setBadgeText({ text: kind === 'error' ? '!' : '' });
  chrome.action.setBadgeBackgroundColor({ color: '#d93025' });
  chrome.action.setTitle({ title: `Life Copilot web chats — ${title}` });
}

// ---------------------------------------------------------------------------
// Fetch strategies: direct from the worker first, then inside a same-origin
// page (robots.txt, falling back to the full app if Cloudflare insists).
// ---------------------------------------------------------------------------
async function workerFetch(ctx, path) {
  const headers = {};
  if (ctx.provider === 'chatgpt') {
    if (!ctx.token) {
      const session = await rawFetch(`${PROVIDERS.chatgpt.origin}/api/auth/session`, {});
      ctx.token = session.json && session.json.accessToken ? session.json.accessToken : '';
      if (!ctx.token) return { status: 401, json: null, error: 'no_session', detail: sessionDetail(session) };
    }
    headers.Authorization = `Bearer ${ctx.token}`;
  }
  if (ctx.provider === 'deepseek') {
    // DeepSeek keeps its login in the page's localStorage, which a worker
    // cannot read; apiGet switches to a same-origin page.
    return { status: 401, json: null, error: 'no_session', detail: 'DeepSeek login is only readable inside its page' };
  }
  return rawFetch(PROVIDERS[ctx.provider].origin + path, headers);
}

// Describes a session reply without an access token by its key names only.
function sessionDetail(result) {
  const json = result.json;
  const shape = json && typeof json === 'object' ? `keys: ${Object.keys(json).join(', ') || 'none'}` : 'not JSON';
  return `/api/auth/session gave no access token (HTTP ${result.status}, ${shape})`;
}

// A short reason for a failed request: the session problem, the API's own
// error text, or the fetch error. Never includes tokens.
function failureDetail(result) {
  if (result.detail) return result.detail;
  const body = result.json;
  const reason = body && typeof body === 'object' ? body.detail || body.error || body.message : '';
  if (reason) return String(typeof reason === 'string' ? reason : reason.message || JSON.stringify(reason)).slice(0, 200);
  return result.error || '';
}

// DeepSeek answers HTTP 200 with its own error codes inside the envelope
// {code, msg, data: {biz_code, biz_msg, biz_data}}; map them onto statuses.
function unwrapDeepseek(result) {
  const body = result.json;
  if (result.status !== 200 || !body || typeof body !== 'object' || !('code' in body)) return result;
  if (body.code !== 0) {
    const status = [40001, 40002, 40003].includes(body.code) ? 401 : 502;
    return { status, json: null, detail: `DeepSeek code ${body.code}: ${String(body.msg || '').slice(0, 200)}` };
  }
  const data = body.data || {};
  if (data.biz_code !== undefined && data.biz_code !== 0) {
    return { status: 502, json: null, detail: `DeepSeek biz_code ${data.biz_code}: ${String(data.biz_msg || '').slice(0, 200)}` };
  }
  return { status: 200, json: data.biz_data === undefined ? null : data.biz_data };
}

async function rawFetch(url, headers) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 60000);
  try {
    const response = await fetch(url, { headers, credentials: 'include', signal: controller.signal });
    const text = await response.text();
    let json = null;
    try {
      json = JSON.parse(text);
    } catch (_) {
      json = null;
    }
    return { status: response.status, json };
  } catch (error) {
    return { status: 0, json: null, error: String(error) };
  } finally {
    clearTimeout(timer);
  }
}

async function pageFetch(ctx, path) {
  const [injection] = await chrome.scripting.executeScript({
    target: { tabId: ctx.tabId },
    world: 'MAIN',
    args: [ctx.provider, path],
    func: async (provider, requestPath) => {
      const headers = {};
      if (provider === 'chatgpt') {
        const cached = window.__lifeCopilotSession;
        if (!cached || Date.now() - cached.at > 5 * 60 * 1000) {
          let token = '';
          let detail = '';
          try {
            const response = await fetch('/api/auth/session', { credentials: 'include' });
            let session = null;
            try {
              session = JSON.parse(await response.text());
            } catch (_) {
              session = null;
            }
            token = (response.ok && session && session.accessToken) || '';
            if (!token) {
              const shape = session && typeof session === 'object'
                ? `keys: ${Object.keys(session).join(', ') || 'none'}`
                : 'not JSON';
              detail = `/api/auth/session gave no access token (HTTP ${response.status}, ${shape})`;
            }
          } catch (error) {
            detail = `/api/auth/session failed: ${error}`;
          }
          window.__lifeCopilotSession = { token, detail, at: Date.now() };
        }
        if (!window.__lifeCopilotSession.token) {
          return { status: 401, json: null, error: 'no_session', detail: window.__lifeCopilotSession.detail };
        }
        headers.Authorization = `Bearer ${window.__lifeCopilotSession.token}`;
      }
      if (provider === 'deepseek') {
        // The web app keeps its login as {"value": token} in localStorage.
        // Without one the request still carries the browser's cookies, and
        // DeepSeek's own reply (code 40003 when logged out) decides.
        let token = '';
        try {
          const parsed = JSON.parse(localStorage.getItem('userToken') || 'null');
          token = parsed && typeof parsed.value === 'string' ? parsed.value : '';
        } catch (_) {
          token = '';
        }
        if (token) headers.Authorization = `Bearer ${token}`;
        headers['x-client-platform'] = 'web';
      }
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 60000);
      try {
        const response = await fetch(requestPath, { headers, credentials: 'include', signal: controller.signal });
        const text = await response.text();
        let json = null;
        try {
          json = JSON.parse(text);
        } catch (_) {
          json = null;
        }
        return { status: response.status, json };
      } catch (error) {
        return { status: 0, json: null, error: String(error) };
      } finally {
        clearTimeout(timer);
      }
    },
  });
  return injection && injection.result ? injection.result : { status: 0, json: null, error: 'no result' };
}

async function openPageTab(ctx, path) {
  const url = PROVIDERS[ctx.provider].origin + path;
  if (ctx.tabId) {
    await chrome.tabs.update(ctx.tabId, { url });
  } else {
    const tab = await chrome.tabs.create({ windowId: await pageWindowId(), url, active: false });
    ctx.tabId = tab.id;
    ctx.cleanup.push(() => chrome.tabs.remove(tab.id));
  }
  await waitForTabComplete(ctx.tabId, url);
}

// Page tabs open in the background of an existing window. Chrome started by
// copilot.py has none, and closing the only window of such a Chrome stopped
// this worker and dropped the native host mid-sync: on 2026-09-24 a failed
// Claude sync closed its window before ChatGPT ran. So a window opened here
// holds a blank tab and stays open, and removing a sync tab never closes it.
// copilot.py quits a Chrome it launched once the sync is done.
async function pageWindowId() {
  const windows = await chrome.windows.getAll({ windowTypes: ['normal'] });
  if (windows.length) return windows[0].id;
  const win = await chrome.windows.create({ url: 'about:blank', focused: false, state: 'minimized' });
  return win.id;
}

// Resolves once the tab has loaded `url`. The initial check compares paths so
// a tab still showing the previous page is not mistaken for the new one.
function waitForTabComplete(tabId, url) {
  const expectedPath = new URL(url).pathname;
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(listener);
      if (error) reject(error);
      else resolve();
    };
    const timer = setTimeout(
      () => finish(new SyncError('tab_timeout', `Tab did not finish loading ${url}`)),
      TAB_LOAD_TIMEOUT_MS,
    );
    const listener = (updatedId, info) => {
      if (updatedId === tabId && info.status === 'complete') finish();
    };
    chrome.tabs.onUpdated.addListener(listener);
    chrome.tabs
      .get(tabId)
      .then((tab) => {
        if (tab.status === 'complete' && tab.url && new URL(tab.url).pathname === expectedPath) finish();
      })
      .catch(() => {});
  });
}

async function apiGet(ctx, path) {
  let transientRetries = 0;
  let rateLimitRetries = 0;
  for (;;) {
    await sleep(PROVIDERS[ctx.provider].requestGapMs);
    const fetched = ctx.mode === 'worker' ? await workerFetch(ctx, path) : await pageFetch(ctx, path);
    const result = ctx.provider === 'deepseek' ? unwrapDeepseek(fetched) : fetched;
    if (result.status === 200 && result.json !== null) return result.json;

    if (result.status === 429) {
      if (rateLimitRetries < 1) {
        rateLimitRetries += 1;
        await sleep(RATE_LIMIT_WAIT_MS);
        continue;
      }
      throw new SyncError('rate_limited', `${ctx.provider}: rate limited (HTTP 429) for ${path}`);
    }
    const transient = result.status === 0 || result.status >= 500;
    if (transient && transientRetries < 3) {
      transientRetries += 1;
      await sleep(2000 * transientRetries * transientRetries);
      continue;
    }
    const detail = failureDetail(result);
    const reason = `HTTP ${result.status}${detail ? `: ${detail}` : ''}`;
    if (ctx.mode === 'worker') {
      log('info', `${ctx.provider}: worker fetch got ${reason} for ${path}; switching to page context`);
      ctx.mode = 'page';
      await openPageTab(ctx, PROVIDERS[ctx.provider].bootstrapPath);
      continue;
    }
    if (!ctx.fullPageTried && (result.json === null || result.status === 403)) {
      log('info', `${ctx.provider}: page fetch got ${reason}; loading the full app page`);
      ctx.fullPageTried = true;
      await openPageTab(ctx, PROVIDERS[ctx.provider].fullPagePath);
      await sleep(3000);
      continue;
    }
    if (result.status === 401 || result.status === 403 || result.error === 'no_session') {
      throw new SyncError('auth_required', `${ctx.provider}: not logged in (${reason})`);
    }
    throw new SyncError('http_error', `${ctx.provider}: ${reason} for ${path}`);
  }
}

// ---------------------------------------------------------------------------
// Providers
// ---------------------------------------------------------------------------
function timeValue(value) {
  const millis = typeof value === 'number' ? value * 1000 : Date.parse(value);
  return Number.isFinite(millis) ? millis : 0;
}

// Downloads changed conversations newest first. On rate limiting it stops and
// reports what is left, so the host can tell whether a given day is complete;
// the leftovers stay unknown and are picked up by the next sync.
async function fetchChanged(ctx, requestId, items, known, pathFor) {
  const changed = items
    .filter((item) => known[item.id] !== item.update_time)
    .sort((a, b) => timeValue(b.update_time) - timeValue(a.update_time));
  let fetched = 0;
  const errors = [];
  for (let i = 0; i < changed.length; i += 1) {
    const item = changed[i];
    try {
      const conversation = await apiGet(ctx, pathFor(item));
      post({ type: 'conversation', request_id: requestId, provider: ctx.provider, ...item, conversation });
      fetched += 1;
    } catch (error) {
      if (error.code === 'rate_limited') {
        const pending = changed.slice(i);
        log('warn', `${ctx.provider}: rate limited; ${pending.length} conversation(s) left for the next sync`);
        return {
          fetched,
          errors,
          rate_limited: true,
          pending: pending.length,
          pending_newest_update_time: pending[0].update_time,
        };
      }
      if (error.code === 'auth_required' || error.code === 'host_disconnected') throw error;
      errors.push(`${item.id}: ${error.message}`);
    }
  }
  return { fetched, errors, rate_limited: false, pending: 0, pending_newest_update_time: '' };
}

async function syncClaude(ctx, requestId, known) {
  const orgs = await apiGet(ctx, '/api/organizations');
  if (!Array.isArray(orgs) || !orgs.length) throw new SyncError('auth_required', 'claude: no organizations for this login');
  const chatOrgs = orgs.filter((org) => (org.capabilities || []).includes('chat'));
  const listed = new Map();
  const pageSize = 50;
  for (const org of chatOrgs.length ? chatOrgs : orgs) {
    const orgId = encodeURIComponent(org.uuid);
    for (let offset = 0; ; offset += pageSize) {
      const page = await apiGet(ctx, `/api/organizations/${orgId}/chat_conversations?limit=${pageSize}&offset=${offset}`);
      if (!Array.isArray(page)) throw new SyncError('unexpected_response', 'claude: conversation list is not an array');
      let fresh = 0;
      for (const conv of page) {
        if (!conv || !conv.uuid || listed.has(conv.uuid)) continue;
        fresh += 1;
        const tags = [];
        if (conv.platform === 'VOICE') tags.push('voice');
        if (conv.project && conv.project.name) tags.push(`project:${conv.project.name}`);
        listed.set(conv.uuid, {
          id: conv.uuid,
          org_uuid: org.uuid,
          title: conv.name || '',
          created_at: conv.created_at || '',
          update_time: conv.updated_at || '',
          tags,
        });
      }
      if (page.length < pageSize || fresh === 0) break;
    }
  }
  post({ type: 'index', request_id: requestId, provider: 'claude', items: [...listed.values()] });

  const stats = await fetchChanged(
    ctx,
    requestId,
    [...listed.values()],
    known,
    (item) =>
      `/api/organizations/${encodeURIComponent(item.org_uuid)}/chat_conversations/${encodeURIComponent(item.id)}` +
      '?tree=True&rendering_mode=messages&render_all_tools=true',
  );
  return { listed: listed.size, ...stats };
}

async function syncChatGPT(ctx, requestId, known) {
  const listed = new Map();
  const warnings = [];
  const add = (conv, tag) => {
    if (!conv || !conv.id || conv.is_temporary_chat) return;
    const previous = listed.get(conv.id);
    const tags = new Set(previous ? previous.tags : []);
    if (tag) tags.add(tag);
    listed.set(conv.id, {
      id: conv.id,
      title: conv.title || (previous && previous.title) || '',
      created_at: conv.create_time || (previous && previous.created_at) || '',
      update_time: conv.update_time || (previous && previous.update_time) || '',
      tags: [...tags],
    });
  };

  const pageSize = 100;
  const lists = [
    '/backend-api/conversations?order=updated&is_archived=false&is_starred=false',
    '/backend-api/conversations?order=updated&is_archived=false&is_starred=true',
    '/backend-api/conversations?order=updated&is_archived=true',
  ];
  for (const base of lists) {
    for (let offset = 0; ; offset += pageSize) {
      const page = await apiGet(ctx, `${base}&offset=${offset}&limit=${pageSize}`);
      const items = Array.isArray(page.items) ? page.items : [];
      items.forEach((conv) => add(conv, base.includes('is_archived=true') ? 'archived' : ''));
      if (items.length < pageSize) break;
    }
  }

  // ChatGPT Health keeps its own conversation list.
  for (let offset = 0; ; ) {
    const page = await apiGet(ctx, `/backend-api/aip/olympic/chats?offset=${offset}`);
    const items = Array.isArray(page.items) ? page.items : [];
    items.forEach((conv) => add(conv, 'health'));
    offset += items.length;
    if (!items.length || (typeof page.total === 'number' && offset >= page.total)) break;
  }

  // Projects are best-effort: their shape is less stable than the main lists.
  try {
    let cursor = '';
    for (let guard = 0; guard < 50; guard += 1) {
      const sidebar = await apiGet(
        ctx,
        `/backend-api/gizmos/snorlax/sidebar?conversations_per_gizmo=0&limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`,
      );
      for (const entry of sidebar.items || []) {
        const gizmo = entry && entry.gizmo ? entry.gizmo.gizmo || entry.gizmo : null;
        if (!gizmo || !gizmo.id) {
          warnings.push('project entry without id');
          continue;
        }
        const name = (gizmo.display && gizmo.display.name) || gizmo.id;
        let projectCursor = '0';
        for (let pageGuard = 0; pageGuard < 100 && projectCursor !== null && projectCursor !== undefined; pageGuard += 1) {
          const page = await apiGet(
            ctx,
            `/backend-api/gizmos/${encodeURIComponent(gizmo.id)}/conversations?cursor=${encodeURIComponent(projectCursor)}`,
          );
          const items = Array.isArray(page.items) ? page.items : [];
          items.forEach((conv) => add(conv, `project:${name}`));
          if (!items.length) break;
          projectCursor = page.cursor;
        }
      }
      cursor = sidebar.cursor;
      if (!cursor) break;
    }
  } catch (error) {
    if (error.code === 'auth_required') throw error;
    warnings.push(`projects: ${error.message}`);
  }

  post({ type: 'index', request_id: requestId, provider: 'chatgpt', items: [...listed.values()] });

  const stats = await fetchChanged(
    ctx,
    requestId,
    [...listed.values()],
    known,
    (item) => `/backend-api/conversation/${encodeURIComponent(item.id)}`,
  );
  return { listed: listed.size, ...stats, warnings };
}

async function syncDeepseek(ctx, requestId, known) {
  const listed = new Map();
  let cursor = '';
  for (let guard = 0; guard < 200; guard += 1) {
    const page = await apiGet(ctx, `/api/v0/chat_session/fetch_page?count=100${cursor}`);
    const sessions = page && Array.isArray(page.chat_sessions) ? page.chat_sessions : null;
    if (!sessions) throw new SyncError('unexpected_response', 'deepseek: session list has no chat_sessions');
    let fresh = 0;
    for (const session of sessions) {
      if (!session || !session.id || listed.has(session.id)) continue;
      fresh += 1;
      const tags = session.pinned ? ['pinned'] : [];
      listed.set(session.id, {
        id: session.id,
        title: session.title || '',
        created_at: session.inserted_at || '',
        update_time: session.updated_at || '',
        tags,
      });
    }
    const last = sessions[sessions.length - 1];
    if (!page.has_more || !fresh || !last) break;
    cursor = `&lte_cursor.updated_at=${encodeURIComponent(last.updated_at)}&lte_cursor.pinned=${last.pinned ? 'true' : 'false'}`;
  }
  post({ type: 'index', request_id: requestId, provider: 'deepseek', items: [...listed.values()] });

  const stats = await fetchChanged(
    ctx,
    requestId,
    [...listed.values()],
    known,
    (item) => `/api/v0/chat/history_messages?chat_session_id=${encodeURIComponent(item.id)}`,
  );
  return { listed: listed.size, ...stats };
}

function extractGeminiTokensFromHtml(html) {
  if (!html || typeof html !== 'string') return null;
  const atMatch = html.match(/"?SNlM0e"?\s*:\s*"([^"]+)"/);
  if (!atMatch) return null;
  const blMatch = html.match(/"?cfb2h"?\s*:\s*"([^"]+)"/);
  const fsidMatch = html.match(/"?FdrFJe"?\s*:\s*"([^"]+)"/);
  const userMatch = html.match(/"?oPEP7c"?\s*:\s*"([^"]*)"/);
  return {
    at: atMatch[1],
    bl: blMatch ? blMatch[1] : '',
    fsid: fsidMatch ? fsidMatch[1] : '',
    signedIn: Boolean(userMatch && userMatch[1]),
  };
}

function parseGeminiBatchResponse(text, rpcId) {
  const cleaned = String(text || '').replace(/^\)\]\}'\s*/, '');
  const results = [];
  const errors = [];
  let sawUnauth = false;
  const visit = (node) => {
    if (!Array.isArray(node)) return;
    if (node[0] === 'wrb.fr' && node[1] === rpcId) {
      if (typeof node[2] === 'string') {
        try {
          results.push(JSON.parse(node[2]));
        } catch (_) {
          // Ignore malformed chunk.
        }
      } else {
        if (node[5] !== undefined && node[5] !== null) errors.push(node[5]);
        if (Array.isArray(node[5]) && node[5].includes(16)) sawUnauth = true;
      }
      return;
    }
    if (node[0] === 'er' && Array.isArray(node[5])) {
      errors.push(node[5]);
      if (node[5].includes(16) || node[5].includes(8)) sawUnauth = true;
      return;
    }
    for (const child of node) visit(child);
  };
  for (const line of cleaned.split('\n')) {
    const trimmed = line.trim();
    const start = trimmed.indexOf('[');
    if (start === -1) continue;
    try {
      visit(JSON.parse(trimmed.slice(start)));
    } catch (_) {
      // Ignore non-JSON chunk length or trailer lines.
    }
  }
  if (!results.length) {
    try {
      visit(JSON.parse(cleaned));
    } catch (_) {
      // Ignore if chunked.
    }
  }
  return { payload: results.length ? results[0] : null, allPayloads: results, sawUnauth, errors };
}

function extractGeminiTimestamp(node, depth = 0) {
  if (depth > 4 || !Array.isArray(node)) return '';
  if (
    node.length === 2
    && Number.isInteger(node[0])
    && node[0] > 1500000000
    && node[0] < 4000000000
    && Number.isInteger(node[1])
    && node[1] >= 0
    && node[1] < 1000000000
  ) {
    const ms = node[0] * 1000 + Math.floor(node[1] / 1000000);
    return new Date(ms).toISOString();
  }
  for (const child of node) {
    if (Array.isArray(child)) {
      const found = extractGeminiTimestamp(child, depth + 1);
      if (found) return found;
    }
  }
  return '';
}

function extractGeminiListAndCursor(data) {
  if (!Array.isArray(data)) return { items: [], nextCursor: null };
  const isConvItem = (entry) =>
    Array.isArray(entry) && typeof entry[0] === 'string' && entry[0].startsWith('c_');
  let items = [];
  for (const candidate of data) {
    if (Array.isArray(candidate) && candidate.some(isConvItem)) {
      items = candidate.filter(isConvItem);
      break;
    }
  }
  let nextCursor = null;
  for (const candidate of data) {
    if (typeof candidate === 'string' && candidate && !candidate.startsWith('c_')) {
      nextCursor = candidate;
      break;
    }
  }
  return { items, nextCursor };
}

async function geminiLoadTokensInPage(ctx) {
  ctx.mode = 'page';
  await openPageTab(ctx, PROVIDERS.gemini.fullPagePath);
  const [injection] = await chrome.scripting.executeScript({
    target: { tabId: ctx.tabId },
    world: 'MAIN',
    func: () => {
      const wiz = window.WIZ_global_data || {};
      return {
        url: window.location.href,
        at: typeof wiz.SNlM0e === 'string' ? wiz.SNlM0e : '',
        bl: typeof wiz.cfb2h === 'string' ? wiz.cfb2h : '',
        fsid: typeof wiz.FdrFJe === 'string' ? wiz.FdrFJe : '',
        signedIn: Boolean(wiz.oPEP7c || wiz.S06Grb),
      };
    },
  });
  const res = injection && injection.result;
  if (!res || !res.at || !res.signedIn || (res.url && res.url.includes('accounts.google.com'))) {
    throw new SyncError('auth_required', 'gemini: not logged in at gemini.google.com');
  }
  return { at: res.at, bl: res.bl || '', fsid: res.fsid || '', signedIn: res.signedIn };
}

async function geminiLoadTokens(ctx) {
  const response = await fetch(`${PROVIDERS.gemini.origin}/app`, { credentials: 'include' });
  const html = await response.text();
  if (response.url && response.url.includes('accounts.google.com')) {
    throw new SyncError('auth_required', 'gemini: not logged in at gemini.google.com');
  }
  const tokens = extractGeminiTokensFromHtml(html);
  if (tokens && tokens.signedIn) return tokens;

  log('info', `gemini: worker /app had tokens=${Boolean(tokens)} signedIn=${Boolean(tokens && tokens.signedIn)}; trying page context`);
  return geminiLoadTokensInPage(ctx);
}

async function geminiPostRaw(ctx, url, body) {
  if (ctx.mode === 'page' && ctx.tabId) {
    const path = new URL(url).pathname + new URL(url).search;
    const [injection] = await chrome.scripting.executeScript({
      target: { tabId: ctx.tabId },
      world: 'MAIN',
      args: [path, body],
      func: async (requestPath, requestBody) => {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 60000);
        try {
          const response = await fetch(requestPath, {
            method: 'POST',
            credentials: 'include',
            headers: {
              'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
              'X-Same-Domain': '1',
            },
            body: requestBody,
            signal: controller.signal,
          });
          return { status: response.status, text: await response.text() };
        } catch (error) {
          return { status: 0, text: '', error: String(error) };
        } finally {
          clearTimeout(timer);
        }
      },
    });
    return injection && injection.result ? injection.result : { status: 0, text: '', error: 'no result' };
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 60000);
  try {
    const response = await fetch(url, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
        'X-Same-Domain': '1',
      },
      body,
      signal: controller.signal,
    });
    return { status: response.status, text: await response.text() };
  } catch (error) {
    return { status: 0, text: '', error: String(error) };
  } finally {
    clearTimeout(timer);
  }
}

async function geminiBatchExecute(ctx, tokens, rpcId, payload) {
  const params = new URLSearchParams({
    rpcids: rpcId,
    'source-path': '/app',
    hl: 'en',
    _reqid: String(Math.floor(Math.random() * 900000) + 100000),
    rt: 'c',
  });
  if (tokens.bl) params.set('bl', tokens.bl);
  if (tokens.fsid) params.set('f.sid', tokens.fsid);
  const url = `${PROVIDERS.gemini.origin}/_/BardChatUi/data/batchexecute?${params.toString()}`;
  const body = new URLSearchParams({
    'f.req': JSON.stringify([[[rpcId, JSON.stringify(payload), null, 'generic']]]),
    at: tokens.at,
  }).toString();

  let transientRetries = 0;
  let rateLimitRetries = 0;
  for (;;) {
    await sleep(PROVIDERS.gemini.requestGapMs);
    const result = await geminiPostRaw(ctx, url, body);
    if (result.status === 429) {
      if (rateLimitRetries < 1) {
        rateLimitRetries += 1;
        await sleep(RATE_LIMIT_WAIT_MS);
        continue;
      }
      throw new SyncError('rate_limited', `gemini: rate limited (HTTP 429) for ${rpcId}`);
    }
    const transient = result.status === 0 || result.status >= 500;
    if (transient && transientRetries < 3) {
      transientRetries += 1;
      await sleep(2000 * transientRetries * transientRetries);
      continue;
    }
    if (result.status === 401 || result.status === 403) {
      throw new SyncError('auth_required', `gemini: not logged in (HTTP ${result.status})`);
    }
    if (result.status !== 200) {
      throw new SyncError('http_error', `gemini: HTTP ${result.status} for ${rpcId}`);
    }
    const parsed = parseGeminiBatchResponse(result.text, rpcId);
    if (parsed.sawUnauth) {
      throw new SyncError('auth_required', `gemini: session expired for ${rpcId}`);
    }
    if (parsed.payload === null) {
      const head = String(result.text || '').replace(/\s+/g, ' ').slice(0, 140);
      log('warn', `gemini: empty ${rpcId} payload errors=${JSON.stringify(parsed.errors)} len=${(result.text || '').length} head=${head}`);
      throw new SyncError('unexpected_response', `gemini: empty ${rpcId} response`);
    }
    return parsed.payload;
  }
}

async function syncGemini(ctx, requestId, known) {
  const POST_TAKEOUT_CUTOFF_MS = Date.parse('2026-09-16T00:00:00.000Z');
  const MAX_CONVS_PER_SYNC = 40;
  let tokens = await geminiLoadTokens(ctx);
  const listed = new Map();
  const warnings = [];
  let cursor = null;
  for (let guard = 0; guard < 50; guard += 1) {
    let data;
    try {
      data = await geminiBatchExecute(ctx, tokens, 'MaZiqc', [20, cursor, [0, null, 1]]);
    } catch (err) {
      const retryable = err.code === 'unexpected_response' || err.code === 'http_error';
      if (guard === 0 && retryable) {
        log('info', `gemini: initial MaZiqc failed (${err.message}); retrying in page context with [13, null, [0, null, 1]]`);
        if (ctx.mode !== 'page') {
          tokens = await geminiLoadTokensInPage(ctx);
        }
        data = await geminiBatchExecute(ctx, tokens, 'MaZiqc', [13, null, [0, null, 1]]);
      } else if (guard > 0 && listed.size > 0 && retryable) {
        const msg = `MaZiqc page ${guard} failed after listing ${listed.size} conversation(s): ${err.message}`;
        warnings.push(msg);
        log('warn', `gemini: ${msg}`);
        break;
      } else {
        throw err;
      }
    }
    const { items, nextCursor } = extractGeminiListAndCursor(data);
    let fresh = 0;
    let unchangedOnPage = 0;
    const pageTimes = [];
    for (const c of items) {
      const rawId = String(c[0] || '');
      const id = rawId.replace(/^c_/, '');
      if (!id) continue;
      const updateTime = extractGeminiTimestamp(c);
      const ms = timeValue(updateTime);
      if (ms > 0) pageTimes.push(ms);
      if (updateTime && known[id] === updateTime) unchangedOnPage += 1;
      if (listed.has(id)) continue;
      fresh += 1;
      listed.set(id, {
        id,
        raw_id: rawId,
        title: typeof c[1] === 'string' ? c[1] : '',
        created_at: '',
        update_time: updateTime,
        tags: [],
        list_item: c,
      });
    }
    const allKnownUnchanged = items.length > 0 && unchangedOnPage === items.length;
    const beforeTakeoutCutoff = pageTimes.length > 0 && Math.max(...pageTimes) < POST_TAKEOUT_CUTOFF_MS;
    if (!nextCursor || fresh === 0 || allKnownUnchanged || beforeTakeoutCutoff) break;
    cursor = nextCursor;
  }
  log('info', `gemini: listed ${listed.size} conversation(s) in mode=${ctx.mode}`);
  post({
    type: 'index',
    request_id: requestId,
    provider: 'gemini',
    items: [...listed.values()].map(({ list_item, raw_id, ...rest }) => rest),
  });

  const changed = [...listed.values()]
    .filter((item) => {
      if (item.update_time && known[item.id] === item.update_time) return false;
      const ms = timeValue(item.update_time);
      if (ms > 0 && ms < POST_TAKEOUT_CUTOFF_MS && !known[item.id]) return false;
      return true;
    })
    .sort((a, b) => timeValue(b.update_time) - timeValue(a.update_time));
  const batch = changed.slice(0, MAX_CONVS_PER_SYNC);
  const deferred = changed.slice(MAX_CONVS_PER_SYNC);

  let fetched = 0;
  const errors = [];
  for (let i = 0; i < batch.length; i += 1) {
    const item = batch[i];
    try {
      const pages = [];
      let turnCursor = null;
      let useShortArgs = false;
      for (let pageGuard = 0; pageGuard < 50; pageGuard += 1) {
        let turnData;
        if (useShortArgs) {
          turnData = await geminiBatchExecute(ctx, tokens, 'hNvQHb', [item.raw_id, turnCursor, null]);
        } else {
          try {
            turnData = await geminiBatchExecute(
              ctx,
              tokens,
              'hNvQHb',
              [item.raw_id, 50, turnCursor, 1, [1], [4], null, 1],
            );
          } catch (err) {
            if (pageGuard === 0 && err.code === 'unexpected_response') {
              useShortArgs = true;
              turnData = await geminiBatchExecute(ctx, tokens, 'hNvQHb', [item.raw_id, null, null]);
            } else {
              throw err;
            }
          }
        }
        pages.push(turnData);
        const nextTurnCursor =
          Array.isArray(turnData) && typeof turnData[1] === 'string' && turnData[1]
            ? turnData[1]
            : null;
        if (!nextTurnCursor || nextTurnCursor === turnCursor) break;
        turnCursor = nextTurnCursor;
      }
      post({
        type: 'conversation',
        request_id: requestId,
        provider: 'gemini',
        id: item.id,
        title: item.title,
        created_at: item.created_at,
        update_time: item.update_time,
        tags: item.tags,
        conversation: {
          id: item.id,
          raw_id: item.raw_id,
          title: item.title,
          update_time: item.update_time,
          list_item: item.list_item,
          pages,
        },
      });
      fetched += 1;
    } catch (error) {
      if (error.code === 'rate_limited') {
        const pending = changed.slice(i);
        log('warn', `gemini: rate limited; ${pending.length} conversation(s) left for the next sync`);
        return {
          listed: listed.size,
          fetched,
          errors,
          rate_limited: true,
          pending: pending.length,
          pending_newest_update_time: pending[0].update_time,
          warnings,
        };
      }
      if (error.code === 'auth_required' || error.code === 'host_disconnected') throw error;
      errors.push(`${item.id}: ${error.message}`);
    }
  }
  return {
    listed: listed.size,
    fetched,
    errors,
    rate_limited: false,
    pending: deferred.length,
    pending_newest_update_time: deferred.length ? deferred[0].update_time : '',
    warnings,
  };
}

const SYNCERS = { claude: syncClaude, chatgpt: syncChatGPT, deepseek: syncDeepseek, gemini: syncGemini };

async function runSync(message) {
  const requestId = message.request_id;
  if (activeSync) {
    post({ type: 'done', request_id: requestId, ok: false, providers: {}, error: 'busy' });
    return;
  }
  activeSync = requestId;
  const providers = {};
  try {
    for (const provider of message.providers || Object.keys(SYNCERS)) {
      const syncer = SYNCERS[provider];
      if (!syncer) {
        providers[provider] = { ok: false, code: 'unknown_provider', message: provider };
        continue;
      }
      const ctx = { provider, mode: 'worker', tabId: null, token: '', fullPageTried: false, cleanup: [] };
      const started = Date.now();
      try {
        const stats = await syncer(ctx, requestId, (message.known && message.known[provider]) || {});
        providers[provider] = { ok: true, mode: ctx.mode, seconds: (Date.now() - started) / 1000, ...stats };
      } catch (error) {
        providers[provider] = { ok: false, mode: ctx.mode, code: error.code || 'error', message: String(error.message || error) };
      } finally {
        for (const cleanup of ctx.cleanup) {
          try {
            await cleanup();
          } catch (_) {
            // Tab or window already closed.
          }
        }
      }
    }
  } finally {
    activeSync = null;
  }
  const ok = Object.values(providers).every((result) => result.ok);
  setStatus(ok ? 'ok' : 'error', ok ? `last sync ${new Date().toLocaleString()}` : JSON.stringify(providers));
  try {
    post({ type: 'done', request_id: requestId, ok, providers });
  } catch (error) {
    setStatus('error', error.message);
  }
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------
async function ensureAlarms() {
  if (!(await chrome.alarms.get('keepalive'))) {
    chrome.alarms.create('keepalive', { periodInMinutes: 1 });
  }
  if (!(await chrome.alarms.get('periodic-sync'))) {
    chrome.alarms.create('periodic-sync', { delayInMinutes: 5, periodInMinutes: 60 });
  }
}

chrome.runtime.onStartup.addListener(() => {
  ensureAlarms();
  connect();
});
chrome.runtime.onInstalled.addListener(() => {
  ensureAlarms();
  connect();
});
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'keepalive') connect();
  if (alarm.name === 'periodic-sync') requestSync('alarm');
});
chrome.action.onClicked.addListener(() => requestSync('action'));

connect();
