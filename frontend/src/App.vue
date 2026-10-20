<script setup>
import { computed, nextTick, ref, watch } from 'vue'

const url = ref('')
const manualTitle = ref('')
const pastedText = ref('')
const articleResult = ref(null)
const selectedTerm = ref('')
const question = ref('')
const messages = ref([])
const studyNote = ref('')
const studyRecords = ref([])
const readArticles = ref([])
const industryIssues = ref([])
const selectedIssueId = ref('')
const readMessage = ref('')
const sessionChoices = ref([])
const sessionId = ref('')
const sessionToken = ref('')
const sessionReady = ref(false)
const busy = ref(false)
const currentStatus = ref('')
const errorMessage = ref('')
const saveMessage = ref('')
const chatPanel = ref(null)
let activeController = null
const SESSION_STORAGE_KEY = 'pharmamate.sessions.v1'

const terms = computed(() => articleResult.value?.analysis?.key_terms ?? [])
const currentTerm = computed(() => terms.value.find((item) => item.term === selectedTerm.value) ?? null)
const canSave = computed(() => Boolean(currentTerm.value && articleResult.value?.article_id && messages.value.some((item) => item.role === 'assistant' && item.content)))

watch(messages, async () => {
  await nextTick()
  if (chatPanel.value) chatPanel.value.scrollTop = chatPanel.value.scrollHeight
}, { deep: true })

async function requestJson(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers ?? {}) },
  })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    const error = new Error(payload.detail || `요청 실패 (${response.status})`)
    error.status = response.status
    throw error
  }
  return payload
}

async function sessionRequest(path, options = {}) {
  return requestJson(path, {
    ...options,
    headers: {
      Authorization: `Bearer ${sessionToken.value}`,
      ...(options.headers ?? {}),
    },
  })
}

function persistSessionChoices() {
  localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(sessionChoices.value))
}

function termStorageKey(value) {
  const term = String(value || '').trim()
  const acronyms = [...term.matchAll(/\(([A-Za-z][A-Za-z0-9+-]{1,15})\)/g)]
  if (acronyms.length) return acronyms.at(-1)[1].toLowerCase()
  if (/^[A-Za-z][A-Za-z0-9+-]{1,15}$/.test(term)) return term.toLowerCase()
  return term.replace(/[\s_-]+/g, '').toLowerCase()
}

function restoreSnapshot(snapshot) {
  articleResult.value = snapshot.article
  const savedTerm = snapshot.turns.at(-1)?.term_name
  const selectedByKey = terms.value.find((term) => termStorageKey(term.term) === snapshot.selected_term_key)?.term
  selectedTerm.value = terms.value.some((term) => term.term === savedTerm)
    ? savedTerm
    : selectedByKey ?? terms.value[0]?.term ?? ''
  messages.value = snapshot.turns.flatMap((turn) => [
    { role: 'user', content: turn.question },
    {
      role: 'assistant', content: turn.answer, sources: turn.sources,
      recommendations: turn.recommendations, route: turn.route,
      relatedToSelected: turn.related_to_selected, selectedTerm: turn.term_name,
      validationStatus: turn.validation_status, validationRetries: turn.validation_retries,
    },
  ])
  studyNote.value = ''
  saveMessage.value = ''
  readMessage.value = ''
  selectedIssueId.value = ''
}

async function activateSession(credentials) {
  sessionId.value = credentials.session_id
  sessionToken.value = credentials.access_token
  const snapshot = await sessionRequest(`/api/sessions/${sessionId.value}`)
  sessionChoices.value = [credentials, ...sessionChoices.value.filter((item) => item.session_id !== credentials.session_id)]
  persistSessionChoices()
  restoreSnapshot(snapshot)
  await refreshRecords()
  await refreshReadingLists()
  currentStatus.value = '저장된 학습 세션을 불러왔습니다.'
}

async function createSession() {
  const created = await requestJson('/api/sessions', { method: 'POST', body: '{}' })
  const credentials = {
    session_id: created.session_id,
    access_token: created.access_token,
    created_at: created.created_at,
  }
  sessionChoices.value = [credentials, ...sessionChoices.value.filter((item) => item.session_id !== credentials.session_id)]
  persistSessionChoices()
  await activateSession(credentials)
}

