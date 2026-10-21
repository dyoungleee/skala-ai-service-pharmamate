<script setup>
import { computed, nextTick, ref, watch } from 'vue'

const url = ref('')
const manualTitle = ref('')
const pastedText = ref('')
const articleResult = ref(null)
const selectedTerm = ref('')
const tutorTerm = ref('')
const question = ref('')
const messages = ref([])
const chatThreads = ref({})
const restoredThreadTerms = ref([])
const activeChatThreadKey = ref('')
const studyNote = ref('')
const memoDraftReady = ref(false)
const studyRecords = ref([])
const selectedRecordKey = ref('')
const readArticles = ref([])
const industryIssues = ref([])
const selectedIssueId = ref('')
const readMessage = ref('')
const activeStep = ref('article')
const sessionChoices = ref([])
const sessionId = ref('')
const sessionToken = ref('')
const sessionReady = ref(false)
const busy = ref(false)
const currentStatus = ref('')
const errorMessage = ref('')
const saveMessage = ref('')
const chatPanel = ref(null)
const articleTextContainer = ref(null)
const articleTermList = ref(null)
const termListScrollTail = ref(0)
const selectedArticleText = ref('')
const articleTermMessage = ref('')
const articleTermBusy = ref(false)
const articleTermClassifying = ref(false)
const articleWorkspace = ref(null)
let activeController = null
const SESSION_STORAGE_KEY = 'pharmamate.sessions.v1'
const STREAM_IDLE_TIMEOUT_MS = Number(import.meta.env.VITE_STREAM_IDLE_TIMEOUT_MS) || 120_000

function renderAnswerText(value) {
  const escaped = String(value ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[character])
  return escaped.replace(/(?:\\?\*\\?\*)([^\n]+?)(?:\\?\*\\?\*)/g, (_match, text) => (
    `<strong>${text.trim()}</strong>`
  ))
}

const steps = [
  { id: 'article', label: '기사 읽기', hint: '원문과 브리핑' },
  { id: 'tutor', label: 'AI Tutor', hint: '질문하고 학습하기' },
  { id: 'records', label: '내 학습 기록', hint: '저장 내용 다시 보기' },
]
const activeStepIndex = computed(() => steps.findIndex((step) => step.id === activeStep.value))
const terms = computed(() => articleResult.value?.analysis?.key_terms ?? [])
const currentTerm = computed(() => terms.value.find((item) => item.term === selectedTerm.value) ?? null)
const tutorTerms = computed(() => {
  const candidates = articleResult.value
    ? terms.value
    : [
        ...studyRecords.value.map((record) => ({ ...record, term: record.term_name })),
        ...restoredThreadTerms.value,
      ]
  const unique = new Map()
  for (const item of candidates) {
    const name = String(item.term || item.term_name || '').trim()
    const key = termStorageKey(name)
    if (name && key && !unique.has(key)) unique.set(key, { ...item, term: name })
  }
  return [...unique.values()]
})
const selectedTutorTerm = computed(() => tutorTerms.value.find(
  (item) => termStorageKey(item.term) === termStorageKey(tutorTerm.value),
) ?? null)
const selectedTutorQAs = computed(() => {
  if (!selectedTutorTerm.value) return []
  const selectedKey = termStorageKey(selectedTutorTerm.value.term)
  const conversations = []
  for (let index = 0; index < messages.value.length - 1; index += 1) {
    const questionMessage = messages.value[index]
    const answerMessage = messages.value[index + 1]
    if (questionMessage.role !== 'user' || answerMessage.role !== 'assistant' || !answerMessage.content) continue
    const answerTermKey = termStorageKey(answerMessage.selectedTerm || selectedTutorTerm.value.term)
    if (answerTermKey !== selectedKey) continue
    if (!answerMessage.relatedToSelected && !questionMentionsTerm(questionMessage.content, selectedTutorTerm.value)) continue
    conversations.push({ question: questionMessage.content, answer: answerMessage.content })
  }
  return conversations
})
const easyCategoryDescriptions = {
  Other: '기사에서 직접 선택한 용어예요. AI Tutor에서 뜻과 중요성을 확인해 보세요.',
  Modality: '치료 효과를 내기 위해 사용하는 치료 방식이에요.',
  Drug: '질병을 치료하거나 조절하기 위해 개발하는 약이에요.',
  Target: '약이 찾아가거나 작용하도록 정해둔 목표물이에요.',
  Biomarker: '몸의 상태나 치료 반응을 알려주는 측정 신호예요.',
  Disease: '치료와 연구의 대상이 되는 질환이에요.',
  'Clinical Trial': '약을 사람에게 사용해 안전성과 효과를 단계적으로 확인하는 과정이에요.',
  'Clinical Metric': '임상시험의 결과를 판단할 때 살펴보는 측정 기준이에요.',
  Regulatory: '의약품 개발과 허가에 필요한 공식 기준과 절차예요.',
  Business: '제약 기업의 계약, 투자, 사업 전략과 관련된 내용이에요.',
  Manufacturing: '의약품을 일정한 품질로 만들어 공급하는 과정이에요.',
  Platform: '여러 약이나 연구에 반복해서 활용하는 기반 기술이에요.',
  Diagnostic: '질환이나 치료 반응을 확인하는 검사 방법이에요.',
  Mechanism: '치료가 몸 안에서 효과를 내는 원인과 과정이에요.',
  Technology: '의약품 연구·개발·생산에 활용하는 기술이에요.',
}
const selectedTermGuide = computed(() => {
  const term = selectedTutorTerm.value
  if (!term) return []
  const definition = String(term.simple_definition || '용어의 기본 정의가 아직 준비되지 않았습니다.')
  return [
    { label: '한 줄 정의', content: definition },
    { label: '쉽게 말하면', content: easyCategoryDescriptions[term.category] || `핵심은 ${definition}` },
    { label: '이 기사에서는', content: term.article_context || '연결된 기사 설명이 없습니다.' },
    { label: '지금 기억할 한 가지', content: term.reason || `이 용어의 기본 정의를 기억하세요: ${definition}` },
  ]
})
const sortedStudyRecords = computed(() => [...studyRecords.value].sort((left, right) => {
  const leftTime = Date.parse(left.updated_at || '') || 0
  const rightTime = Date.parse(right.updated_at || '') || 0
  return rightTime - leftTime
}))
const studyRecordGroups = computed(() => {
  const groups = new Map()
  for (const record of sortedStudyRecords.value) {
    const category = String(record.category || 'Other')
    if (!groups.has(category)) groups.set(category, [])
    groups.get(category).push(record)
  }
  return [...groups.entries()]
    .map(([category, records]) => ({ category, records }))
    .sort((left, right) => (Date.parse(right.records[0]?.updated_at || '') || 0)
      - (Date.parse(left.records[0]?.updated_at || '') || 0))
})
const selectedStudyRecord = computed(() => studyRecords.value.find(
  (record) => record.term_key === selectedRecordKey.value,
) ?? null)
const recordCategoryLabels = {
  Modality: '치료 방식', Drug: '의약품 후보', Target: '표적', Biomarker: '바이오마커',
  Disease: '질환', 'Clinical Trial': '임상시험', 'Clinical Metric': '임상 지표',
  Regulatory: '규제·허가', Business: '사업·제휴', Manufacturing: '생산',
  Platform: '플랫폼', Diagnostic: '진단', Mechanism: '작용 기전', Technology: '기술',
  Other: '기타',
}
const manualTermFallbackRules = [
  { category: 'Clinical Metric', pattern: /(?<![A-Za-z])(?:PFS|OS|ORR|EFS|DFS|DOR|mOS|HR|CI)(?![A-Za-z])|평가변수|반응률|생존기간|위험비|유효성 지표|객관적 반응/i },
  { category: 'Clinical Trial', pattern: /임상\s*(?:시험\s*)?[1-4]\s*상?|(?:^|\s)[1-4]\s*상(?:$|\s)|phase\s*[1-4]|임상시험|무작위\s*대조|코호트|용량.?증량|대조군/i },
  { category: 'Regulatory', pattern: /(?<![A-Za-z])(?:IND|NDA|BLA)(?![A-Za-z])|품목.?허가|시판.?허가|허가.?신청|허가.?심사|규제.?경로|신속.?심사|승인 절차/i },
  { category: 'Business', pattern: /기술.?이전|라이선스|계약금|마일스톤|로열티|판권|제휴|인수.?합병|상업화|사업.?개발|공동.?개발/i },
  { category: 'Manufacturing', pattern: /(?<![A-Za-z])(?:GMP|CMO|CDMO)(?![A-Za-z])|생산|제조|배양.?공정|품질.?관리|스케일.?업/i },
  { category: 'Diagnostic', pattern: /동반.?진단|진단.?키트|진단법|진단.?검사|검사법|진단.?기술/i },
  { category: 'Biomarker', pattern: /바이오.?마커|biomarker|발현.?량|돌연변이|유전자.?변이|PD-L1|HER2|MSI-H|TMB/i },
  { category: 'Mechanism', pattern: /작용.?기전|기전|분해.?유도|억제.?작용|활성화.?경로|신호.?전달|분해.?경로/i },
  { category: 'Modality', pattern: /CAR.?T|항체.?약물.?접합체|ADC|mRNA|siRNA|ASO|세포.?치료|유전자.?치료|방사성.?의약품|단일.?클론.?항체/i },
  { category: 'Platform', pattern: /플랫폼|platform|발굴.?플랫폼|개발.?플랫폼/i },
  { category: 'Target', pattern: /표적|타깃|target|수용체|항원|단백질|유전자|EGFR|PD-1|KRAS|BRAF/i },
  { category: 'Disease', pattern: /(?:폐|유방|위|간|췌장|대장|직장|전립선|난소|혈액|식도|두경부|소세포|비소세포)암|암종|질환|증후군|폐섬유증|신경퇴행|자가면역|백혈병|림프종|흑색종|당뇨병|비만/i },
  { category: 'Drug', pattern: /후보물질|신약|치료제|의약품|약물|약제|억제제|저해제|바이오시밀러|유효성분|화합물|성분|antagonist|inhibitor|agonist/i },
  { category: 'Technology', pattern: /기술|알고리즘|시퀀싱|인공지능|CRISPR|나노입자|전달체|유전자.?편집/i },
]
const manualTermFallbackDefinitions = {
  Modality: '치료에 사용하는 방식이나 형태를 설명하는 용어입니다.',
  Drug: '특정 의약품이나 개발 중인 약물 후보를 가리키는 용어입니다.',
  Target: '약물이나 치료 기술이 작용하도록 겨냥하는 분자입니다.',
  Biomarker: '질병 상태나 치료 반응을 측정·예측하는 생체 지표입니다.',
  Disease: '기사에서 다루는 질환 또는 질환의 하위 유형입니다.',
  'Clinical Trial': '임상시험의 단계, 설계, 대상자 또는 진행 방식을 설명합니다.',
  'Clinical Metric': '임상시험에서 효과나 안전성 결과를 측정하는 지표입니다.',
  Regulatory: '의약품의 허가 신청, 심사, 승인과 관련된 절차나 기준입니다.',
  Business: '의약품 개발·판매와 관련된 계약이나 사업 거래를 뜻합니다.',
  Manufacturing: '의약품의 생산, 제조 공정 또는 품질 관리와 관련된 용어입니다.',
  Platform: '여러 후보나 연구에 반복해서 활용하는 기술 기반 체계입니다.',
  Diagnostic: '질환이나 생체 지표를 확인하는 검사 또는 진단 방법입니다.',
  Mechanism: '약물이나 기술이 생물학적 효과를 내는 작동 원리입니다.',
  Technology: '치료 방식·작용 기전·플랫폼 외의 구체적인 기술 방법입니다.',
  Other: '기사 문맥만으로 전문 범주를 확정하기 어려워 추가 확인이 필요한 용어입니다.',
}
const canSave = computed(() => Boolean(selectedTutorTerm.value && memoDraftReady.value && studyNote.value.trim()))
const starterQuestions = [
  { label: '쉽게 비유해줘', question: '이 용어를 일상적인 예로 쉽게 비유해줘.' },
  { label: '기사에서 왜 중요해?', question: '이 용어가 기사에서 왜 중요하게 다뤄졌는지 설명해줘.' },
  { label: '비슷한 개념과 비교해줘', question: '이 용어와 비슷한 개념의 공통점과 차이를 비교해줘.' },
]
const articleContextQuestions = computed(() => {
  const article = articleResult.value
  if (!article) return starterQuestions

  const savedQuestions = article.analysis?.article_questions
  if (Array.isArray(savedQuestions) && savedQuestions.length === 2
    && savedQuestions.every((item) => typeof item === 'string' && item.trim())) {
    return savedQuestions.map((item) => ({ label: item, question: item }))
  }

  // 세션에 저장된 구버전 분석 결과에 추천 질문이 없을 때도 기사 맥락 질문 두 개를 제공합니다.
  const normalizeAnchor = (value) => String(value || '').normalize('NFKC').toLocaleLowerCase()
    .replaceAll(' ', '').replaceAll('_', '').replaceAll('-', '')
  const source = normalizeAnchor(article.body || '')
  const candidates = [
    ...(article.analysis?.key_entities || []),
    ...(article.analysis?.key_terms || []).flatMap((item) => [item.term, ...(item.aliases || [])]),
  ]
  const anchors = [...new Map(candidates
    .map((item) => String(item || '').trim())
    .filter((item) => item && source.includes(normalizeAnchor(item)))
    .map((item) => [normalizeAnchor(item), item]))
    .values()]
  const [firstAnchor, secondAnchor] = anchors
  const questions = firstAnchor && secondAnchor
    ? [
        `기사에서 다룬 ‘${firstAnchor}’의 의미와 중요한 이유는 무엇인가요?`,
        `기사의 핵심 이슈와 ‘${secondAnchor}’의 연결은 무엇인가요?`,
      ]
    : firstAnchor
      ? [
          `기사에서 다룬 ‘${firstAnchor}’의 의미와 중요한 이유는 무엇인가요?`,
          `기사의 핵심 이슈와 ‘${firstAnchor}’의 연결은 무엇인가요?`,
        ]
      : [
          '기사에서 다룬 핵심 변화의 배경은 무엇인가요?',
          '이 기사의 핵심 이슈가 업계에 주는 의미는 무엇인가요?',
        ]
  return questions.map((item) => ({ label: item, question: item }))
})
const visibleStarterQuestions = computed(() => (
  articleResult.value && !tutorTerm.value ? articleContextQuestions.value : starterQuestions
))
const articleSegments = computed(() => {
  const article = articleResult.value?.body ?? articleResult.value?.article ?? ''
  if (!article) return []

  const aliases = new Map()
  for (const term of terms.value) {
    const title = String(term.term || '')
    const values = [title, ...(term.aliases ?? [])]
    const acronym = title.match(/\(([A-Za-z][A-Za-z0-9+-]{1,15})\)/)?.[1]
    if (acronym) values.push(acronym)
    if (title.includes('(')) values.push(title.split('(')[0].trim())
    for (const value of values) {
      const alias = String(value || '').trim()
      if (alias.length < 2 || alias.length > 70) continue
      const key = alias.normalize('NFKC').toLocaleLowerCase()
      if (!aliases.has(key)) aliases.set(key, { alias, term })
    }
  }

  const matches = [...aliases.values()].sort((left, right) => right.alias.length - left.alias.length)
  const termMatches = []
  if (matches.length) {
    const pattern = new RegExp(matches.map(({ alias }) => {
      const escaped = alias.replace(/[.*+?^$()|[\]\\]/g, '\\$&')
      return /^[a-z0-9+-]+$/i.test(alias)
        ? '(?<![A-Za-z0-9])' + escaped + '(?![A-Za-z0-9])'
        : escaped
    }).join('|'), 'gi')
    const termLookup = new Map(matches.map(({ alias, term }) => [
      alias.normalize('NFKC').toLocaleLowerCase(), term,
    ]))
    const highlightedTermKeys = new Set()
    for (const match of article.matchAll(pattern)) {
      const term = termLookup.get(match[0].normalize('NFKC').toLocaleLowerCase())
      const termKey = termStorageKey(term?.term)
      const firstOccurrence = Boolean(termKey) && !highlightedTermKeys.has(termKey)
      if (firstOccurrence) highlightedTermKeys.add(termKey)
      termMatches.push({
        start: match.index,
        end: match.index + match[0].length,
        status: firstOccurrence ? (isKnownTerm(term) ? 'known' : 'new') : '',
        title: firstOccurrence ? (term?.simple_definition || term?.term || '') : '',
        term: firstOccurrence ? (term?.term || '') : '',
      })
    }
  }

  const boundaries = new Set([0, article.length])
  for (const match of termMatches) {
    boundaries.add(match.start)
    boundaries.add(match.end)
  }
  const positions = [...boundaries].sort((left, right) => left - right)
  const segments = []
  for (let index = 0; index < positions.length - 1; index += 1) {
    const start = positions[index]
    const end = positions[index + 1]
    if (start === end) continue
    const termMatch = termMatches.find((match) => match.start <= start && match.end >= end)
    segments.push({
      text: article.slice(start, end),
      status: termMatch?.status || '',
      title: termMatch?.title || '',
      term: termMatch?.term || '',
    })
  }
  return segments
})