async function initializeSession() {
  currentStatus.value = '저장된 학습 세션을 확인합니다.'
  try {
    try {
      const stored = JSON.parse(localStorage.getItem(SESSION_STORAGE_KEY) || '[]')
      sessionChoices.value = Array.isArray(stored)
        ? stored.filter((item) => item?.session_id && item?.access_token)
        : []
    } catch {
      sessionChoices.value = []
      localStorage.removeItem(SESSION_STORAGE_KEY)
    }
    for (const credentials of [...sessionChoices.value]) {
      try {
        await activateSession(credentials)
        return
      } catch (error) {
        if (error.status !== 404) throw error
        sessionChoices.value = sessionChoices.value.filter((item) => item.session_id !== credentials.session_id)
      }
    }
    persistSessionChoices()
    await createSession()
  } catch (error) {
    errorMessage.value = error.message
    currentStatus.value = ''
  } finally {
    sessionReady.value = true
  }
}

async function switchSession(nextSessionId) {
  const credentials = sessionChoices.value.find((item) => item.session_id === nextSessionId)
  if (!credentials || busy.value) return
  busy.value = true
  errorMessage.value = ''
  try {
    await activateSession(credentials)
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    busy.value = false
  }
}

async function startNewSession() {
  if (busy.value) return
  busy.value = true
  errorMessage.value = ''
  try {
    await createSession()
    url.value = ''
    manualTitle.value = ''
    pastedText.value = ''
    currentStatus.value = '새 학습 세션을 시작했습니다.'
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    busy.value = false
  }
}

async function analyzeArticle() {
  errorMessage.value = ''
  saveMessage.value = ''
  readMessage.value = ''
  selectedIssueId.value = ''
  if (!url.value.trim() && !pastedText.value.trim()) {
    errorMessage.value = '기사 URL 또는 본문을 입력해 주세요.'
    return
  }
  busy.value = true
  currentStatus.value = '기사를 분석합니다.'
  try {
    const analyzed = await requestJson('/api/articles/analyze', {
      method: 'POST',
      body: JSON.stringify({ url: url.value, pasted_text: pastedText.value, title: manualTitle.value }),
    })
    const firstTerm = analyzed.analysis.key_terms[0]?.term ?? ''
    await sessionRequest(`/api/sessions/${sessionId.value}/article`, {
      method: 'PUT',
      body: JSON.stringify({ article: analyzed, selected_term_key: firstTerm }),
    })
    articleResult.value = analyzed
    selectedTerm.value = firstTerm
    messages.value = []
    studyNote.value = ''
    currentStatus.value = '기사 분석이 완료됐습니다.'
    await refreshRecords()
    await refreshReadingLists()
  } catch (error) {
    errorMessage.value = error.message
    currentStatus.value = ''
  } finally {
    busy.value = false
  }
}

function handleSseEvent(name, data, assistantMessage) {
  if (name === 'status') {
    currentStatus.value = data.message || '응답을 준비합니다.'
  } else if (name === 'token') {
    assistantMessage.content += data.text || ''
  } else if (name === 'sources') {
    assistantMessage.sources = data.items || []
  } else if (name === 'recommendations') {
    assistantMessage.recommendations = data.items || []
  } else if (name === 'done') {
    assistantMessage.route = data.route || ''
    assistantMessage.validationStatus = data.validation_status || ''
    assistantMessage.validationRetries = data.validation_retries || 0
    assistantMessage.relatedToSelected = Boolean(data.related_to_selected)
    currentStatus.value = '답변과 근거 검토가 완료됐습니다.'
  } else if (name === 'error') {
    throw new Error(data.message || '스트리밍 응답을 완료하지 못했습니다.')
  }
}

async function consumeSse(response, assistantMessage) {
  if (!response.body) throw new Error('브라우저에서 스트리밍 본문을 읽을 수 없습니다.')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  function dispatchBlocks() {
    let boundary = buffer.indexOf('\n\n')
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      let eventName = 'message'
      const dataLines = []
      for (const line of block.replace(/\r/g, '').split('\n')) {
        if (line.startsWith('event:')) eventName = line.slice(6).trim()
        if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
      }
      if (dataLines.length) handleSseEvent(eventName, JSON.parse(dataLines.join('\n')), assistantMessage)
      boundary = buffer.indexOf('\n\n')
    }
  }

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
    dispatchBlocks()
  }
  buffer += decoder.decode()
  dispatchBlocks()
}

async function sendQuestion() {
  const asked = question.value.trim()
  if (!asked || busy.value || !sessionReady.value || !sessionId.value) return
  errorMessage.value = ''
  saveMessage.value = ''
  const selected = currentTerm.value
  messages.value.push({ role: 'user', content: asked })
  const assistantMessage = {
    role: 'assistant', content: '', sources: [], recommendations: [],
    relatedToSelected: false, selectedTerm: selected?.term ?? '', validationStatus: '', validationRetries: 0,
  }
  messages.value.push(assistantMessage)
  question.value = ''
  busy.value = true
  activeController = new AbortController()
  currentStatus.value = '질문을 처리합니다.'
  try {
    const response = await fetch(`/api/sessions/${sessionId.value}/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${sessionToken.value}`,
      },
      body: JSON.stringify({
        question: asked,
        term: selected ? `${selected.term}\n${selected.simple_definition}\n${selected.article_context}` : '',
      }),
      signal: activeController.signal,
    })
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}))
      throw new Error(payload.detail || `요청 실패 (${response.status})`)
    }
    await consumeSse(response, assistantMessage)
    if (!assistantMessage.content) throw new Error('Agent가 답변을 반환하지 않았습니다.')
  } catch (error) {
    if (error.name === 'AbortError') {
      assistantMessage.content = '응답을 취소했습니다.'
      currentStatus.value = '요청이 취소됐습니다.'
    } else {
      assistantMessage.content ||= '답변을 받지 못했습니다.'
      errorMessage.value = error.message
      currentStatus.value = ''
    }
  } finally {
    activeController = null
    busy.value = false
  }
}

function cancelResponse() {
  activeController?.abort()
}

function useRecommendation(item) {
  question.value = item.question
  document.querySelector('#question-input')?.focus()
}

async function saveStudyRecord() {
  if (!canSave.value || busy.value) return
  errorMessage.value = ''
  saveMessage.value = ''
  try {
    const result = await sessionRequest(`/api/sessions/${sessionId.value}/study-records`, {
      method: 'POST',
      body: JSON.stringify({
        term: currentTerm.value,
        note: studyNote.value,
      }),
    })
    saveMessage.value = result.message
    await refreshRecords()
  } catch (error) {
    errorMessage.value = error.message
  }
}

async function markArticleRead() {
  if (!articleResult.value || !sessionReady.value || busy.value) return
  errorMessage.value = ''
  readMessage.value = ''
  busy.value = true
  try {
    const result = await sessionRequest(`/api/sessions/${sessionId.value}/articles/mark-read`, {
      method: 'POST',
      body: JSON.stringify({ article: articleResult.value, issue_id: selectedIssueId.value }),
    })
    readMessage.value = result.message
    selectedIssueId.value = ''
    await refreshReadingLists()
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    busy.value = false
  }
}

async function refreshRecords() {
  if (!sessionId.value) return
  try {
    studyRecords.value = await sessionRequest(`/api/sessions/${sessionId.value}/study-records`)
  } catch {
    studyRecords.value = []
  }
}

async function refreshReadingLists() {
  if (!sessionId.value) return
  try {
    const [articles, issues] = await Promise.all([
      sessionRequest(`/api/sessions/${sessionId.value}/articles`),
      sessionRequest(`/api/sessions/${sessionId.value}/industry-issues`),
    ])
    readArticles.value = articles
    industryIssues.value = issues
  } catch {
    readArticles.value = []
    industryIssues.value = []
  }
}

initializeSession()
</script>