watch(messages, async () => {
  chatThreads.value = {
    ...chatThreads.value,
    [activeChatThreadKey.value]: messages.value,
  }
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

function normalizeArticleResponse(article) {
  if (!article || typeof article !== 'object') return article
  const body = article.body ?? article.article ?? ''
  return { ...article, body: typeof body === 'string' ? body : '' }
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
  const term = String(value || '').normalize('NFKC').trim()
  const acronyms = [...term.matchAll(/\(([A-Za-z][A-Za-z0-9+-]{1,15})\)/g)]
  if (acronyms.length) return acronyms.at(-1)[1].toLowerCase()
  if (/^[A-Za-z][A-Za-z0-9+-]{1,15}$/.test(term)) return term.toLowerCase()
  return term.replace(/[\s_-]+/g, '').toLowerCase()
}

function termAliases(term) {
  const title = String(term?.term || term?.term_name || '')
  const acronym = title.match(/\(([A-Za-z][A-Za-z0-9+-]{1,15})\)/)?.[1]
  return [...new Set([
    title,
    ...(term?.aliases ?? []),
    ...(acronym ? [acronym] : []),
    ...(title.includes('(') ? [title.split('(')[0].trim()] : []),
  ].map((value) => String(value || '').trim()).filter(Boolean))]
}

function questionMentionsTerm(question, term) {
  const normalize = (value) => String(value || '').normalize('NFKC').toLocaleLowerCase().replace(/[^\p{L}\p{N}]/gu, '')
  const normalizedQuestion = normalize(question)
  return termAliases(term).some((alias) => {
    const normalizedAlias = normalize(alias)
    return normalizedAlias.length >= 3 && normalizedQuestion.includes(normalizedAlias)
  })
}

function isKnownTerm(term) {
  if (!term) return false
  const currentKeys = new Set(termAliases(term).map(termStorageKey).filter(Boolean))
  return studyRecords.value.some((record) => [
    record.term_key,
    record.term_name,
    ...(record.aliases ?? []),
  ].some((value) => currentKeys.has(termStorageKey(value))))
}

function switchTutorTerm(termName, force = false) {
  if (busy.value && !force) return
  chatThreads.value = {
    ...chatThreads.value,
    [activeChatThreadKey.value]: messages.value,
  }
  const nextName = String(termName || '')
  const nextKey = termStorageKey(nextName)
  activeChatThreadKey.value = nextKey
  tutorTerm.value = nextName
  messages.value = [...(chatThreads.value[nextKey] || [])]
  studyNote.value = ''
  memoDraftReady.value = false
  saveMessage.value = ''
}

function selectStarterQuestion(prompt) {
  question.value = prompt
  document.querySelector('#question-input')?.focus()
}

function captureArticleTermSelection() {
  const selection = window.getSelection()
  const range = selection?.rangeCount ? selection.getRangeAt(0) : null
  const container = articleTextContainer.value
  const text = String(selection?.toString() || '').replace(/\s+/g, ' ').trim()
  if (!container || !range || !text || !container.contains(range.commonAncestorContainer)) {
    selectedArticleText.value = ''
    return
  }
  selectedArticleText.value = text
  articleTermMessage.value = text.length < 2 || text.length > 70
    ? '용어는 2~70자로 선택해 주세요.'
    : ''
}

function getArticleTermContext(termName) {
  const article = String(articleResult.value?.body || '')
  const paragraph = article.split(/\n+/).map((line) => line.trim()).find((line) => line.includes(termName))
  if (paragraph) {
    const termIndex = paragraph.toLocaleLowerCase().indexOf(termName.toLocaleLowerCase())
    const start = Math.max(0, termIndex - 300)
    return paragraph.slice(start, Math.min(paragraph.length, start + 700))
  }
  const index = article.toLocaleLowerCase().indexOf(termName.toLocaleLowerCase())
  if (index < 0) return `기사 원문에서 사용자가 직접 선택한 용어입니다: ${termName}`
  return article.slice(Math.max(0, index - 140), Math.min(article.length, index + termName.length + 240))
    .replace(/\s+/g, ' ').trim().slice(0, 700)
}

function fallbackManualArticleTerm(termName, articleContext) {
  const matchedRule = manualTermFallbackRules.find((rule) => rule.pattern.test(termName))
  const category = matchedRule?.category || 'Other'
  const evidence = matchedRule?.pattern.exec(termName)?.[0]
  return {
    term: termName,
    category,
    reason: evidence
      ? `선택한 용어의 “${evidence}” 표현을 기준으로 ${category}로 분류했습니다.`
      : '용어는 추가하고, 기사 문맥만으로 범주를 확정하기 어려워 기타로 분류했습니다.',
    simple_definition: manualTermFallbackDefinitions[category],
    article_context: articleContext,
    aliases: [],
  }
}

async function updateArticleTerms(nextTerms, {
  selectedName = selectedTerm.value,
  tutorName = tutorTerm.value,
  showSaveError = true,
} = {}) {
  if (!articleResult.value || articleTermBusy.value) return false
  const updatedArticle = {
    ...articleResult.value,
    analysis: { ...articleResult.value.analysis, key_terms: nextTerms },
  }
  const termKey = (name) => termStorageKey(name)
  const nextSelected = nextTerms.find((term) => termKey(term.term) === termKey(selectedName)) || nextTerms[0]
  const nextSelectedName = nextSelected?.term || ''
  const nextTutor = nextTerms.find((term) => termKey(term.term) === termKey(tutorName))
    || nextTerms.find((term) => termKey(term.term) === termKey(nextSelectedName))
  articleTermBusy.value = true
  try {
    await sessionRequest(`/api/sessions/${sessionId.value}/article`, {
      method: 'PUT',
      body: JSON.stringify({ article: updatedArticle, selected_term_key: nextSelectedName }),
    })
    articleResult.value = updatedArticle
    selectedTerm.value = nextSelectedName
    const nextTutorName = nextTutor?.term || ''
    if (termKey(nextTutorName) !== termKey(tutorTerm.value)) switchTutorTerm(nextTutorName, true)
    return true
  } catch (error) {
    if (showSaveError) errorMessage.value = `용어 목록을 저장하지 못했습니다. ${error.message}`
    return false
  } finally {
    articleTermBusy.value = false
  }
}

async function addSelectedArticleTerm() {
  const termName = selectedArticleText.value.trim()
  if (!termName || termName.length < 2 || termName.length > 70 || articleTermBusy.value || articleTermClassifying.value || busy.value) return
  const selectedKey = termStorageKey(termName)
  const alreadyAdded = terms.value.some((term) => termAliases(term)
    .some((alias) => termStorageKey(alias) === selectedKey))
  if (alreadyAdded) {
    articleTermMessage.value = '이미 용어 목록에 있는 표현입니다.'
    return
  }
  if (terms.value.length >= 20) {
    articleTermMessage.value = '용어는 기사당 최대 20개까지 추가할 수 있습니다.'
    return
  }
  errorMessage.value = ''
  const articleContext = getArticleTermContext(termName)
  articleTermClassifying.value = true
  articleTermMessage.value = '선택한 용어의 분류와 뜻을 확인하고 있습니다.'
  let newTerm
  let classificationMethod = 'AI 문맥 분류'
  try {
    newTerm = await requestJson('/api/articles/classify-term', {
      method: 'POST',
      body: JSON.stringify({
        term: termName,
        article_context: articleContext,
        article_type: articleResult.value?.analysis?.article_type || '',
      }),
    })
  } catch (error) {
    newTerm = fallbackManualArticleTerm(termName, articleContext)
    classificationMethod = '기준 기반 보조 분류'
  }

  try {
    const nextTerms = [...terms.value, newTerm]
    articleResult.value = {
      ...articleResult.value,
      analysis: { ...articleResult.value.analysis, key_terms: nextTerms },
    }
    selectedTerm.value = termName
    switchTutorTerm(termName, true)
    const saved = await updateArticleTerms(nextTerms, {
      selectedName: termName,
      tutorName: termName,
      showSaveError: false,
    })
    selectedArticleText.value = ''
    window.getSelection()?.removeAllRanges()
    const categoryLabel = recordCategoryLabels[newTerm.category] || newTerm.category || '기타'
  } finally {
    articleTermClassifying.value = false
  }
}

async function removeArticleTerm(termName) {
  if (articleTermBusy.value || articleTermClassifying.value || busy.value) return
  const removedKey = termStorageKey(termName)
  const nextTerms = terms.value.filter((term) => termStorageKey(term.term) !== removedKey)
  if (nextTerms.length === terms.value.length) return
  const fallbackName = nextTerms[0]?.term || ''
  const nextSelectedName = termStorageKey(selectedTerm.value) === removedKey ? fallbackName : selectedTerm.value
  const nextTutorName = termStorageKey(tutorTerm.value) === removedKey ? fallbackName : tutorTerm.value
  const saved = await updateArticleTerms(nextTerms, {
    selectedName: nextSelectedName,
    tutorName: nextTutorName,
  })
  if (saved) {
    articleTermMessage.value = `“${termName}” 용어를 현재 기사에서 제외했습니다.`
    if (termStorageKey(selectedArticleText.value) === removedKey) selectedArticleText.value = ''
  }
}

async function focusArticleTermSummary(termName) {
  const term = terms.value.find((item) => termStorageKey(item.term) === termStorageKey(termName))
  if (!term) return
  selectedTerm.value = term.term
  termListScrollTail.value = 0
  await nextTick()
  const list = articleTermList.value
  const target = [...(list?.querySelectorAll('[data-term-key]') || [])]
    .find((element) => element.dataset.termKey === termStorageKey(term.term))
  if (!list || !target) return

  if (terms.value.length >= 3) {
    const targetTop = target.getBoundingClientRect().top - list.getBoundingClientRect().top + list.scrollTop
    const requiredTail = Math.max(0, Math.ceil(targetTop + list.clientHeight - list.scrollHeight))
    if (requiredTail) {
      termListScrollTail.value = requiredTail
      await nextTick()
    }
    list.scrollTo({ top: targetTop, behavior: 'smooth' })
    return
  }
  target.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function buildStudyNoteDraft() {
  const term = selectedTutorTerm.value
  if (!term) return
  const selectedKey = termStorageKey(term.term)
  const savedRecord = studyRecords.value.find((record) => (
    record.term_key === selectedKey
    || (record.aliases || []).some((alias) => termStorageKey(alias) === selectedKey)
  ))
  const existingNote = String(savedRecord?.note || '')
  const definition = String(term.simple_definition || '용어의 기본 정의를 확인해 보세요.').slice(0, 900)
  const articleContext = String(term.article_context || term.reason || '현재 기사와 직접 연결된 설명이 없습니다.').slice(0, 900)
  const remember = String(term.reason || definition).slice(0, 700)
  const headings = ['한 줄 개념', '헷갈렸던 부분 Q&A', '기사에서 중요한 이유', '기억할 점']
  const normalizeHeading = (line) => line.trim().replace(/^#{1,6}\s*/, '').replace(/\*\*/g, '').replace(/:$/, '').trim()
  const readSection = (note, heading) => {
    const lines = String(note || '').split('\n')
    const start = lines.findIndex((line) => normalizeHeading(line) === heading)
    if (start < 0) return ''
    const end = lines.findIndex((line, index) => index > start && headings.includes(normalizeHeading(line)))
    return lines.slice(start + 1, end < 0 ? lines.length : end).join('\n').trim()
  }
  const parseQAs = (section) => {
    const lines = String(section || '').split('\n')
    const pairs = []
    const plainLine = (line) => String(line).trim().replace(/^\*\*/, '').replace(/\*\*\s*$/, '').trim()
    for (let index = 0; index < lines.length; index += 1) {
      const questionMatch = plainLine(lines[index]).match(/^Q[.:：]\s*(.*)$/i)
      if (!questionMatch) continue
      const answerIndex = lines.findIndex((line, candidate) => candidate > index && /^\s*A[.:：]\s*/i.test(plainLine(line)))
      if (answerIndex < 0) continue
      const nextQuestionIndex = lines.findIndex((line, candidate) => candidate > answerIndex && /^Q[.:：]\s*/i.test(plainLine(line)))
      const answer = [plainLine(lines[answerIndex]).replace(/^A[.:：]\s*/i, ''), ...lines.slice(answerIndex + 1, nextQuestionIndex < 0 ? lines.length : nextQuestionIndex)].join('\n').trim()
      const asked = questionMatch[1].trim()
      if (asked && answer) pairs.push({ question: asked, answer })
    }
    return pairs
  }
  const existingQAs = parseQAs(readSection(existingNote, '헷갈렸던 부분 Q&A'))
  const mergedQAs = new Map()
  for (const item of [...existingQAs, ...selectedTutorQAs.value]) {
    const key = String(item.question || '').normalize('NFKC').replace(/\s+/g, ' ').trim().toLocaleLowerCase()
    if (key && item.answer) mergedQAs.set(key, item)
  }
  const qaSection = mergedQAs.size
    ? [...mergedQAs.values()].map(({ question: asked, answer }) => (
      `**Q: ${String(asked).slice(0, 200)}**  \nA: ${String(answer).slice(0, 500)}`
    )).join('\n\n')
    : '아직 이 용어에 연결된 질문과 답변이 없습니다.'
  const rememberText = readSection(existingNote, '기억할 점') || `${remember}\n${definition}`
  const rememberItems = [...new Set(rememberText.split('\n')
    .map((line) => line.replace(/^\s*[-*]\s*/, '').trim())
    .filter(Boolean))]
  const rememberSection = rememberItems.map((line) => `- ${line}`).join('\n')
  studyNote.value = [
    `# ${term.term} 학습 메모`,
    '', '## 한 줄 개념', readSection(existingNote, '한 줄 개념') || definition,
    '', '## 기사에서 중요한 이유', readSection(existingNote, '기사에서 중요한 이유') || articleContext,
    '', '## 기억할 점', rememberSection,
    '', '## 헷갈렸던 부분 Q&A', qaSection,
  ].join('\n').slice(0, 7900)
  memoDraftReady.value = true
  saveMessage.value = ''
}

function handleQuestionKeydown(event) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229) return
  event.preventDefault()
  sendQuestion()
}

function recordCategoryLabel(category) {
  return recordCategoryLabels[category] || category || '기타'
}

function formatRecordDate(value) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString('ko-KR', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

function escapeMemoHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[character])
}

function renderMemoInline(value) {
  return escapeMemoHtml(value).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
}

function renderStudyNote(record) {
  const note = String(record?.note || record?.simple_definition || '')
  const lines = note.split(/\r?\n/)
  const output = []
  let paragraph = []
  let listItems = []
  const flushParagraph = () => {
    if (!paragraph.length) return
    output.push(`<p>${paragraph.map(renderMemoInline).join('<br>')}</p>`)
    paragraph = []
  }
  const flushList = () => {
    if (!listItems.length) return
    output.push(`<ul class="record-note-bullets">${listItems.map((item) => `<li>${renderMemoInline(item)}</li>`).join('')}</ul>`)
    listItems = []
  }
  const flushText = () => {
    flushParagraph()
    flushList()
  }
  const sectionNames = ['한 줄 개념', '헷갈렸던 부분 Q&A', '기사에서 중요한 이유', '기억할 점']
  const sectionHeading = (value) => value.trim().replace(/^#{1,6}\s*/, '').replace(/^\*\*(.*?)\*\*$/, '$1').trim()
  const questionText = (value) => value.trim().replace(/^\*\*/, '').replace(/\*\*\s*$/, '').trim()
  const expectedTitle = `# ${record?.term_name || ''} 학습 메모`
  const hasTitle = lines[0]?.trim() === expectedTitle
  if (!hasTitle && record?.term_name) output.push(`<h3 class="record-note-title">${renderMemoInline(`${record.term_name} 학습 메모`)}</h3>`)

  for (let index = hasTitle ? 1 : 0; index < lines.length; index += 1) {
    const line = lines[index].trim()
    if (!line) {
      flushText()
      continue
    }
    const heading = sectionHeading(line)
    if (sectionNames.includes(heading)) {
      flushText()
      output.push(`<h4 class="record-note-section-title">${renderMemoInline(heading)}</h4>`)
      continue
    }
    const bulletMatch = line.match(/^[-*]\s+(.+)$/)
    if (bulletMatch) {
      flushParagraph()
      listItems.push(bulletMatch[1])
      continue
    }
    flushList()
    const questionMatch = questionText(line).match(/^Q[.:：]\s*(.*)$/i)
    if (questionMatch) {
      flushParagraph()
      let answerIndex = -1
      for (let cursor = index + 1; cursor < lines.length; cursor += 1) {
        const candidate = lines[cursor].trim()
        if (!candidate) continue
        if (sectionNames.includes(sectionHeading(candidate)) || /^Q[.:：]\s*/i.test(questionText(candidate))) break
        if (/^A[.:：]\s*/i.test(candidate)) {
          answerIndex = cursor
          break
        }
      }

      const answerLines = []
      let consumedUntil = index
      if (answerIndex >= 0) {
        for (let cursor = answerIndex; cursor < lines.length; cursor += 1) {
          const candidate = lines[cursor].trim()
          if (cursor > answerIndex && (sectionNames.includes(sectionHeading(candidate)) || /^Q[.:：]\s*/i.test(questionText(candidate)))) break
          answerLines.push(cursor === answerIndex ? candidate.replace(/^A[.:：]\s*/i, '') : candidate)
          consumedUntil = cursor
        }
        while (answerLines.length && !answerLines[answerLines.length - 1]) answerLines.pop()
        output.push(`<details class="record-note-qa-item"><summary><strong>Q: ${renderMemoInline(questionMatch[1])}</strong></summary><div class="record-note-qa-answer"><strong>A:</strong> ${answerLines.map(renderMemoInline).join('<br>')}</div></details>`)
      } else {
        output.push(`<details class="record-note-qa-item"><summary><strong>Q: ${renderMemoInline(questionMatch[1])}</strong></summary><div class="record-note-qa-answer">저장된 답변이 없습니다.</div></details>`)
      }
      index = consumedUntil
      continue
    }
    const answerMatch = line.match(/^A[.:：]\s*(.*)$/i)
    if (answerMatch) {
      flushParagraph()
      output.push(`<p class="record-note-answer"><strong>A:</strong> ${renderMemoInline(answerMatch[1])}</p>`)
      continue
    }
    paragraph.push(line)
  }
  flushText()
  return output.join('')
}

function selectStudyRecord(record) {
  selectedRecordKey.value = record.term_key
}

function goToStep(stepId) {
  if (!steps.some((step) => step.id === stepId)) return
  if (stepId === 'records') selectedRecordKey.value = ''
  activeStep.value = stepId
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function moveStep(offset) {
  const next = steps[activeStepIndex.value + offset]
  if (next) goToStep(next.id)
}

function isStepComplete(stepId) {
  if (stepId === 'article') return Boolean(articleResult.value)
  if (stepId === 'tutor') return messages.value.some((message) => message.role === 'assistant' && message.content)
  if (stepId === 'records') return studyRecords.value.length > 0 || readArticles.value.length > 0
  return false
}

function restoreSnapshot(snapshot) {
  articleResult.value = normalizeArticleResponse(snapshot.article)
  selectedArticleText.value = ''
  articleTermMessage.value = ''
  selectedRecordKey.value = ''
  const savedTerm = snapshot.turns.at(-1)?.term_name
  const selectedByKey = terms.value.find((term) => termStorageKey(term.term) === snapshot.selected_term_key)?.term
  selectedTerm.value = terms.value.some((term) => term.term === savedTerm)
    ? savedTerm
    : selectedByKey ?? terms.value[0]?.term ?? ''
  const groupedThreads = {}
  const threadTerms = new Map()
  for (const turn of snapshot.turns) {
    const threadKey = turn.term_key || termStorageKey(turn.term_name)
    groupedThreads[threadKey] ||= []
    groupedThreads[threadKey].push(
      { role: 'user', content: turn.question },
      {
        role: 'assistant', content: turn.answer, sources: turn.sources,
        recommendations: turn.recommendations, route: turn.route,
        relatedToSelected: turn.related_to_selected, selectedTerm: turn.term_name,
        validationStatus: turn.validation_status, validationRetries: turn.validation_retries,
      },
    )
    if (turn.term_name) threadTerms.set(threadKey, { term: turn.term_name })
  }
  chatThreads.value = groupedThreads
  restoredThreadTerms.value = [...threadTerms.values()]
  tutorTerm.value = savedTerm || selectedTerm.value
  activeChatThreadKey.value = termStorageKey(tutorTerm.value)
  messages.value = [...(groupedThreads[activeChatThreadKey.value] || [])]
  studyNote.value = ''
  memoDraftReady.value = false
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
  studyNote.value = selectedTutorTerm.value?.note || ''
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
    activeStep.value = 'article'
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
  selectedArticleText.value = ''
  articleTermMessage.value = ''
  selectedIssueId.value = ''
  const articleText = pastedText.value.trim()
  if (!url.value.trim() && !articleText) {
    errorMessage.value = '기사 URL 또는 본문을 입력해 주세요.'
    return
  }
  if (articleText && !manualTitle.value.trim()) {
    errorMessage.value = '직접 붙여넣은 기사의 제목을 입력해 주세요.'
    return
  }
  busy.value = true
  currentStatus.value = '기사를 분석합니다.'
  try {
    const analyzed = normalizeArticleResponse(await requestJson('/api/articles/analyze', {
      method: 'POST',
      body: JSON.stringify({
        url: articleText ? '' : url.value,
        pasted_text: articleText,
        title: articleText ? manualTitle.value.trim() : '',
      }),
    }))
    if (!analyzed?.body?.trim()) {
      throw new Error('기사 분석 응답에 원문 본문이 없습니다. URL을 확인하거나 본문을 직접 붙여넣어 주세요.')
    }
    const firstTerm = analyzed.analysis.key_terms[0]?.term ?? ''
    await sessionRequest(`/api/sessions/${sessionId.value}/article`, {
      method: 'PUT',
      body: JSON.stringify({ article: analyzed, selected_term_key: firstTerm }),
    })
    articleResult.value = analyzed
    selectedTerm.value = firstTerm
    switchTutorTerm(firstTerm, true)
    await nextTick()
    articleWorkspace.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
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
    assistantMessage.streamComplete = true
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
    let timeoutId
    const idleTimeout = new Promise((_, reject) => {
      timeoutId = setTimeout(() => reject(new Error(
        '스트리밍 연결이 일정 시간 동안 응답하지 않아 종료했습니다. 다시 시도해 주세요.',
      )), STREAM_IDLE_TIMEOUT_MS)
    })
    let chunk
    try {
      chunk = await Promise.race([reader.read(), idleTimeout])
    } finally {
      clearTimeout(timeoutId)
    }
    const { value, done } = chunk
    if (done) break
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
    dispatchBlocks()
  }
  buffer += decoder.decode()
  dispatchBlocks()
  if (!assistantMessage.streamComplete) {
    throw new Error('스트리밍 연결이 답변 완료 전에 종료됐습니다. 다시 시도해 주세요.')
  }
}

async function sendQuestion(questionOverride = '') {
  const asked = String(questionOverride || question.value).trim()
  if (!asked || busy.value || !sessionReady.value || !sessionId.value) return
  errorMessage.value = ''
  saveMessage.value = ''
  const selected = selectedTutorTerm.value
  studyNote.value = ''
  memoDraftReady.value = false
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
        term: selected ? `${selected.term}\n${selected.simple_definition || ''}\n${selected.article_context || ''}` : '',
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
      activeController?.abort()
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

async function saveStudyRecord() {
  if (!canSave.value || busy.value) return
  errorMessage.value = ''
  saveMessage.value = ''
  try {
    const result = await sessionRequest(`/api/sessions/${sessionId.value}/study-records`, {
      method: 'POST',
      body: JSON.stringify({
        term: {
          term: selectedTutorTerm.value.term,
          category: selectedTutorTerm.value.category || 'Mechanism',
          reason: selectedTutorTerm.value.reason || 'AI Tutor에서 질문하고 학습한 용어입니다.',
          simple_definition: selectedTutorTerm.value.simple_definition || '',
          article_context: selectedTutorTerm.value.article_context || '',
          aliases: selectedTutorTerm.value.aliases || [],
        },
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
    if (!studyRecords.value.some((record) => record.term_key === selectedRecordKey.value)) {
      selectedRecordKey.value = ''
    }
  } catch {
    studyRecords.value = []
    selectedRecordKey.value = ''
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
      <div class="hero-orbit" aria-hidden="true"><span>PM</span><b></b><i></i></div>
    </section>

    <div v-if="errorMessage" class="alert alert-error" role="alert">
      <span>{{ errorMessage }}</span><button @click="errorMessage = ''" aria-label="닫기">×</button>
    </div>

    <nav class="step-tabs" aria-label="학습 단계">
      <button v-for="(step, index) in steps" :key="step.id" class="step-tab"
        :class="{ 'step-tab-active': activeStep === step.id, 'step-tab-done': isStepComplete(step.id) }"
        :aria-current="activeStep === step.id ? 'step' : undefined"
        @click="goToStep(step.id)">
        <span class="step-tab-number">{{ index + 1 }}</span>
        <span class="step-tab-copy"><strong>{{ step.label }}</strong><small>{{ step.hint }}</small></span>
        <span v-if="index < steps.length - 1" class="step-tab-arrow" aria-hidden="true">›</span>
      </button>
    </nav>

    <section v-show="activeStep === 'article'" class="step-page" aria-labelledby="article-step-title">
      <div class="step-content">
        <section class="card article-card">
          <div class="section-heading">
            <div><p class="eyebrow">01 · ARTICLE</p><h2 id="article-step-title">기사 읽기</h2></div>
            <span v-if="articleResult" class="status-pill status-done">분석 완료</span>
          </div>
          <label class="field-label" for="article-url">기사 URL</label>
          <input id="article-url" v-model="url" class="text-input" type="url" placeholder="https://news.example.com/article" />
          <details class="paste-details">
            <summary>기사 본문을 직접 붙여넣기</summary>
            <textarea v-model="pastedText" class="text-input article-textarea" rows="5" placeholder="URL에서 본문을 가져오기 어렵다면 기사 본문을 붙여넣으세요."></textarea>
            <label class="field-label" for="article-title">기사 제목 <span>필수</span></label>
            <input id="article-title" v-model="manualTitle" class="text-input" type="text" placeholder="붙여넣은 기사의 제목을 입력하세요" />
          </details>
          <button class="button button-primary button-wide" :disabled="busy || articleTermBusy || articleTermClassifying || !sessionReady || !sessionId" @click="analyzeArticle">
            <span v-if="busy && !messages.length" class="spinner"></span>
            기사 분석하기 <span aria-hidden="true">→</span>
          </button>
          <p v-if="currentStatus && !messages.length" class="inline-status">{{ currentStatus }}</p>
        </section>

        <div v-if="articleResult" ref="articleWorkspace" class="article-workspace">
          <div class="article-reading-column">
            <section class="card article-reading-card">
          <div class="section-heading compact-heading">
            <div>
              <p class="eyebrow">ARTICLE TEXT</p>
              <h2>{{ articleResult.title }}</h2>
            </div>
            <span class="status-pill status-done">기사 원문</span>
          </div>
          <div class="highlight-legend" aria-label="원문 강조 기준">
            <span><i class="term-swatch term-swatch-new"></i>새 용어</span>
            <span><i class="term-swatch term-swatch-known"></i>저장한 용어</span>
          </div>
          <div ref="articleTextContainer" class="article-reading-text" aria-label="기사 전체 원문"
            @mouseup="captureArticleTermSelection" @keyup="captureArticleTermSelection" @touchend="captureArticleTermSelection">
            <template v-for="(segment, index) in articleSegments" :key="index">
              <button v-if="segment.status" type="button" class="article-term-button"
                :aria-label="segment.text + '의 핵심 용어 설명 보기'"
                :title="segment.title + ' · 눌러서 오른쪽 핵심 용어 설명 보기'"
                :disabled="busy" @click="focusArticleTermSummary(segment.term)">
                <mark :class="'term-highlight-' + segment.status">{{ segment.text }}</mark>
              </button>
              <span v-else>{{ segment.text }}</span>
            </template>
          </div>
          <div class="article-term-edit-bar">
            <p>원문에서 낯선 용어를 드래그해 추가할 수 있습니다.</p>
            <div v-if="selectedArticleText" class="article-term-selection">
              <span>선택한 문구 <strong>{{ selectedArticleText }}</strong></span>
              <button type="button" class="button button-secondary" :disabled="busy || articleTermBusy || articleTermClassifying || selectedArticleText.length < 2 || selectedArticleText.length > 70"
                @click="addSelectedArticleTerm">
                {{ articleTermClassifying ? '분류 중…' : '용어로 추가' }}
              </button>
            </div>
            <p v-if="articleTermMessage" class="article-term-message" role="status">{{ articleTermMessage }}</p>
          </div>
            </section>
          </div>
          <aside class="article-brief-column">
            <section class="card briefing-card">
          <div class="section-heading compact-heading">
            <div><p class="eyebrow">ARTICLE BRIEF</p><h2>기사 브리핑</h2></div>
            <span class="type-pill">{{ articleResult.analysis.article_type }}</span>
          </div>
          <div class="briefing-field">
            <span class="mini-label">한 줄 정리</span>
            <p class="brief-summary">{{ articleResult.analysis.one_line_summary }}</p>
          </div>
          <div class="issue-block">
            <span class="mini-label">업계 이슈</span>
            <p>{{ articleResult.analysis.key_issue }}</p>
          </div>
          <div class="term-section">
            <div class="term-section-heading">
              <div>
                <p class="eyebrow">KEY TERMS</p>
                <h2>이 기사에서 알아둘 핵심 용어</h2>
              </div>
            </div>
            <div ref="articleTermList" class="term-list" :class="{ 'term-list-scrollable': terms.length >= 3 }"
              :style="{ '--term-list-scroll-tail': `${termListScrollTail}px` }">
              <article v-for="(term, index) in terms" :key="term.term" class="term-summary-item"
                :data-term-key="termStorageKey(term.term)"
                :class="{ 'term-summary-item-active': selectedTerm === term.term }">
                <div class="term-summary-heading">
                  <button type="button" class="term-summary-select" :aria-pressed="selectedTerm === term.term"
                    :disabled="busy || articleTermBusy || articleTermClassifying" @click="selectedTerm = term.term">
                    <span class="term-summary-index">{{ index + 1 }}.</span>
                    <strong>{{ term.term }}</strong>
                    <span class="term-summary-status" :class="isKnownTerm(term) ? 'known' : 'new'">
                      {{ isKnownTerm(term) ? '복습' : '새 용어' }}
                    </span>
                  </button>
                  <span class="term-summary-category">{{ recordCategoryLabels[term.category] || term.category || '기타' }}</span>
                  <button type="button" class="term-summary-remove" :aria-label="`${term.term}를 현재 기사 용어에서 제외`"
                    :title="'현재 기사에서 용어 제외'" :disabled="busy || articleTermBusy || articleTermClassifying"
                    @click="removeArticleTerm(term.term)">×</button>
                </div>
                <p class="term-summary-definition">{{ term.simple_definition || 'AI Tutor에서 이 용어의 의미를 질문해 보세요.' }}</p>
                <p class="term-summary-context"><em>이 기사에서는 · {{ term.article_context || '기사의 핵심 용어로 선정됐습니다.' }}</em></p>
              </article>
            </div>
            <p v-if="!terms.length" class="term-list-empty">추출된 용어가 없습니다. 원문에서 드래그해 직접 추가할 수 있습니다.</p>
          </div>
          <div class="read-actions">
            <label class="field-label" for="issue-group">읽은 기사를 이슈에 묶기 <span>선택</span></label>
            <select id="issue-group" v-model="selectedIssueId" class="text-input" :disabled="busy">
              <option value="">자동으로 판단</option>
              <option v-for="issue in industryIssues" :key="issue.issue_id" :value="issue.issue_id">
                직접 선택 · {{ issue.title }} ({{ issue.article_count }}건)
              </option>
            </select>
            <button class="button button-secondary button-wide" :disabled="busy || !sessionReady" @click="markArticleRead">
              읽은 기사로 저장 <span aria-hidden="true">✓</span>
            </button>
            <p v-if="readMessage" class="save-success">{{ readMessage }}</p>
          </div>
            </section>
          </aside>
        </div>
      </div>
      <div class="step-navigation">
        <span>원문과 브리핑을 확인한 뒤 AI Tutor에서 질문을 이어가세요.</span>
        <button class="button button-primary" @click="goToStep('tutor')">AI Tutor로 이동 <span aria-hidden="true">→</span></button>
      </div>
    </section>

    <section v-show="activeStep === 'tutor'" class="step-page" aria-labelledby="tutor-step-title">
      <div class="step-content tutor-content">
        <div class="tutor-workspace">
          <section class="card tutor-learning-card">
          <div class="section-heading">
            <div><p class="eyebrow">02 · AI TUTOR</p><h2 id="tutor-step-title">질문하고 학습하기</h2></div>
          </div>
          <p v-if="!articleResult" class="card-intro">기사 없이도 제약·바이오 개념을 자유롭게 질문할 수 있습니다.</p>
          <div class="tutor-controls">
            <label class="field-label" for="tutor-term-select">학습할 용어</label>
            <select id="tutor-term-select" class="text-input" :value="tutorTerm"
              :disabled="busy || !sessionReady" @change="switchTutorTerm($event.target.value)">
              <option value="">일반 질문</option>
              <option v-for="term in tutorTerms" :key="termStorageKey(term.term)" :value="term.term">
                {{ term.term }}{{ isKnownTerm(term) ? ' · 학습 기록 있음' : '' }}
              </option>
            </select>
          </div>
          <section v-if="selectedTutorTerm" class="term-guide" aria-label="용어 빠른 정리">
            <div class="term-guide-heading">
              <div><span class="mini-label">QUICK STUDY</span><h3>{{ selectedTutorTerm.term }} 빠른 정리</h3></div>
              <span>{{ selectedTutorTerm.category === 'Other' ? '기타' : selectedTutorTerm.category }}</span>
            </div>
            <article v-for="(item, index) in selectedTermGuide" :key="item.label" class="term-guide-row">
              <span class="term-guide-number">{{ index + 1 }}</span>
              <div><strong>{{ item.label }}</strong><p>{{ item.content }}</p></div>
            </article>
            <p class="term-guide-next">더 궁금한 내용은 AI Tutor에게 질문해 보세요.</p>
          </section>
          </section>
          <div class="tutor-chat-column">
            <section class="card chat-card">
              <div class="section-heading compact-heading">
                <div><p class="eyebrow">LLM TUTOR</p><h2>질문하고 답변 받기</h2></div>
              </div>
          <div ref="chatPanel" class="chat-panel" aria-live="polite">
            <div v-if="!messages.length" class="empty-chat">
              <div class="empty-icon">✳</div>
              <strong>{{ tutorTerm ? `${tutorTerm}부터 알아볼까요?` : '어떤 내용이 궁금한가요?' }}</strong>
              <hr>
              <div class="starter-questions">
                <button v-for="item in visibleStarterQuestions" :key="item.question" type="button"
                  @click="selectStarterQuestion(item.question)">{{ item.label }}</button>
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
                  <p class="answer-text" v-html="renderAnswerText(message.content)"></p>
                  <details v-if="message.sources?.length" class="source-details">
                    <summary>참고 자료 보기 <span>({{ message.sources.length }})</span></summary>
                    <div class="source-list">
                      <a v-for="(source, sourceIndex) in message.sources" :key="sourceIndex"
                         :href="source.url?.startsWith('http') ? source.url : undefined"
                         :target="source.url?.startsWith('http') ? '_blank' : undefined"
                         :rel="source.url?.startsWith('http') ? 'noreferrer' : undefined">
                        {{ source.title || source.record_id || '학습 기록' }}<small v-if="source.record_id"> · {{ source.record_id }}</small>
                      </a>
                    </div>
                  </details>
                  <div v-if="message.recommendations?.length" class="recommendations">
                    <div class="recommendation-heading"><span>다음 학습 방향</span><small>원하는 질문을 눌러 이어가세요</small></div>
                    <button v-for="item in message.recommendations" :key="item.category" type="button"
                      class="recommendation-card" :disabled="busy" @click="sendQuestion(item.question)">
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
          <form class="composer" @submit.prevent="sendQuestion()">
            <textarea id="question-input" v-model="question" rows="2" :disabled="busy || !sessionReady"
              placeholder="질문을 입력하세요 · Enter 전송 / Shift+Enter 줄바꿈"
              @keydown="handleQuestionKeydown"></textarea>
            <div class="composer-footer">
              <span>{{ selectedTutorTerm ? ` 선택 용어 · ${selectedTutorTerm.term}` : '선택 · 일반 질문' }}</span>
              <div>
                <button v-if="busy" class="button button-quiet" type="button" @click="cancelResponse">중단</button>
                <button class="send-button" type="submit" :disabled="busy || !sessionReady || !question.trim()" aria-label="질문 보내기">↑</button>
              </div>
            </div>
          </form>
            </section>

        <section v-if="selectedTutorTerm" class="card save-card">
          <div class="section-heading compact-heading">
            <div><p class="eyebrow">YOUR MEMORY</p><h2>대화를 내 학습 메모로 정리</h2></div>
            <span class="save-term-label">{{ selectedTutorTerm.term }}</span>
          </div>
          <p class="card-intro">AI Tutor 대화를 반영해 초안을 만듭니다. 대화가 없어도 기본 용어 정리로 시작할 수 있고, 초안은 직접 수정할 수 있습니다.</p>
          <button class="button button-secondary button-wide memo-draft-button" :disabled="busy" @click="buildStudyNoteDraft">
            대화를 반영한 학습 메모 만들기 <span aria-hidden="true">✎</span>
          </button>
          <template v-if="memoDraftReady">
            <label class="field-label" for="study-note">학습 메모 초안 <span>자유롭게 수정할 수 있어요</span></label>
            <textarea id="study-note" v-model="studyNote" class="text-input note-input" rows="14" maxlength="8000"></textarea>
            <button class="button button-primary button-wide" :disabled="!canSave || busy" @click="saveStudyRecord">
              이 용어 학습 기록 저장 <span aria-hidden="true">↓</span>
            </button>
          </template>
          <p v-if="saveMessage" class="save-success">{{ saveMessage }}</p>
        </section>
          </div>
        </div>
      </div>
      <div class="step-navigation">
        <button class="button button-secondary" @click="moveStep(-1)"><span aria-hidden="true">←</span> 기사 읽기로</button>
        <span>학습한 용어와 대화를 저장한 뒤 기록에서 다시 확인할 수 있습니다.</span>
        <button class="button button-primary" @click="goToStep('records')">내 학습 기록 <span aria-hidden="true">→</span></button>
      </div>
    </section>

    <section v-show="activeStep === 'records'" class="step-page" aria-labelledby="records-step-title">
      <div class="step-content records-grid">
        <section class="card records-card">
          <div class="section-heading compact-heading">
            <div><p class="eyebrow">03 · STUDY MEMORY</p><h2 id="records-step-title">내 학습 기록</h2></div>
            <button class="text-button" @click="refreshRecords">새로고침</button>
          </div>
          <div v-if="studyRecords.length" class="record-groups">
            <details v-for="(group, groupIndex) in studyRecordGroups" :key="group.category"
              class="record-group" :open="groupIndex === 0">
              <summary class="record-group-heading">
                <strong>{{ recordCategoryLabel(group.category) }}</strong>
                <span>{{ group.records.length }}개 용어 · 최신순</span>
              </summary>
              <div class="record-list">
                <button v-for="record in group.records" :key="record.term_key" type="button"
                  class="record-item" :class="{ 'record-item-active': selectedRecordKey === record.term_key }"
                  :aria-pressed="selectedRecordKey === record.term_key" @click="selectStudyRecord(record)">
                  <span class="record-dot"></span>
                  <span class="record-item-copy">
                    <strong>{{ record.term_name }}</strong>
                    <span class="record-summary">{{ record.simple_definition || '저장된 학습 용어' }}</span>
                    <span class="record-meta">{{ formatRecordDate(record.updated_at) }} · Q&A {{ record.qa_count }}</span>
                  </span>
                  <span class="record-chevron" aria-hidden="true">›</span>
                </button>
              </div>
            </details>
          </div>
          <p v-else class="records-empty">아직 저장된 용어가 없습니다. AI Tutor에서 용어를 선택하고 질문한 뒤 <strong>학습 용어와 관련 대화 저장</strong>을 눌러 보세요. 대화 요약과 질문이 없어도 기본 용어 정리가 기록됩니다.</p>
          <p v-if="studyRecords.length && !selectedStudyRecord" class="record-note-prompt">
            용어를 누르면 저장된 학습 메모가 여기에 표시됩니다.
          </p>
          <section v-if="selectedStudyRecord" class="record-note-detail" aria-live="polite">
            <div class="record-note-heading">
              <div>
                <span class="mini-label">저장된 학습 메모</span>
              </div>
              <span class="record-date">{{ formatRecordDate(selectedStudyRecord.updated_at) }}</span>
            </div>
            <div class="record-note-body" v-html="renderStudyNote(selectedStudyRecord)"></div>
            <p class="privacy-note">{{ recordCategoryLabel(selectedStudyRecord.category) }} · 관련 대화 {{ selectedStudyRecord.qa_count }}건</p>
          </section>
        </section>

        <section class="card issues-card">
          <div class="section-heading compact-heading">
            <div><p class="eyebrow">READING HISTORY</p><h2>읽은 기사와 산업 이슈</h2></div>
            <button class="text-button" @click="refreshReadingLists">새로고침</button>
          </div>
          <p class="card-intro">읽은 기사를 저장하면 같은 사건을 다룬 기사끼리 이슈 단위로 모아 보여줍니다.</p>
          <div v-if="industryIssues.length" class="issue-list">
            <article v-for="issue in industryIssues" :key="issue.issue_id" class="saved-issue">
              <div class="saved-issue-heading"><strong>{{ issue.title }}</strong><span>{{ issue.article_count }}건</span></div>
              <a v-for="article in issue.articles" :key="article.article_id"
                 :href="article.source_url?.startsWith('http') ? article.source_url : undefined"
                 :target="article.source_url?.startsWith('http') ? '_blank' : undefined"
                 :rel="article.source_url?.startsWith('http') ? 'noreferrer' : undefined">
                {{ article.title }}
              </a>
            </article>
          </div>
          <p v-else-if="!readArticles.length" class="records-empty">읽은 기사를 저장하면 여기에 이슈별로 표시됩니다.</p>
          <div v-if="readArticles.length" class="issue-list recent-articles">
            <span class="mini-label">최근 저장한 기사</span>
            <article v-for="article in readArticles" :key="article.article_id" class="saved-issue">
              <a :href="article.source_url?.startsWith('http') ? article.source_url : undefined"
                 :target="article.source_url?.startsWith('http') ? '_blank' : undefined"
                 :rel="article.source_url?.startsWith('http') ? 'noreferrer' : undefined">{{ article.title }}</a>
              <span v-if="article.issue_title" class="saved-issue-label">{{ article.issue_title }}</span>
            </article>
          </div>
          <p class="privacy-note">기사는 현재 세션 안에서만 보입니다.</p>
        </section>
      </div>
      <div class="step-navigation">
        <button class="button button-secondary" @click="moveStep(-1)"><span aria-hidden="true">←</span> AI Tutor로</button>
        <span>저장한 용어는 다음 기사 읽기에서 복습 용어로 표시됩니다.</span>
        <button class="button button-primary" @click="goToStep('article')">다음 기사 읽기 <span aria-hidden="true">→</span></button>
      </div>
    </section>

    <footer class="page-footer"><span>PharmaMate 3.0</span><span>Article learning · Evidence-aware answers · Personal memory</span></footer>
  </main>
</template>