<template>
  <main class="app-shell">
    <header class="topbar">
      <a class="brand" href="#top" aria-label="PharmaMate 홈">
        <span class="brand-mark">P</span>
        <span>PharmaMate <small>3.0</small></span>
      </a>
      <div class="topbar-right">
        <span class="local-indicator"><i></i> 세션별 로컬 저장</span>
        <select v-if="sessionChoices.length" v-model="sessionId" class="session-select" aria-label="학습 세션 선택" :disabled="busy" @change="switchSession($event.target.value)">
          <option v-for="session in sessionChoices" :key="session.session_id" :value="session.session_id">
            세션 · {{ new Date(session.created_at).toLocaleString('ko-KR') }}
          </option>
        </select>
        <button class="new-session-button" :disabled="busy || !sessionReady" @click="startNewSession">새 세션 +</button>
        <a class="docs-link" href="http://127.0.0.1:8000/docs" target="_blank" rel="noreferrer">API 문서 ↗</a>
      </div>
    </header>

    <section class="hero" id="top">
      <div>
        <p class="eyebrow">PHARMA & BIOTECH LEARNING AGENT</p>
        <h1>기사를 읽고, 질문하고,<br /><em>배운 내용을 연결하세요.</em></h1>
        <p class="hero-copy">제약·바이오 기사와 개인 학습 기록을 근거로 더 깊이 공부합니다.</p>
      </div>
      <div class="hero-orbit" aria-hidden="true"><span>Rx</span><b></b><i></i></div>
    </section>

    <div v-if="errorMessage" class="alert alert-error" role="alert">
      <span>{{ errorMessage }}</span><button @click="errorMessage = ''" aria-label="닫기">×</button>
    </div>

    <section class="workspace-grid">
      <div class="column-stack">
        <section class="card article-card">
          <div class="section-heading">
            <div><p class="eyebrow">01 · ARTICLE</p><h2>기사 읽기</h2></div>
            <span v-if="articleResult" class="status-pill status-done">분석 완료</span>
          </div>
          <label class="field-label" for="article-url">기사 URL</label>
          <input id="article-url" v-model="url" class="text-input" type="url" placeholder="https://news.example.com/article" />
          <details class="paste-details">
            <summary>기사 본문을 직접 붙여넣기</summary>
            <textarea v-model="pastedText" class="text-input article-textarea" rows="5" placeholder="URL에서 본문을 가져오기 어렵다면 기사 본문을 붙여넣으세요."></textarea>
          </details>
          <label class="field-label" for="article-title">표시 제목 <span>선택</span></label>
          <input id="article-title" v-model="manualTitle" class="text-input" type="text" placeholder="기사 제목을 입력하세요" />
          <button class="button button-primary button-wide" :disabled="busy || !sessionReady || !sessionId" @click="analyzeArticle">
            <span v-if="busy && !messages.length" class="spinner"></span>
            기사 분석하기 <span aria-hidden="true">→</span>
          </button>
          <p v-if="currentStatus && !messages.length" class="inline-status">{{ currentStatus }}</p>
        </section>

        <section v-if="articleResult" class="card briefing-card">
          <div class="section-heading compact-heading">
            <div><p class="eyebrow">ARTICLE BRIEF</p><h2>{{ articleResult.title }}</h2></div>
            <span class="type-pill">{{ articleResult.analysis.article_type }}</span>
          </div>
          <p class="brief-summary">{{ articleResult.analysis.one_line_summary }}</p>
          <div class="issue-block">
            <span class="mini-label">산업 이슈</span>
            <p>{{ articleResult.analysis.key_issue }}</p>
          </div>
          <div class="read-actions">
            <label class="field-label" for="issue-group">같은 산업 이슈에 묶기 <span>선택</span></label>
            <select id="issue-group" v-model="selectedIssueId" class="text-input" :disabled="busy">
              <option value="">자동으로 이슈 연결</option>
              <option v-for="issue in industryIssues" :key="issue.issue_id" :value="issue.issue_id">
                {{ issue.title }} · {{ issue.article_count }}건
              </option>
            </select>
            <button class="button button-secondary button-wide" :disabled="busy || !sessionReady" @click="markArticleRead">
              읽은 기사로 저장 <span aria-hidden="true">✓</span>
            </button>
            <p v-if="readMessage" class="save-success">{{ readMessage }}</p>
          </div>
          <div class="term-section">
            <div class="term-section-heading"><span class="mini-label">읽기 전 핵심 용어</span><span>{{ terms.length }}개</span></div>
            <div class="term-list">
              <button
                v-for="term in terms"
                :key="term.term"
                class="term-chip"
                :class="{ 'term-chip-active': selectedTerm === term.term }"
                @click="selectedTerm = term.term"
              >{{ term.term }}</button>
            </div>
            <div v-if="currentTerm" class="selected-term-card">
              <div class="selected-term-top"><strong>{{ currentTerm.term }}</strong><span>{{ currentTerm.category }}</span></div>
              <p>{{ currentTerm.simple_definition }}</p>
              <small>이 기사에서는 · {{ currentTerm.article_context }}</small>
            </div>
          </div>
          <details class="article-source">
            <summary>기사 원문 보기</summary>
            <pre>{{ articleResult.article }}</pre>
          </details>
        </section>
      </div>

      <div class="column-stack">
        <section class="card chat-card">
          <div class="section-heading">
            <div><p class="eyebrow">02 · AI TUTOR</p><h2>자유롭게 질문하기</h2></div>
            <button class="icon-button" title="새 학습 세션" :disabled="busy || !sessionReady" @click="startNewSession">＋</button>
          </div>
          <p class="card-intro">기사 내용과 {{ currentTerm ? '선택한 용어' : '제약·바이오 개념' }}를 바탕으로 답변합니다.</p>
          <div ref="chatPanel" class="chat-panel" aria-live="polite">
            <div v-if="!messages.length" class="empty-chat">
              <div class="empty-icon">✳</div>
              <strong>어떤 내용이 궁금한가요?</strong>
              <p>기사의 주장과 확인된 근거를 구분해 설명합니다.</p>
              <div class="starter-questions">
                <button @click="question = '기사에서 실제로 확인된 결과와 아직 모르는 내용을 구분해줘.'">확인된 근거와 미확인 내용</button>
                <button @click="question = '이 개념의 핵심 작동 원리를 쉬운 말로 설명해줘.'">핵심 원리 쉽게 보기</button>
              </div>
            </div>
            <template v-for="(message, index) in messages" :key="index">
              <div v-if="message.role === 'user'" class="user-message">{{ message.content }}</div>
              <article v-else class="assistant-message">
                <div class="assistant-avatar">P</div>
                <div class="assistant-body">
                  <div class="message-meta">
                    <strong>PharmaMate</strong>
                    <span v-if="message.validationStatus" class="validation-pill" :class="message.validationStatus === 'pass' ? 'validation-ok' : 'validation-caution'">
                      {{ message.validationStatus === 'pass' ? '근거 확인' : '근거 부족' }}<template v-if="message.validationRetries"> · 수정 {{ message.validationRetries }}회</template>
                    </span>
                  </div>
                  <p class="answer-text">{{ message.content }}</p>
                  <div v-if="message.sources?.length" class="source-list">
                    <span class="mini-label">참고 자료</span>
                    <a v-for="(source, sourceIndex) in message.sources" :key="sourceIndex"
                       :href="source.url?.startsWith('http') ? source.url : undefined"
                       :target="source.url?.startsWith('http') ? '_blank' : undefined"
                       :rel="source.url?.startsWith('http') ? 'noreferrer' : undefined">
                      {{ source.title || source.record_id || '학습 기록' }}<small v-if="source.record_id"> · {{ source.record_id }}</small>
                    </a>
                  </div>
                  <div v-if="message.recommendations?.length" class="recommendations">
                    <div class="recommendation-heading"><span>다음 학습 방향</span><small>원하는 질문을 눌러 이어가세요</small></div>
                    <button v-for="item in message.recommendations" :key="item.category" class="recommendation-card" @click="useRecommendation(item)">
                      <span class="recommendation-category">{{ item.category }}</span>
                      <span class="recommendation-goal">{{ item.learning_goal }}</span>
                      <strong>{{ item.question }} <i>↗</i></strong>
                    </button>
                  </div>
                </div>
              </article>
            </template>
            <div v-if="busy" class="live-status"><span class="pulse-dot"></span>{{ currentStatus || '응답을 준비합니다.' }}</div>
          </div>
          <form class="composer" @submit.prevent="sendQuestion">
            <textarea id="question-input" v-model="question" rows="2" :disabled="busy || !sessionReady" placeholder="궁금한 점을 입력하세요…"></textarea>
            <div class="composer-footer">
              <span>{{ selectedTerm ? `선택 용어 · ${selectedTerm}` : '기사와 일반 개념을 모두 질문할 수 있어요' }}</span>
              <div>
                <button v-if="busy" class="button button-quiet" type="button" @click="cancelResponse">중단</button>
                <button class="send-button" type="submit" :disabled="busy || !sessionReady || !question.trim()" aria-label="질문 보내기">↑</button>
              </div>
            </div>
          </form>
        </section>

        <section v-if="articleResult && currentTerm" class="card save-card">
          <div class="section-heading compact-heading">
            <div><p class="eyebrow">03 · YOUR MEMORY</p><h2>학습 기록 저장</h2></div>
            <span class="save-term-label">{{ currentTerm.term }}</span>
          </div>
          <label class="field-label" for="study-note">내 메모 <span>선택</span></label>
          <textarea id="study-note" v-model="studyNote" class="text-input note-input" rows="3" placeholder="대화를 정리해 나만의 메모를 남기세요."></textarea>
          <button class="button button-secondary button-wide" :disabled="!canSave || busy" @click="saveStudyRecord">
            학습 용어와 관련 대화 저장 <span aria-hidden="true">↓</span>
          </button>
          <p v-if="saveMessage" class="save-success">{{ saveMessage }}</p>
          <p class="privacy-note">선택 용어와 관련 있다고 판단된 대화만 저장합니다.</p>
        </section>

        <section class="card records-card">
          <div class="section-heading compact-heading">
            <div><p class="eyebrow">STUDY MEMORY</p><h2>내 학습 기록</h2></div>
            <button class="text-button" @click="refreshRecords">새로고침</button>
          </div>
          <div v-if="studyRecords.length" class="record-list">
            <div v-for="record in studyRecords.slice(0, 5)" :key="record.term_key" class="record-item">
              <span class="record-dot"></span>
              <div><strong>{{ record.term_name }}</strong><p>{{ record.note || record.simple_definition }}</p></div>
              <span class="review-count">Q&A {{ record.qa_count }}</span>
            </div>
          </div>
          <p v-else class="records-empty">저장된 용어가 없습니다. 기사를 분석하고 학습 기록을 저장해 보세요.</p>
          <p class="privacy-note">기록은 로컬 SQLite에 저장됩니다.</p>
        </section>

        <section class="card issues-card">
          <div class="section-heading compact-heading">
            <div><p class="eyebrow">READING HISTORY</p><h2>읽은 기사와 산업 이슈</h2></div>
            <button class="text-button" @click="refreshReadingLists">새로고침</button>
          </div>
          <div v-if="industryIssues.length" class="issue-list">
            <article v-for="issue in industryIssues.slice(0, 5)" :key="issue.issue_id" class="saved-issue">
              <div class="saved-issue-heading"><strong>{{ issue.title }}</strong><span>{{ issue.article_count }}건</span></div>
              <a v-for="article in issue.articles.slice(0, 3)" :key="article.article_id"
                 :href="article.source_url?.startsWith('http') ? article.source_url : undefined"
                 :target="article.source_url?.startsWith('http') ? '_blank' : undefined"
                 :rel="article.source_url?.startsWith('http') ? 'noreferrer' : undefined">
                {{ article.title }}
              </a>
            </article>
          </div>
          <p v-else-if="!readArticles.length" class="records-empty">읽은 기사를 저장하면 같은 산업 이슈별로 모아 보여드립니다.</p>
          <div v-if="readArticles.length" class="issue-list recent-articles">
            <span class="mini-label">최근 저장한 기사</span>
            <article v-for="article in readArticles.slice(0, 5)" :key="article.article_id" class="saved-issue">
              <a :href="article.source_url?.startsWith('http') ? article.source_url : undefined"
                 :target="article.source_url?.startsWith('http') ? '_blank' : undefined"
                 :rel="article.source_url?.startsWith('http') ? 'noreferrer' : undefined">{{ article.title }}</a>
              <span v-if="article.issue_title" class="saved-issue-label">{{ article.issue_title }}</span>
            </article>
          </div>
          <p class="privacy-note">기사는 현재 세션 안에서만 보입니다.</p>
        </section>
      </div>
    </section>

    <footer class="page-footer"><span>PharmaMate 3.0</span><span>Article learning · Evidence-aware answers · Personal memory</span></footer>
  </main>
</template>
