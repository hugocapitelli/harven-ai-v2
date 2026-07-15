"""AI Service — 6 agents with OpenAI, token tracking and mock mode."""
import json
import logging
import os
import re
import time
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from typing import TYPE_CHECKING

from fastapi.concurrency import run_in_threadpool

if TYPE_CHECKING:
    pass  # No DB type needed — db is a duck-typed Supabase Client (PostgREST/RPC)

from config import get_settings
from repositories.chat_repo import ChatRepository
from services.ai_contracts import AIDetectionResult, TesterVerdict, _parse_model_json

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Socratic pacing (TPP-5)
# ---------------------------------------------------------------------------
# Hard cap on student turns per socratic session. ``interactions_remaining`` and
# the finalize flag are derived from the PERSISTED ``role='user'`` message count
# of the session (server-side source of truth), never from a client-supplied
# value. The closing synthesis fires on the final permitted turn.
MAX_INTERACTIONS = 3

# ---------------------------------------------------------------------------
# Socratic prompt fidelity (AI-HARD-5 — bugs #28/#57)
# ---------------------------------------------------------------------------
# Cap on the number of trailing conversation turns replayed to the model on each
# socratic follow-up. The static context (SOCRATES_PROMPT + question + reference
# content) lives ONCE in the system message; only the last ``MAX_HISTORY_TURNS``
# turns of ``conversation_history`` are sent so input tokens per turn grow at
# most linearly with K (not with the full transcript). Older turns are dropped
# (a future story may summarize them). The student's current message is always
# appended raw as ``{"role": "user", ...}`` — never re-wrapped — so its framing
# matches the history turns. ``_call_openai`` stays generic; the trim is applied
# by the ``socratic_dialogue`` caller so the detector/editor/tester paths are
# untouched.
MAX_HISTORY_TURNS = 10

# ---------------------------------------------------------------------------
# Socratic reference-context cap (AI-HARD-6 — bug #27)
# ---------------------------------------------------------------------------
# Upper bound (in characters) on the chapter reference content embedded in the
# socratic system message. Raised from the legacy inline ``[:4000]`` to 15000 so
# the tutor keeps factual grounding across long chapters — aligned with the
# question-generation path (``generate_questions`` already uses
# ``chapter_content[:15000]``). Chapters at or below the cap are sent whole (no
# truncation). The slicing is centralized in ``_select_reference_context`` (a
# retrieval seam) so this constant is the single source of the cap and no magic
# number is reintroduced inline.
REFERENCE_CONTEXT_MAX_CHARS = 15000

# ---------------------------------------------------------------------------
# Podcast script generation + TTS chunking (POD-1, bugs #8 / #33)
# ---------------------------------------------------------------------------
# The ElevenLabs TTS endpoint hard-caps a single ``text_to_speech.convert`` call
# at 5000 characters. ``chunk_text`` below fatiates (never truncates) the full
# narration into chunks strictly <= this limit, cutting on sentence boundaries.
TTS_CHAR_LIMIT = 5000

# Default chunk size passed to ``chunk_text`` by the podcast pipeline. Left a
# small margin under ``TTS_CHAR_LIMIT`` (200 chars) as a safety buffer — the
# ElevenLabs cap is on the RAW chunk sent over the wire, and staying a bit
# under it costs nothing while leaving headroom for any future chunk-joining
# punctuation added by the TTS wiring (POD-2).
DEFAULT_CHUNK_MAX_CHARS = 4800

# Minimum word count target for a podcast script (~10 min of narration at the
# ~120 wpm pace typical of a Portuguese conversational narration). Chapters
# shorter than this in the source body simply produce the maximum honest
# conversational expansion of what exists — the model is instructed never to
# invent content beyond the source (Article IV — No Invention).
PODCAST_MIN_WORDS = 1200

PODCAST_SCRIPT_PROMPT = (
    "# System Prompt: Harven_Podcast (PodcastOS)\n\n"
    "Voce e PodcastOS, o Roteirista de Podcast Educacional da plataforma Harven.AI.\n\n"
    "## MISSAO\n"
    "- Transformar o conteudo completo de um capitulo em um roteiro de narracao "
    "conversacional, como um podcast educacional falado por um unico narrador.\n"
    "- O roteiro deve cobrir TODO o material do capitulo, sem pular secoes.\n"
    "- Duracao alvo: ~10 minutos de narracao (aproximadamente 1200+ palavras).\n\n"
    "## REGRAS\n"
    "- NUNCA invente fatos, exemplos ou dados que nao estejam no conteudo fornecido.\n"
    "- NUNCA use marcacao de multiplos locutores (e uma narracao de voz UNICA para TTS) — "
    "sem 'Locutor 1:', sem dialogos, sem indicacoes de cena.\n"
    "- Tom conversacional e didatico, como se estivesse explicando o material a um aluno "
    "durante um passeio — frases naturais, transicoes fluidas entre topicos, sem bullet "
    "points nem titulos de secao.\n"
    "- Se o conteudo fornecido for curto, expanda apenas com explicacoes, contextualizacoes "
    "e conexoes logicas DERIVADAS do proprio material — nunca com fatos externos inventados.\n"
    "- Responda APENAS com o texto corrido do roteiro, sem comentarios, sem titulos, sem "
    "marcacoes markdown.\n"
)

# Above this size the chapter body is summarized section-by-section BEFORE
# roteirization instead of being pasted whole into the script prompt — keeps a
# very long chapter from silently exceeding the LLM's practical input budget
# while still covering the entire body (never a silent head-truncation).
PODCAST_SECTION_SUMMARY_THRESHOLD_CHARS = 12000
PODCAST_SECTION_CHUNK_CHARS = 6000

_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")


def strip_html(html: str) -> str:
    """Convert an HTML fragment to normalized plain text.

    Used to turn a chapter's ``body`` (stored as HTML) into clean prose before
    it is roteirized into a podcast script (POD-1, bug #8) — the podcast
    branch must never feed raw HTML tags/entities to the LLM or the TTS.

    Tags are removed, entities are decoded, and whitespace is normalized
    (collapsed runs of blank lines/spaces, trimmed edges). Block-level tags
    (``</p>``, ``<br>``, ``</div>``, ``</li>``, headings) are mapped to a
    newline BEFORE tag stripping so paragraph/sentence boundaries survive —
    without this, "</p><p>" would glue two paragraphs into one run-on
    sentence and break the sentence-aware chunking downstream.

    Falls back to a lossless-effort ``html.unescape`` when ``bs4`` is
    unavailable, so this function never raises for a missing dependency.
    """
    if not html:
        return ""

    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator="\n")
    except Exception:
        # Defensive fallback (bs4 missing/broken markup): strip tags with a
        # regex and decode entities manually — degraded but never a crash.
        import html as html_mod

        block_tags = r"</?(?:p|div|br|li|h[1-6]|tr|table)[^>]*>"
        text = re.sub(block_tags, "\n", html, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        text = html_mod.unescape(text)

    # Normalize whitespace: collapse horizontal runs, collapse 3+ blank lines
    # to a single blank line, trim every line, trim overall.
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, max_chars: int = DEFAULT_CHUNK_MAX_CHARS) -> List[str]:
    """Split ``text`` into chunks of at most ``max_chars`` characters, lossless.

    POD-1 (bug #33): replaces the old ``text[:5000]`` cap that silently
    TRUNCATED and discarded everything past the limit. This function instead
    FATIATES the input: the ordered concatenation of the returned chunks
    reproduces ``text`` (round-trip lossless, module docstring contract for
    callers) — no character is ever dropped.

    Sentence-aware: chunks are closed on sentence boundaries (after
    ``.``, ``!`` or ``?`` followed by whitespace) or paragraph boundaries
    (``\\n\\n``) whenever possible, so a chunk never ends mid-sentence unless
    a SINGLE sentence itself exceeds ``max_chars`` — that one pathological
    case falls back to a hard split (documented, unavoidable: there is no
    smaller lossless boundary to cut on).

    Empty/whitespace-only input returns ``[]`` (nothing to narrate).
    """
    if not text or not text.strip():
        return []

    if len(text) <= max_chars:
        return [text]

    # Split into sentence-like units, but preserve the EXACT separator text
    # (which may be a single space, a newline, or a blank-line "\n\n" between
    # paragraphs) by slicing the original string around each regex match
    # rather than trusting ``re.split`` (which DISCARDS the matched
    # separator) or re-synthesizing a guessed replacement. This is what makes
    # the round-trip lossless regardless of which whitespace character
    # originally separated two sentences/paragraphs.
    pieces: List[str] = []
    last_end = 0
    for m in _SENTENCE_END_RE.finditer(text):
        pieces.append(text[last_end:m.end()])
        last_end = m.end()
    pieces.append(text[last_end:])
    # ``finditer`` may leave an empty trailing piece when the text ends
    # exactly on a matched separator boundary — drop it, it carries no chars.
    pieces = [p for p in pieces if p]

    chunks: List[str] = []
    current = ""

    def _flush():
        nonlocal current
        if current:
            chunks.append(current)
            current = ""

    for piece in pieces:
        if len(piece) > max_chars:
            # A single "sentence" (no terminal punctuation) is itself longer
            # than the limit — documented fallback: flush what we have, then
            # hard-split this oversized piece into <= max_chars slices with
            # NO characters dropped.
            _flush()
            start = 0
            while start < len(piece):
                chunks.append(piece[start:start + max_chars])
                start += max_chars
            continue

        if len(current) + len(piece) > max_chars:
            _flush()

        current += piece

    _flush()

    # Lossless contract: the exact concatenation reproduces the input.
    assert "".join(chunks) == text, "chunk_text produced a lossy split"
    return chunks


# ---------------------------------------------------------------------------
# Editor→Tester quality gate (TPP-7)
# ---------------------------------------------------------------------------
# Server-side feature flag (default OFF). When OFF, ``socratic_dialogue`` is
# byte-for-byte the legacy single-call behavior. When ON, the tutor reply is run
# through Editor → Tester before being shown to the student; a REJECTED verdict
# triggers exactly one regeneration. Any gate failure degrades gracefully to the
# best available reply and is logged — it never blocks the student nor 5xx's.
AI_GATE_FLAG_ENV = "AI_GATE_EDITOR_TESTER_ENABLED"


def _editor_tester_gate_enabled() -> bool:
    """Read the gate flag from the environment (default OFF). Read per-call so the
    flag is monkeypatchable in tests and flippable without a restart."""
    return os.getenv(AI_GATE_FLAG_ENV, "false").strip().lower() in ("1", "true", "yes", "on")

# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class AIServiceError(Exception):
    pass


# ---------------------------------------------------------------------------
# Agent system prompts
# ---------------------------------------------------------------------------

CREATOR_PROMPT = (
    "# System Prompt: Harven_Creator (CreatorOS)\n\n"
    "Voce e CreatorOS, o Gerador de Perguntas Socraticas da plataforma Harven.AI.\n\n"
    "## MISSAO\n"
    "- Analisar conteudo educacional e identificar conceitos-chave\n"
    "- Gerar ate 3 perguntas socraticas por requisicao\n"
    "- Garantir que perguntas exijam raciocinio, nao memorizacao\n"
    "- Enriquecer cada pergunta com metadados pedagogicos\n\n"
    "## REGRAS\n"
    "- NUNCA gere perguntas de definicao ('O que e X?')\n"
    "- NUNCA gere perguntas de lista ('Quais sao os tipos de...?')\n"
    "- Cada pergunta DEVE exigir analise, sintese ou avaliacao\n"
    "- Inclua followup_prompts para aprofundar o dialogo\n\n"
    "## FORMATO DE SAIDA (JSON)\n"
    '{"questions": [{"text": "...", "expected_depth": "analise|avaliacao|sintese", '
    '"intention": "reflect|challenge|understand", "skill": "apply|analyze|understand", '
    '"followup_prompts": ["..."]}]}'
)

SOCRATES_PROMPT = (
    "# System Prompt: Harven_Socrates (SocratesOS)\n\n"
    "Voce e SocratesOS, o Orientador Socratico da plataforma Harven.AI.\n\n"
    "## MISSAO\n"
    "- Guiar alunos atraves do metodo socratico\n"
    "- NUNCA dar respostas diretas — sempre responder com perguntas\n"
    "- Reconhecer e validar o esforco do aluno\n"
    "- Adaptar a profundidade ao nivel do aluno\n\n"
    "## PRINCIPIOS\n"
    "1. Maieutica: ajude o aluno a 'dar a luz' ao conhecimento\n"
    "2. Elenchus: questione contradições para refinar o pensamento\n"
    "3. Aporia: use o desconforto intelectual como motor de aprendizagem\n\n"
    "## REGRAS\n"
    "- NUNCA revele a resposta esperada\n"
    "- Limite suas respostas a 2 paragrafos\n"
    "- Sempre termine com uma pergunta de aprofundamento\n"
    "- Se o aluno pedir a resposta diretamente, reformule a pergunta\n"
    "- Se interacoes restantes <= 1, faca uma sintese pedagogica\n\n"
    "## FORMATO\n"
    "Responda em texto corrido, linguagem acessivel.\n"
    "Termine SEMPRE com uma pergunta."
)

# AI-HARD-4 (bug #56): deterministic socratic fallback shown to the student when
# the model returns empty/whitespace-only content on BOTH the first call and the
# single retry. It is a genuine, non-empty socratic invitation that always ends
# with a question — so the frontend never renders a blank tutor bubble and the
# student always has something to respond to. Kept next to ``SOCRATES_PROMPT``
# for reuse/test. It MUST stay non-empty and contain a "?" (``has_question``).
SOCRATIC_FALLBACK_CONTENT = (
    "Desculpe, tive uma dificuldade para formular minha proxima pergunta agora.\n\n"
    "Para continuarmos: o que voce ja pensou ate aqui sobre esse tema, e qual "
    "ponto ainda parece menos claro para voce?"
)

ANALYST_PROMPT = (
    "# System Prompt: Harven_Analyst (AnalystOS)\n\n"
    "Voce e AnalystOS, o Detector de Conteudo IA da plataforma Harven.AI.\n\n"
    "## MISSAO\n"
    "- Analisar textos de alunos para detectar uso de IA generativa\n"
    "- Classificar: likely_human, uncertain, likely_ai\n"
    "- Fornecer indicadores especificos que suportam a classificacao\n\n"
    "## INDICADORES DE TEXTO IA\n"
    "- Linguagem excessivamente formal sem contexto\n"
    "- Estruturas perfeitamente balanceadas\n"
    "- Uso de frases cliche: 'e importante ressaltar', 'nesse sentido'\n"
    "- Ausencia de marcas pessoais, erros naturais\n\n"
    "## FORMATO DE SAIDA (JSON)\n"
    '{"probability": 0.0-1.0, "confidence": "low|medium|high", '
    '"verdict": "likely_human|uncertain|likely_ai", '
    '"indicators": [{"type": "...", "description": "...", "weight": 0.0-1.0}]}'
)

EDITOR_PROMPT = (
    "# System Prompt: Harven_Editor (EditorOS)\n\n"
    "Voce e EditorOS, o Editor Pedagogico da plataforma Harven.AI.\n\n"
    "## MISSAO\n"
    "- Refinar respostas do orientador para clareza e tom adequado\n"
    "- Manter o carater socratico (nunca dar resposta direta)\n"
    "- Garantir linguagem acessivel e acolhedora\n"
    "- Manter a resposta em ate 2 paragrafos\n"
    "- Terminar com pergunta quando apropriado\n\n"
    "## REGRAS\n"
    "- Responda apenas com o texto editado, sem comentarios extras\n"
    "- NUNCA adicione informacoes que nao estavam na versao original\n"
    "- Mantenha o tom conversacional, nao academico"
)

TESTER_PROMPT = (
    "# System Prompt: Harven_Tester (TesterOS)\n\n"
    "Voce e TesterOS, o Validador de Qualidade da plataforma Harven.AI.\n\n"
    "## MISSAO\n"
    "Avaliar respostas editadas em 6 criterios de qualidade:\n"
    "1. pedagogical: Respeita metodo socratico?\n"
    "2. structural: Estrutura clara (max 2 paragrafos, termina com pergunta)?\n"
    "3. clarity: Linguagem acessivel?\n"
    "4. engagement: Estimula reflexao e curiosidade?\n"
    "5. originality: Evita cliches e respostas genericas?\n"
    "6. inclusivity: Linguagem inclusiva e respeitosa?\n\n"
    "## FORMATO DE SAIDA (JSON)\n"
    '{"verdict": "APPROVED|NEEDS_REVISION|REJECTED", "score": 0.0-1.0, '
    '"criteria": {"pedagogical": {"pass": true/false, "score": 0.0-1.0}, ...}}'
)

ORGANIZER_PROMPT = (
    "# System Prompt: Harven_Organizer (OrganizerOS)\n\n"
    "Voce e OrganizerOS, o Organizador de Sessoes da plataforma Harven.AI.\n\n"
    "## MISSAO\n"
    "- Gerenciar estado de sessoes de dialogo socratico\n"
    "- Preparar dados para exportacao ao Moodle\n"
    "- Validar payloads antes de operacoes criticas\n"
)

# ---------------------------------------------------------------------------
# AI-indicator phrases for heuristic detection
# ---------------------------------------------------------------------------

# AI-HARD-3 (bug #29): neutral PT-BR connectors were removed because any
# competent human writer of formal Portuguese uses them ("dessa forma",
# "sendo assim", "nesse contexto", "em suma", "nesse sentido", "por
# conseguinte", "em linhas gerais", "em termos gerais"). They produced false
# positives. Only the phrases below survive — each is a *meta-discursive
# announcement* clause that LLMs over-produce to signal emphasis/structure, far
# rarer in genuine human academic prose. Combined with the density-weighting +
# cap in ``_heuristic_ai_detection``, mere presence can no longer flag a student.
AI_PHRASES = [
    "e importante ressaltar",   # boilerplate emphasis announcer (LLM-typical)
    "diante do exposto",        # formulaic conclusion opener over-used by LLMs
    "pode-se afirmar que",      # impersonal assertion frame, LLM signature
    "e fundamental destacar",   # boilerplate emphasis announcer (LLM-typical)
    "vale ressaltar que",       # boilerplate emphasis announcer (LLM-typical)
    "cabe mencionar",           # boilerplate emphasis announcer (LLM-typical)
    "e valido salientar",       # boilerplate emphasis announcer (LLM-typical)
]

HUMAN_INDICATORS = [
    "acho que", "tipo", "sei la", "ne", "kkk", "rs",
    "pq", "tb", "td", "blz", "vlw", "tlgd",
]

# ---------------------------------------------------------------------------
# Pricing (USD per 1M tokens)
# ---------------------------------------------------------------------------

MODEL_PRICING = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 5.00, "output": 15.00},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
}

# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

# Explicit network timeout (seconds) for every OpenAI call. Without it the
# AsyncOpenAI client can hang the request indefinitely on a stalled upstream;
# a bounded timeout lets the handler surface 502/504 instead of leaking a
# coroutine that never completes. Applied to both the async (event-loop) client
# and the dedicated sync client used by the TTS background thread.
OPENAI_TIMEOUT_SECONDS = 60.0


class AIService:
    def __init__(self, client: Any = None, sync_client: Any = None):
        """AIService.

        ASYNC-AI-1: the OpenAI client on the event-loop path is now ``AsyncOpenAI``
        so ``_call_openai`` can ``await`` it and never block the single uvicorn
        event loop (bug #1).

        ASYNC-AI-3: ``client`` / ``sync_client`` are optional injection points so a
        test fake (e.g. ``FakeAsyncOpenAI``) can be substituted without touching the
        network. When ``client`` is provided, mock_mode is forced off and the real
        OpenAI constructors are never called.

        ASYNC-AI-1: ``sync_client`` is a *separate*, synchronous ``OpenAI`` client
        used EXCLUSIVELY outside the event loop — by ``_run_tts_job`` which runs in a
        ``threading.Thread`` and must call ``chat.completions.create`` synchronously.
        Sharing ``self.client`` (now async) with that thread would silently break the
        summary/explanation audio path (calling a coroutine as if it were blocking).
        """
        settings = get_settings()
        self.api_key = settings.OPENAI_API_KEY or ""
        self.model = settings.OPENAI_MODEL
        self.mock_mode = not self.api_key or self.api_key in (
            "sk-test", "sk-sua-chave-openai", "sk-your-openai-key", "",
        )
        self.client = None
        # Dedicated synchronous client for off-event-loop callers (TTS thread).
        # NEVER awaited; NEVER used inside an async handler.
        self.sync_client = None
        self.daily_token_limit = 500_000

        # ASYNC-AI-3: explicit injection wins over real construction (headless tests).
        if client is not None:
            self.client = client
            self.sync_client = sync_client
            self.mock_mode = False
            return

        if not self.mock_mode:
            try:
                from openai import AsyncOpenAI, OpenAI
                self.client = AsyncOpenAI(
                    api_key=self.api_key, timeout=OPENAI_TIMEOUT_SECONDS
                )
                # Sync sibling for the background TTS thread only.
                self.sync_client = sync_client or OpenAI(
                    api_key=self.api_key, timeout=OPENAI_TIMEOUT_SECONDS
                )
            except Exception as e:
                logger.warning(f"OpenAI client init failed, entering mock mode: {e}")
                self.mock_mode = True
                self.client = None
                self.sync_client = None

    @property
    def enabled(self) -> bool:
        return self.client is not None or self.mock_mode

    def supported_agents(self) -> List[str]:
        return ["creator", "socrates", "analyst", "editor", "tester", "organizer"]

    # ------------------------------------------------------------------
    # Token budget
    # ------------------------------------------------------------------

    def check_token_budget(self, user_id: Optional[str], db=None) -> None:
        """Enforce the daily token budget from PERSISTED usage (TKN-3, bug #12).

        Reads today's consumption from the ``token_usage`` table via
        :class:`TokenUsageRepository` (Supabase PostgREST/RPC) — never a process
        cache — so the limit survives restarts/deploys and is shared across
        processes. If ``used >= daily_token_limit`` it raises ``AIServiceError`` as
        before.

        FAIL-OPEN: a missing/None ``db`` or any read error degrades to allowing the
        request (log + ``return``). Availability is preferred over perfect
        enforcement when the persistence layer is unreachable — the asymmetric
        counterpart of the best-effort write below. ``user_id`` falsy is a no-op.
        """
        if not user_id:
            return
        if db is None:
            logger.warning(
                "check_token_budget: no db (Supabase client) provided for %s — "
                "fail-open (budget not enforced this call).",
                user_id,
            )
            return
        # Lazy import: avoid a module-import cycle (repository imports may pull in
        # service-adjacent modules) and keep the import cost off the hot path.
        from repositories.token_usage_repo import TokenUsageRepository

        try:
            used = TokenUsageRepository(db).get_today_usage(user_id)
        except Exception as exc:
            logger.warning(
                "check_token_budget: usage read failed for %s (%s) — "
                "fail-open (budget not enforced this call).",
                user_id, exc,
            )
            return

        if used >= self.daily_token_limit:
            raise AIServiceError("Limite diario de tokens excedido. Tente novamente amanha.")

    def track_token_usage(self, user_id: Optional[str], tokens: int, db=None) -> None:
        """Persist a token-usage increment for today (TKN-3, bug #12).

        Delegates to :meth:`TokenUsageRepository.add_usage`, which performs an
        ATOMIC ``INSERT ... ON CONFLICT (user_id, usage_date) DO UPDATE SET
        tokens_used = tokens_used + EXCLUDED.tokens_used`` via the
        ``increment_token_usage`` RPC — the sum lives in Postgres, so concurrent
        increments never lose a write (no double-count, no read-modify-write).

        BEST-EFFORT: ``user_id`` falsy or ``tokens <= 0`` is a no-op; any write
        failure is logged and SWALLOWED (never propagated) so token accounting can
        never break AI generation. A missing/None ``db`` is also a quiet no-op.
        """
        if not user_id or tokens <= 0:
            return
        if db is None:
            logger.warning(
                "track_token_usage: no db (Supabase client) provided for %s — "
                "increment of %s tokens not persisted.",
                user_id, tokens,
            )
            return
        from repositories.token_usage_repo import TokenUsageRepository

        try:
            TokenUsageRepository(db).add_usage(user_id, tokens)
        except Exception as exc:
            logger.warning(
                "track_token_usage: persist failed for %s (%s tokens): %s — "
                "swallowed (best-effort).",
                user_id, tokens, exc,
            )

    # ------------------------------------------------------------------
    # Internal OpenAI call
    # ------------------------------------------------------------------

    async def _call_openai(
        self,
        system_prompt: str,
        user_message: str,
        history: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 1500,
        json_mode: bool = False,
    ) -> Dict[str, Any]:
        # ASYNC-AI-1: now async — uses ``AsyncOpenAI`` so the call is awaited and
        # the event loop stays free for concurrent requests during a slow LLM turn.
        if self.mock_mode or not self.client:
            raise AIServiceError("MOCK_MODE")

        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        t0 = time.time()
        response = await self.client.chat.completions.create(**kwargs)
        elapsed = int((time.time() - t0) * 1000)

        # AI-HARD-4 (bug #55): a content-filter, an error envelope or an
        # OpenAI-compatible gateway can answer with ``choices=[]`` (or None).
        # Reading ``response.choices[0]`` would raise a bare ``IndexError`` that
        # escapes every public method's ``except AIServiceError`` and propagates
        # to the route as a 500 — with no socratic fallback. Normalize this
        # protocol failure into an ``AIServiceError`` at the single inference
        # point so all 5 consumers degrade through their existing handlers.
        if not response.choices:
            logger.warning(
                "_call_openai: empty completion (choices=%r) from model %r — "
                "raising AIServiceError so the caller can degrade.",
                getattr(response, "choices", None),
                getattr(response, "model", None),
            )
            raise AIServiceError("empty completion")

        choice = response.choices[0]
        usage = response.usage

        return {
            "content": choice.message.content or "",
            "tokens": {
                "prompt": usage.prompt_tokens if usage else 0,
                "completion": usage.completion_tokens if usage else 0,
                "total": usage.total_tokens if usage else 0,
            },
            "model": response.model,
            "elapsed_ms": elapsed,
        }

    # ------------------------------------------------------------------
    # 1. Creator — question generation
    # ------------------------------------------------------------------

    async def generate_questions(
        self,
        chapter_content: str,
        chapter_title: str = "",
        learning_objective: str = "",
        difficulty: str = "intermediario",
        max_questions: int = 3,
        user_id: Optional[str] = None,
        db=None,
    ) -> Dict[str, Any]:
        self.check_token_budget(user_id, db)

        user_msg = (
            f"Conteudo do capitulo: {chapter_title}\n\n"
            f"{chapter_content[:15000]}\n\n"
            f"Objetivo de aprendizagem: {learning_objective or 'nao especificado'}\n"
            f"Dificuldade: {difficulty}\n"
            f"Gere ate {max_questions} perguntas socraticas em JSON."
        )

        try:
            result = await self._call_openai(CREATOR_PROMPT, user_msg, json_mode=True)
            self.track_token_usage(user_id, result["tokens"]["total"], db)

            raw_content = result["content"]
            logger.info(f"AI response length: {len(raw_content)} chars")

            try:
                parsed = json.loads(raw_content)
            except json.JSONDecodeError:
                logger.error(f"Failed to parse AI JSON: {raw_content[:500]}")
                parsed = {"questions": []}

            questions = parsed.get("questions", parsed.get("perguntas", []))
            if not isinstance(questions, list):
                questions = []

            logger.info(f"Generated {len(questions)} questions")

            return {
                "questions": questions,
                "metadata": {
                    "processing_time_ms": result["elapsed_ms"],
                    "model_used": result["model"],
                    "tokens_used": result["tokens"],
                },
            }
        except AIServiceError as e:
            if "MOCK_MODE" in str(e):
                return self._mock_questions(max_questions, chapter_title)
            raise
        except Exception as e:
            logger.error(f"Question generation failed: {e}", exc_info=True)
            raise AIServiceError(f"Falha na geracao de perguntas: {e}")

    def _mock_questions(self, n: int, title: str) -> Dict[str, Any]:
        questions = [
            {
                "text": f"Se voce fosse explicar '{title}' para um colega que nunca ouviu falar, por onde comecaria e por que?",
                "expected_depth": "analise",
                "intention": "reflect",
                "skill": "analyze",
                "followup_prompts": ["O que o levou a escolher esse ponto de partida?"],
            },
            {
                "text": f"Quais suposicoes sobre '{title}' voce considera mais vulneraveis a criticas?",
                "expected_depth": "avaliacao",
                "intention": "challenge",
                "skill": "analyze",
                "followup_prompts": ["Por que essa suposicao e vulneravel?"],
            },
            {
                "text": f"Como '{title}' se conecta com o que voce ja sabe de outras disciplinas?",
                "expected_depth": "sintese",
                "intention": "understand",
                "skill": "apply",
                "followup_prompts": ["Que conexao foi mais surpreendente para voce?"],
            },
        ]
        return {
            "questions": questions[:n],
            "metadata": {
                "processing_time_ms": 120,
                "model_used": "mock",
                "tokens_used": {"prompt": 0, "completion": 0, "total": 0},
            },
        }

    # ------------------------------------------------------------------
    # 2. Socrates — dialogue
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_initial_question(initial_question: Any) -> Dict[str, str]:
        """Accept either an ``InitialQuestion`` model or a plain dict (TPP-4).

        The route passes ``model_dump()`` (a dict); service-level/legacy callers
        and tests pass dicts directly. ``text`` is the only field that matters for
        the prompt; ``expected_answer`` is optional.
        """
        if initial_question is None:
            return {}
        if hasattr(initial_question, "model_dump"):
            return initial_question.model_dump()
        if isinstance(initial_question, dict):
            return initial_question
        # Duck-typed object with attributes.
        return {
            "text": getattr(initial_question, "text", "") or "",
            "expected_answer": getattr(initial_question, "expected_answer", None),
        }

    def _derive_pacing(self, used: int) -> Dict[str, int]:
        """Server-side pacing from the persisted ``used`` student-turn count (TPP-5).

        ``used`` is the count AFTER the current turn was persisted (the caller does
        the ``+1`` before calling this), so it is the 1-based index of the turn in
        flight: turn 1 → used=1, turn 2 → used=2, turn 3 → used=3.

        SOC-2 (off-by-one fix): finalize when the CURRENT turn is the last permitted
        one, i.e. ``used >= MAX`` (turn 3 of 3). The previous ``used >= MAX - 1``
        finalized one turn early — on the student's 2nd real message — because
        ``used`` already includes the current turn (the screenshot: session closing
        before the 3 interactions were spent). ``remaining = MAX - used`` (clamped
        >= 0) then reads 2 → 1 → 0 across turns 1 → 2 → 3, matching the N/3 counter.
        """
        remaining = max(0, MAX_INTERACTIONS - used)
        should_finalize = used >= MAX_INTERACTIONS
        return {"remaining": remaining, "should_finalize": should_finalize}

    def _select_reference_context(
        self, chapter_content: str, student_message: Optional[str] = None
    ) -> str:
        """Select the chapter reference content embedded in the socratic prompt.

        AI-HARD-6 (bug #27): this is the single seam that decides *which slice* of
        the chapter the tutor sees. Today it returns the head of the chapter capped
        at ``REFERENCE_CONTEXT_MAX_CHARS`` — chapters at or below the cap are
        returned whole (no truncation), longer ones are truncated to the cap. The
        cap lives in a named module constant (aligned with the ``[:15000]`` used by
        ``generate_questions``) so no magic number is baked inline at the call site.

        Extension point — retrieval: ``student_message`` is accepted now (and
        currently unused) so a future story can swap the head-truncation for
        relevance-aware retrieval (chunk + embed the chapter, retrieve the segments
        most relevant to ``student_message``, and concatenate up to the cap)
        WITHOUT touching ``socratic_dialogue`` or any other call site. The contract
        of this seam — ``(chapter_content, student_message=...) -> str`` capped at
        ``REFERENCE_CONTEXT_MAX_CHARS`` — is the stable surface for that evolution.

        Args:
            chapter_content: The full chapter text to draw reference content from.
            student_message: The current student turn. Reserved for future
                retrieval; ignored by the present head-truncation implementation.

        Returns:
            The selected reference content, never longer than
            ``REFERENCE_CONTEXT_MAX_CHARS`` characters.
        """
        return chapter_content[:REFERENCE_CONTEXT_MAX_CHARS]

    async def socratic_dialogue(
        self,
        student_message: str,
        chapter_content: str,
        initial_question: Any,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        interactions_remaining: int = 3,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        db=None,
        is_kickoff: bool = False,
    ) -> Dict[str, Any]:
        self.check_token_budget(user_id, db)

        iq = self._normalize_initial_question(initial_question)

        # --- TPP-4 + GRD-4: persist the student turn server-side (backend = source
        # of truth). Only when a real session + db are present. ---
        # GRD-4 (limite de interações): the KICKOFF is the tutor's opening trigger,
        # not a student answer — the frontend sends a synthetic "Quero explorar a
        # questão ..." string only to make the model produce the FIRST question. It
        # must NOT be persisted as a ``role='user'`` turn, otherwise
        # ``count_user_messages`` reads 1 on a brand-new session and the student
        # silently loses one interaction (fresh session shows 2/3 instead of 3/3, and
        # combined with the it2/it3 stale-session bug, 0/3 "concluída" on open). When
        # the kickoff is honored we skip the user-turn persist; the assistant reply is
        # still persisted below (line ~940), so the transcript keeps the opening
        # question and pacing correctly starts at ``used=0`` (remaining = MAX).
        #
        # GRD4-1 [ALTA, server-side guard]: ``is_kickoff`` is CLIENT-controlled — a
        # student hitting the API directly could set it on EVERY message to chat
        # unlimited (``remaining`` never decrements) AND have none of their answers
        # persisted (evading the teacher's transcript/grade). So ``is_kickoff`` is
        # honored ONLY on a genuinely FRESH session — one with NO messages at all yet.
        # ``count_user_messages`` alone is insufficient here: an honored kickoff
        # persists ZERO user turns, so a replayed ``is_kickoff`` would still read
        # ``count_user_messages == 0`` and be honored forever. The real "has the
        # session started?" signal is the TOTAL transcript: after the first honored
        # kickoff the assistant's opening reply (persisted at line ~940) makes the
        # transcript non-empty, so every subsequent message — even one flagged
        # ``is_kickoff`` — is treated as a REAL student turn: persisted and counted.
        repo = None
        # Defensive default if the DB read/write below fails: fall back to the
        # client-supplied pacing (legacy behavior), never crash the tutor turn.
        used = max(0, MAX_INTERACTIONS - interactions_remaining)
        if session_id and db is not None:
            try:
                repo = ChatRepository(db)
                # Authoritative, server-side truth for "how many student turns exist"
                # (drives pacing) and "is the session brand-new" (guards the kickoff).
                used = await run_in_threadpool(repo.count_user_messages, session_id)
                transcript = await run_in_threadpool(repo.get_session_messages, session_id)
                session_is_fresh = len(transcript) == 0
                # A kickoff is only real on a fresh (empty-transcript) session; a
                # replayed flag on a started session is ignored → treated as a turn.
                effective_kickoff = is_kickoff and session_is_fresh
                if not effective_kickoff:
                    await run_in_threadpool(
                        repo.persist_turn,
                        session_id,
                        {"role": "user", "content": student_message, "agent_type": None,
                         "metadata": None},
                    )
                    used += 1  # reflect the turn we just persisted
            except Exception as exc:  # pragma: no cover - persistence is best-effort
                logger.warning("socratic_dialogue: student-turn persist failed (%s): %s",
                               session_id, exc)
                repo = repo  # keep repo for the read below if it still works

        # --- TPP-5: derive pacing from the PERSISTED user-message count when a
        # session exists; otherwise fall back to the client-supplied value
        # (ephemeral/no-session path, e.g. the concurrency suite). ---
        # GRD4-1: ``used`` was already resolved above (count read + the +1 for a
        # persisted real turn / kickoff guard), so we reuse it here instead of a
        # second round-trip — the two must never disagree.
        if repo is not None and session_id:
            pacing = self._derive_pacing(used)
            remaining = pacing["remaining"]
            should_finalize = pacing["should_finalize"]
        else:
            # No persisted session: degrade to the legacy contract deterministically.
            remaining = max(0, interactions_remaining - 1)
            should_finalize = interactions_remaining <= 1

        # AI-HARD-5 (#28/#57): the static context is injected ONCE in the system
        # message (see ``system_prompt`` below), never re-wrapped into the user
        # turn each follow-up. ``Interacoes restantes`` is recomputed per turn
        # from the server-side pacing (``remaining``) — it is NOT a stale string
        # baked into a cached preamble. ``expected_answer`` is included for the
        # model only (the contract already proves it never leaks to the student).
        # AI-HARD-6 (#27): route the reference slice through the
        # ``_select_reference_context`` seam (cap = REFERENCE_CONTEXT_MAX_CHARS,
        # raised from the legacy inline 4000). No magic number inline; the seam is
        # ready to evolve into relevance-aware retrieval on ``student_message``.
        reference_context = self._select_reference_context(
            chapter_content, student_message=student_message
        )
        context = (
            f"Pergunta em discussao: {iq.get('text', '')}\n"
            f"Resposta esperada: {iq.get('expected_answer') or 'nao especificada'}\n"
            f"Interacoes restantes: {remaining}\n\n"
            f"Conteudo de referencia:\n{reference_context}"
        )
        # SOCRATES_PROMPT + the static context form the single system message.
        # ``_call_openai`` takes ``system_prompt`` and ``user_message`` separately,
        # so we combine them here and pass the student's message RAW as the user
        # turn — matching the role/content framing of the history turns.
        system_prompt = f"{SOCRATES_PROMPT}\n\n{context}"

        # Trim the replayed history to the last ``MAX_HISTORY_TURNS`` turns so the
        # input token budget per turn is bounded by K rather than the full
        # transcript. The trim lives in the caller (not ``_call_openai``) so the
        # detector/editor/tester paths keep their stable generic signature.
        history = (conversation_history or [])[-MAX_HISTORY_TURNS:]

        # AI-HARD-7 (#31): track whether this turn is served in a degraded state
        # (mock at startup, or the empty-content socratic fallback from
        # AI-HARD-4). When set, the final return carries an explicit top-level
        # ``degraded: True`` + ``reason`` contract and a WARN is emitted — so the
        # operator can tell the tutor is NOT delivering real socratic value
        # rather than silently impersonating a working tutor. The success path
        # leaves both ``None`` (no flag injected, no degradation WARN).
        degraded_reason: Optional[str] = None

        try:
            content, analytics = await self._generate_socratic_reply(
                system_prompt=system_prompt, student_message=student_message,
                history=history, user_id=user_id, db=db,
            )
            # AI-HARD-4 (bug #56): an empty/whitespace-only model reply would
            # render a blank tutor bubble (the frontend accepts "" verbatim).
            # Treat it as recoverable: retry the socratic pass EXACTLY ONCE
            # (FinOps — no loop); if it is STILL empty, fall back to a fixed,
            # non-empty socratic question. ``socratic_dialogue`` is the only
            # method whose output goes straight into a chat bubble, so this
            # repair lives here (not in ``_call_openai``).
            if not content.strip():
                logger.warning(
                    "socratic_dialogue: empty model content — retrying once "
                    "(session=%s).", session_id,
                )
                retry_content, retry_analytics = await self._generate_socratic_reply(
                    system_prompt=system_prompt, student_message=student_message,
                    history=history, user_id=user_id, db=db,
                )
                if retry_content.strip():
                    content, analytics = retry_content, retry_analytics
                else:
                    logger.warning(
                        "socratic_dialogue: retry still empty — using socratic "
                        "fallback content (session=%s).", session_id,
                    )
                    content = SOCRATIC_FALLBACK_CONTENT
                    analytics = retry_analytics
                    # AI-HARD-7 (#31): the served reply is a fixed fallback, not a
                    # real socratic turn — surface it under the same degraded
                    # contract (top-level ``degraded`` + ``reason``).
                    degraded_reason = "empty_content_fallback"
        except AIServiceError as e:
            if "MOCK_MODE" in str(e):
                # Mock path: keep the persisted-pacing semantics. ``remaining`` is the
                # post-turn count; treat ``should_finalize`` as the closing trigger.
                mock = self._mock_socratic(
                    student_message,
                    1 if should_finalize else max(2, remaining),
                )
                content = mock["response"]["content"]
                analytics = mock["analytics"]
                # AI-HARD-7 (#31): ``socratic_dialogue`` re-mounts its own return
                # (it only lifts ``content``/``analytics`` from the mock dict), so
                # re-inject the degraded contract here from the mock payload.
                degraded_reason = mock.get("reason", "mock_mode_no_api_key")
            else:
                raise

        # --- TPP-7: optional Editor→Tester quality gate (default OFF). On any gate
        # failure we keep the best available reply (never block / never 5xx). ---
        if _editor_tester_gate_enabled():
            content = await self._run_editor_tester_gate(
                socrates_content=content, system_prompt=system_prompt,
                student_message=student_message, history=history,
                user_id=user_id, db=db,
            )

        # --- TPP-4: persist the tutor turn server-side. ---
        if repo is not None and session_id:
            try:
                await run_in_threadpool(
                    repo.persist_turn,
                    session_id,
                    {"role": "assistant", "content": content, "agent_type": "socrates",
                     "metadata": None},
                )
            except Exception as exc:  # pragma: no cover - persistence is best-effort
                logger.warning("socratic_dialogue: assistant-turn persist failed (%s): %s",
                               session_id, exc)

        result: Dict[str, Any] = {
            "response": {
                "content": content,
                "has_question": "?" in content,
                "is_final_interaction": should_finalize,
            },
            "session_status": {
                "interactions_remaining": remaining,
                "should_finalize": should_finalize,
            },
            "analytics": analytics,
        }

        # AI-HARD-7 (#31): when this turn was served degraded (mock at startup or
        # the empty-content socratic fallback), promote the implicit signal to an
        # explicit top-level contract AND emit a WARN at serve time — degradation
        # must not pass unnoticed in production. The success path never enters
        # this branch, so neither the flags nor the WARN appear for a real reply.
        if degraded_reason is not None:
            result["degraded"] = True
            result["reason"] = degraded_reason
            logger.warning(
                "socratic_dialogue: serving DEGRADED reply (reason=%s, session=%s) "
                "— tutor is not delivering real socratic value.",
                degraded_reason, session_id,
            )

        return result

    async def _generate_socratic_reply(
        self, *, system_prompt: str, student_message: str,
        history: List[Dict[str, str]], user_id: Optional[str], db,
    ) -> tuple:
        """One Socrates pass. Returns ``(content, analytics_dict)``. Raises
        ``AIServiceError('MOCK_MODE')`` when no client is configured.

        AI-HARD-5 (#28/#57): ``system_prompt`` already carries SOCRATES_PROMPT +
        the static context (injected ONCE). The student's turn is passed RAW as
        the ``user`` message — no ``CONTEXTO:/MENSAGEM DO ALUNO:`` wrapper — so it
        matches the role/content framing of the (pre-trimmed) history turns."""
        result = await self._call_openai(
            system_prompt,
            student_message,
            history=history,
            temperature=0.8,
        )
        self.track_token_usage(user_id, result["tokens"]["total"], db)
        content = result["content"]
        analytics = {
            "response_length": len(content),
            "processing_time_ms": result["elapsed_ms"],
            "model_used": result["model"],
            "tokens_used": result["tokens"],
        }
        return content, analytics

    async def _run_editor_tester_gate(
        self, *, socrates_content: str, system_prompt: str, student_message: str,
        history: List[Dict[str, str]], user_id: Optional[str], db,
    ) -> str:
        """Editor → Tester pedagogical gate (TPP-7).

        APPROVED/NEEDS_REVISION -> return the EDITED text. REJECTED -> regenerate
        the whole pass (Socrates → Editor → Tester) exactly ONCE, then return the
        best available reply regardless of the second verdict. Any exception in the
        gate degrades to the (raw or edited) reply and is logged — the student is
        never blocked, and the handler never sees a 5xx from the gate.
        """
        best = socrates_content
        try:
            edited = await self._edit_safe(socrates_content)
            best = edited
            verdict = await self._validate_safe(edited)

            if verdict == "REJECTED":
                # Regenerate ONCE: new Socrates pass -> Editor -> (best effort).
                try:
                    regen, _ = await self._generate_socratic_reply(
                        system_prompt=system_prompt, student_message=student_message,
                        history=history, user_id=user_id, db=db,
                    )
                    best = await self._edit_safe(regen)
                    # A second validate is informational only — we do NOT retry again.
                    await self._validate_safe(best)
                except AIServiceError as e:
                    if "MOCK_MODE" in str(e):
                        return best
                    logger.warning("TPP-7 regeneration failed: %s", e)
                    return best
            return best
        except AIServiceError as e:
            if "MOCK_MODE" in str(e):
                # No client: gate is a no-op, original reply stands.
                return best
            logger.warning("TPP-7 gate error (returning best available reply): %s", e)
            return best
        except Exception as e:  # pragma: no cover - defensive: never block the student
            logger.warning("TPP-7 gate unexpected error (returning best reply): %s", e)
            return best

    async def _edit_safe(self, text: str) -> str:
        """Editor pass returning the edited text; falls back to the input on failure."""
        out = await self.edit_response(orientador_response=text)
        return out.get("edited_text", text) or text

    async def _validate_safe(self, text: str) -> str:
        """Tester pass returning the verdict string. Never raises for non-MOCK
        errors (validate_response already fails-open to NEEDS_REVISION — TPP-7/#32)."""
        out = await self.validate_response(edited_response=text)
        return str(out.get("verdict", "NEEDS_REVISION")).upper()

    def _mock_socratic(self, msg: str, remaining: int) -> Dict[str, Any]:
        if remaining <= 1:
            content = (
                "Excelente jornada de reflexao! Voce demonstrou capacidade de analise "
                "critica e construcao de argumentos.\n\n"
                "Para encerrar: como voce resumiria o que aprendeu nessa conversa?"
            )
        else:
            content = (
                "Interessante sua perspectiva. Voce levanta um ponto importante.\n\n"
                "Agora, me diga: por que voce acha que isso funciona dessa forma? "
                "Existe alguma situacao em que essa logica nao se aplicaria?"
            )
        return {
            "response": {
                "content": content,
                "has_question": True,
                "is_final_interaction": remaining <= 1,
            },
            "session_status": {
                "interactions_remaining": max(0, remaining - 1),
                "should_finalize": remaining <= 1,
            },
            "analytics": {
                "response_length": len(content),
                "processing_time_ms": 50,
                "model_used": "mock",
                "tokens_used": {"prompt": 0, "completion": 0, "total": 0},
            },
            # AI-HARD-7 (#31): surface degraded state as an explicit top-level
            # contract instead of leaving it buried in ``analytics.model_used``.
            # The canned prompts ignore the student turn and the lesson, so the
            # caller (and the operator) must be able to tell the tutor is NOT
            # delivering real socratic value (API key missing/placeholder at
            # startup). ``socratic_dialogue`` re-mounts its own return, so it
            # re-injects these flags from here — see its MOCK_MODE branch.
            "degraded": True,
            "reason": "mock_mode_no_api_key",
        }

    # ------------------------------------------------------------------
    # 3. Analyst — AI detection
    # ------------------------------------------------------------------

    async def detect_ai_content(
        self,
        text: str,
        context: Optional[Dict[str, Any]] = None,
        interaction_metadata: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        db=None,
    ) -> Dict[str, Any]:
        # TKN-4 (bug #12): enforce the daily token budget BEFORE any paid call.
        # ``user_id``/``db`` DEFAULT to None (no-op without identity — TKN-3). The
        # check runs OUTSIDE the broad ``try/except Exception`` around ``_call_openai``
        # below, so an over-cap ``AIServiceError`` PROPAGATES to the route (→503)
        # instead of being swallowed into the heuristic fallback — no paid call,
        # no consumption when over-cap.
        self.check_token_budget(user_id, db)
        analysis_id = f"ANA-{int(time.time())}"
        words = text.split()
        sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]

        # AI-HARD-1 (bug #30) + AI-HARD-3 (#29): the LLM JSON is no longer read
        # verbatim. It is routed through the ``AIDetectionResult`` contract
        # (str->float coercion, clamp to [0,1], verdict/confidence enum
        # validation). On ANY failure to obtain a *valid* probability — LLM
        # error/mock, malformed JSON, missing/None ``probability``, out-of-enum
        # verdict/confidence, uncoercible type — we fall back HARD to the
        # heuristic. The benign ``0.3`` default is gone: a JSON that lacks
        # ``probability`` no longer fabricates a near-clean verdict.
        validated: Optional[AIDetectionResult] = None
        try:
            result = await self._call_openai(
                ANALYST_PROMPT,
                f"Analise o texto do aluno:\n\n{text}",
                json_mode=True,
            )
            # TKN-4 (bug #12): a REAL LLM call happened → persist consumption here,
            # BEFORE parsing. Track lives only on this real-call path; the heuristic
            # fallback (``except`` below) made no paid call, so it never tracks.
            # Best-effort; no-op without user_id/db (TKN-3).
            self.track_token_usage(user_id, result["tokens"]["total"], db)
            # _parse_model_json: bad JSON / contract violation -> None (the single
            # decision point; never raises). raw is the LLM string itself.
            validated = _parse_model_json(result["content"], AIDetectionResult)
            # Surface ``indicators`` (ignored by the strict contract) for the UI.
            try:
                raw_parsed = json.loads(result["content"])
            except (json.JSONDecodeError, TypeError):
                raw_parsed = {}
        except Exception:
            validated = None
            raw_parsed = {}

        if validated is not None:
            # ``probability`` is a clamped float in [0,1]; ``verdict``/``confidence``
            # are valid enum values. Comparisons/round below cannot TypeError.
            probability = float(validated.probability)
            confidence = validated.confidence.value
            verdict = validated.verdict.value
            parsed = {"indicators": raw_parsed.get("indicators", [])}
        else:
            # Hard fallback to the heuristic (NOT the old benign 0.3 default).
            detection = self._heuristic_ai_detection(text)
            probability = float(detection["probability"])
            confidence = detection["confidence"]
            verdict = detection["verdict"]
            parsed = detection

        flags = []
        if probability > 0.70:
            flags.append("alta_probabilidade_texto_IA")

        return {
            "analysis_id": analysis_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ai_detection": {
                "probability": round(probability, 2),
                "confidence": confidence,
                "verdict": verdict,
                "indicators": parsed.get("indicators", []),
                "flag": flags[0] if flags else None,
            },
            "metrics": {
                "text": {
                    "message_length_chars": len(text),
                    "message_length_words": len(words),
                    "sentence_count": len(sentences),
                    "has_question": "?" in text,
                },
            },
            "flags": flags,
            "observations": [],
            "recommendation": (
                "Revisao manual recomendada" if probability > 0.70 else "Texto parece autentico"
            ),
        }

    # AI-HARD-3: density-weighting tuning constants for the AI-phrase signal.
    #
    # Old scheme: +0.08 per *presence*, uncapped — 5 matches reached 0.70 and 6
    # tripped the >0.70 flag, so a formal essay was falsely flagged regardless of
    # length. New scheme scores the *density* of cliché matches (matches relative
    # to the number of words) and caps the aggregate contribution so that no set
    # of presence matches can, on its own, push a legitimate essay over 0.70.
    #
    # ``_AI_PHRASE_CAP = 0.30`` + the 0.30 base = 0.60 ceiling from phrases alone,
    # strictly below the 0.70 flag threshold. ``_AI_PHRASE_DENSITY_GAIN`` sets how
    # fast density approaches the cap: density = matches / words, contribution =
    # min(cap, density * gain). A short cliché-dense text saturates the cap; a
    # long essay where the same matches are sparse stays well under it — so a
    # dense text always scores strictly higher than a same-size text with fewer
    # clichés, and higher than a longer text with the same match count.
    _AI_PHRASE_CAP = 0.30
    _AI_PHRASE_DENSITY_GAIN = 4.0

    def _heuristic_ai_detection(self, text: str) -> Dict[str, Any]:
        lower = text.lower()
        score = 0.3
        indicators = []

        # --- AI-phrase signal: density-weighted with a hard cap -------------
        word_count = max(len(text.split()), 1)
        ai_matches = 0
        for phrase in AI_PHRASES:
            if phrase in lower:
                ai_matches += 1
                indicators.append({
                    "type": "ai_phrase",
                    "description": f"Frase tipica de IA: '{phrase}'",
                    # Per-phrase weight is informational only; the score uses the
                    # aggregate density contribution below, not this value.
                    "weight": None,
                })

        # Contribution grows with cliché density (matches per word) and is
        # bounded by ``_AI_PHRASE_CAP`` so presence alone cannot reach the flag.
        ai_density = ai_matches / word_count
        ai_contribution = min(self._AI_PHRASE_CAP, ai_density * self._AI_PHRASE_DENSITY_GAIN)
        score += ai_contribution

        for marker in HUMAN_INDICATORS:
            if marker in lower:
                score -= 0.06
                indicators.append({
                    "type": "human_marker",
                    "description": f"Indicador humano: '{marker}'",
                    "weight": -0.06,
                })

        if len(text) > 1500:
            score += 0.05
        if len(text) < 100:
            score -= 0.10

        score = max(0.0, min(1.0, score))

        if score < 0.35:
            verdict, confidence = "likely_human", "medium"
        elif score < 0.65:
            verdict, confidence = "uncertain", "low"
        else:
            verdict, confidence = "likely_ai", "high"

        return {
            "probability": round(score, 2),
            "confidence": confidence,
            "verdict": verdict,
            "indicators": indicators,
        }

    # ------------------------------------------------------------------
    # 4. Editor — response refinement
    # ------------------------------------------------------------------

    async def edit_response(
        self,
        orientador_response: str,
        context: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        db=None,
    ) -> Dict[str, Any]:
        # TKN-4 (bug #12): enforce the daily token budget from PERSISTED usage
        # BEFORE any paid model call. ``user_id``/``db`` DEFAULT to None because the
        # socratic gate calls this method internally (``_edit_safe``) WITHOUT an
        # identity — in that path check/track are no-ops (TKN-3 guards), and the
        # gate behaviour is unchanged. When the route supplies the authenticated
        # identity, an over-cap user raises ``AIServiceError`` here (mapped to 503
        # at the edge) and NO paid call to the model is made.
        self.check_token_budget(user_id, db)
        try:
            result = await self._call_openai(
                EDITOR_PROMPT,
                f"Texto do orientador para editar:\n\n{orientador_response}",
                temperature=0.5,
            )
            # Real LLM call succeeded → persist consumption for the authenticated
            # user (best-effort; no-op without user_id/db — TKN-3).
            self.track_token_usage(user_id, result["tokens"]["total"], db)
            return {
                "edited_text": result["content"],
                "word_count": len(result["content"].split()),
                "paragraph_count": result["content"].count("\n\n") + 1,
                "ends_with_question": result["content"].rstrip().endswith("?"),
                "processing_time_ms": result["elapsed_ms"],
                "model_used": result["model"],
                "tokens_used": result["tokens"],
            }
        except AIServiceError as e:
            if "MOCK_MODE" in str(e):
                # AI-HARD-7 (#31): the orientador text is returned UNEDITED here.
                # Surface that explicitly with top-level ``mock``/``degraded`` +
                # ``reason`` (instead of only ``model_used="mock"`` buried in the
                # payload), and WARN at serve time. ``edited_text`` is unchanged —
                # now flagged as not-actually-edited rather than impersonating an
                # editor pass. The success path above never sets these flags.
                logger.warning(
                    "edit_response: serving DEGRADED reply (reason=%s) — "
                    "orientador text returned unedited (mock mode).",
                    "mock_mode_no_api_key",
                )
                return {
                    "edited_text": orientador_response,
                    "word_count": len(orientador_response.split()),
                    "paragraph_count": orientador_response.count("\n\n") + 1,
                    "ends_with_question": orientador_response.rstrip().endswith("?"),
                    "processing_time_ms": 30,
                    "model_used": "mock",
                    "tokens_used": {"prompt": 0, "completion": 0, "total": 0},
                    "mock": True,
                    "degraded": True,
                    "reason": "mock_mode_no_api_key",
                }
            raise

    # ------------------------------------------------------------------
    # 5. Tester — quality validation
    # ------------------------------------------------------------------

    async def validate_response(
        self,
        edited_response: str,
        context: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        db=None,
    ) -> Dict[str, Any]:
        # TKN-4 (bug #12): enforce the daily token budget BEFORE the paid call.
        # ``user_id``/``db`` DEFAULT to None so the socratic gate's internal call
        # (``_validate_safe``, no identity) stays a no-op and the fail-open
        # contract below is unchanged. The check is placed OUTSIDE the ``try`` on
        # purpose: an over-cap ``AIServiceError`` must PROPAGATE to the route (→503),
        # NOT be caught by the honest fail-open ``except AIServiceError`` below and
        # silently degraded to an UNKNOWN verdict. No paid call happens over-cap.
        self.check_token_budget(user_id, db)
        try:
            result = await self._call_openai(
                TESTER_PROMPT,
                f"Valide a resposta editada:\n\n{edited_response}",
                json_mode=True,
            )
            # Real LLM call succeeded → persist consumption (best-effort; no-op
            # without user_id/db — TKN-3). Tracked here, on the REAL success path
            # only, never in the fail-open/mock branches below.
            self.track_token_usage(user_id, result["tokens"]["total"], db)
            # AI-HARD-2 (bug #32): the LLM JSON is NO LONGER trusted verbatim. It is
            # routed through the ``TesterVerdict`` contract (verdict enum, optional
            # coerced/clamped score). ``_parse_model_json`` is the single decision
            # point — it returns ``None`` on malformed JSON *or* a contract
            # violation (missing/None ``verdict``, out-of-enum value), never raising.
            # An ``APPROVED`` can therefore ONLY surface from a well-formed payload
            # that actually carries that verdict. A syntactically valid JSON that
            # lacks ``verdict`` (or violates the enum) yields ``None`` here and falls
            # through to NEEDS_REVISION below — it can never fail open to APPROVED.
            validated: Optional[TesterVerdict] = _parse_model_json(
                result["content"], TesterVerdict
            )
            if validated is not None:
                # Re-surface the rich LLM payload (e.g. ``criteria``, ignored by the
                # strict contract) while letting the validated ``verdict``/``score``
                # be the source of truth for the fields the gate keys on.
                try:
                    raw_parsed = json.loads(result["content"])
                except (json.JSONDecodeError, TypeError):
                    raw_parsed = {}
                if not isinstance(raw_parsed, dict):
                    raw_parsed = {}
                raw_parsed["verdict"] = validated.verdict.value
                raw_parsed["score"] = validated.score
                return raw_parsed
            # Well-formed-but-invalid payload (missing ``verdict`` / out-of-enum /
            # malformed JSON the model answered with). Fail CLOSED to NEEDS_REVISION
            # — never the fabricated APPROVED of old. Log at ERROR with the root
            # cause so a silently-degrading Tester is observable.
            logger.error(
                "validate_response: Tester payload failed the TesterVerdict contract "
                "(malformed JSON or missing/invalid 'verdict') — verdict NEEDS_REVISION (degraded)."
            )
            return {
                "verdict": "NEEDS_REVISION",
                "score": None,
                "criteria": {},
                "degraded": True,
                "reason": "malformed_json",
            }
        except AIServiceError as e:
            if self.mock_mode and "MOCK_MODE" in str(e):
                # Legitimate canned fallback when NO client is configured (startup
                # mock mode, AI-HARD-0). ``mock: true`` lets the consumer tell a stub
                # verdict apart from a real one. This branch is gated on
                # ``self.mock_mode`` so a runtime quota/limit ``AIServiceError`` (raised
                # by check_token_budget on a real client) does NOT masquerade as a
                # benign mock APPROVED — it falls through to the transport path below.
                criteria = {}
                for c in ("pedagogical", "structural", "clarity", "engagement", "originality", "inclusivity"):
                    criteria[c] = {"pass": True, "score": 0.85}
                return {"verdict": "APPROVED", "score": 0.85, "criteria": criteria, "mock": True}
            # Transport/runtime failure of a REAL call (non-mock ``AIServiceError`` —
            # e.g. token budget exceeded). Fail CLOSED but HONEST (TPP-7 / #32): never
            # fabricate APPROVED. The gate treats a non-APPROVED verdict as "don't
            # block the student", so the edited reply still ships, but we don't lie
            # about the validation having passed.
            logger.error("validate_response transport error (AIServiceError) — verdict UNKNOWN (degraded): %s", e)
            return {
                "verdict": "UNKNOWN",
                "score": None,
                "criteria": {},
                "error": "validation_unavailable",
                "degraded": True,
                "reason": "transport_error",
            }
        except Exception as e:
            # Any other transport/runtime failure (OpenAI/network/timeout/unexpected).
            # Same honest fail-closed: UNKNOWN, never APPROVED, logged at ERROR with
            # the root cause.
            logger.error("validate_response transport error — verdict UNKNOWN (degraded): %s", e)
            return {
                "verdict": "UNKNOWN",
                "score": None,
                "criteria": {},
                "error": "validation_unavailable",
                "degraded": True,
                "reason": "transport_error",
            }

    # ------------------------------------------------------------------
    # 6. Organizer — session management
    # ------------------------------------------------------------------

    async def organize_session(
        self,
        action: str,
        payload: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        t0 = time.time()
        result: Dict[str, Any] = {}

        if action == "get_session_status":
            result = {"status": payload.get("status", "active"), "messages": payload.get("total_messages", 0)}
        elif action == "validate_export_payload":
            required = {"session_id", "user_id"}
            missing = required - set(payload.keys())
            result = {"valid": len(missing) == 0, "missing_fields": list(missing)}
        else:
            result = {"message": f"Acao '{action}' nao reconhecida"}

        elapsed = int((time.time() - t0) * 1000)
        return {
            "success": True,
            "action": action,
            "result": result,
            "metadata": {"timestamp": datetime.now(timezone.utc).isoformat(), "duration_ms": elapsed},
        }

    def prepare_moodle_export(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        messages = session_data.get("messages", [])
        student_words = sum(
            len(m.get("content", "").split())
            for m in messages
            if m.get("role") == "user"
        )

        # INT-MOODLE-1: started_at is derived from the real session, never
        # fabricated. ``started_at`` wins when present; ``created_at`` is the
        # fallback (chat_sessions has no dedicated started_at column today, so
        # every caller effectively falls back to created_at — that is honest,
        # not a placeholder).
        started_at = session_data.get("started_at") or session_data.get("created_at")

        # score.raw must distinguish "no score computed yet" (None/null) from a
        # legitimate score of 0. ``performance_score`` (DATA-GAM-3) is the real,
        # persisted signal — a truthy check would wrongly collapse a real 0 into
        # the same bucket as "no data", so the check is explicit `is None`.
        performance_score = session_data.get("performance_score")
        if performance_score is None:
            performance_score = session_data.get("score")  # legacy/manual override, if provided
        score_raw = performance_score if performance_score is not None else None

        result: Dict[str, Any] = {
            "export_id": f"HARVEN-MOODLE-{uuid4().hex[:8]}",
            "actor": {
                "name": session_data.get("user_name", ""),
                "mbox": f"mailto:{session_data.get('user_email', '')}",
            },
            "context": {
                "course": {"id": session_data.get("course_id"), "title": session_data.get("course_title")},
                "chapter": {"id": session_data.get("chapter_id"), "title": session_data.get("chapter_title")},
                "content": {"id": session_data.get("content_id"), "title": session_data.get("content_title")},
            },
            "session": {
                "id": session_data.get("session_id"),
                "started_at": started_at,
                "total_messages": len(messages),
            },
            "interactions": [
                {
                    "role": m.get("role"),
                    "content": m.get("content"),
                    "agent_type": m.get("agent_type"),
                    "timestamp": m.get("created_at"),
                }
                for m in messages
            ],
            "result": {
                "success": True,
                "completion": session_data.get("status") == "completed",
                "score": {"raw": score_raw, "max": 100, "min": 0},
            },
            "verb": {"id": "http://adlnet.gov/expapi/verbs/experienced"},
            "metrics": {
                "total_words_student": student_words,
            },
        }

        # AI-detection metrics are only emitted when a real, persisted detection
        # result is available on the session — never as fabricated 0.0/[] filler
        # implying "no AI suspicion" when no analysis was actually run.
        ai_detection = session_data.get("ai_detection")
        if isinstance(ai_detection, dict):
            if ai_detection.get("avg_ai_probability") is not None:
                result["metrics"]["avg_ai_probability"] = ai_detection["avg_ai_probability"]
            if ai_detection.get("flags_triggered") is not None:
                result["metrics"]["flags_triggered"] = ai_detection["flags_triggered"]

        return result

    # ------------------------------------------------------------------
    # 7. Podcast — conversational script from the full chapter body (POD-1)
    # ------------------------------------------------------------------

    def generate_podcast_script(self, body_html: str, chapter_title: str = "") -> str:
        """Roteiriza o CORPO COMPLETO de um capitulo em um script de podcast.

        POD-1 (bug #8): fixes the branch where ``audio_type='podcast'`` fell
        through to the summary/explanation path (a short clip narrating a
        3-paragraph summary instead of the full chapter). This method is the
        dedicated podcast source-of-script: it strips the chapter's HTML
        ``body`` to plain text and produces a conversational, single-narrator
        script covering the ENTIRE source material (Article IV — no invented
        content beyond it), targeting ``PODCAST_MIN_WORDS`` (~10 min).

        SYNCHRONOUS on purpose, mirroring the summary/explanation LLM calls
        already made in ``_run_tts_job`` (``routes_ai.py``): that job runs in
        a ``threading.Thread`` OFF the event loop, so it must use
        ``self.sync_client`` (never ``self.client``, which is ``AsyncOpenAI``
        and would silently return an unawaited coroutine there — the exact
        failure mode ASYNC-AI-1 already guards against for summary/
        explanation). Callers on the async request path should wrap this in
        ``run_in_threadpool`` rather than adding a parallel async client call.

        For chapters whose stripped body exceeds
        ``PODCAST_SECTION_SUMMARY_THRESHOLD_CHARS``, the body is first
        summarized section-by-section (splitting on paragraph-ish
        boundaries via ``chunk_text``) and the summaries are then roteirized
        together — this keeps a very long chapter from being silently
        head-truncated into the roteirizer prompt while still covering
        100% of the source (each section contributes to the script, none
        are skipped).

        Falls back to the (HTML-stripped) body itself when no client is
        configured (mock mode) or the LLM call fails — the caller always
        gets *something* narratable, never an exception surfaced mid-job.
        """
        plain_body = strip_html(body_html)
        if not plain_body:
            return ""

        if not self.sync_client:
            # Mock mode / no client configured — the plain (stripped) body is
            # itself a valid (if non-conversational) narration source so the
            # podcast job still reaches 'done' instead of failing hard.
            return plain_body

        try:
            source_material = self._prepare_podcast_source(plain_body)
            user_msg = (
                f"Titulo do capitulo: {chapter_title or 'Capitulo'}\n\n"
                f"Conteudo completo a roteirizar:\n\n{source_material}\n\n"
                f"Gere o roteiro de narracao conversacional completo agora, cobrindo "
                f"TODO o conteudo acima, com pelo menos {PODCAST_MIN_WORDS} palavras "
                f"quando o material permitir."
            )
            result = self.sync_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": PODCAST_SCRIPT_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=4000,
                temperature=0.6,
            )
            script = (result.choices[0].message.content or "").strip()
            return script or plain_body
        except Exception as e:
            logger.error(
                "generate_podcast_script: roteirizacao falhou, usando corpo "
                "puro (HTML-stripped) como fallback: %s", e, exc_info=True,
            )
            return plain_body

    def _prepare_podcast_source(self, plain_body: str) -> str:
        """Return the material handed to the podcast roteirizer prompt.

        Below ``PODCAST_SECTION_SUMMARY_THRESHOLD_CHARS`` the full stripped
        body is passed through untouched. Above it, the body is split into
        ``chunk_text``-derived sections and EACH section is summarized by the
        model, then the summaries are concatenated — so the roteirizer still
        sees the entirety of the chapter's content (just condensed), never a
        silently truncated head. Any per-section summarization failure falls
        back to including that section's own (unsummarized) text, so a single
        LLM hiccup never drops content from the final script.
        """
        if len(plain_body) <= PODCAST_SECTION_SUMMARY_THRESHOLD_CHARS:
            return plain_body

        sections = chunk_text(plain_body, max_chars=PODCAST_SECTION_CHUNK_CHARS)
        summarized_sections: List[str] = []
        for section in sections:
            try:
                result = self.sync_client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Resuma o trecho abaixo preservando todos os "
                                "conceitos e fatos importantes, em portugues, "
                                "de forma densa e factual (sem estilo de "
                                "podcast ainda — este e um resumo intermediario)."
                            ),
                        },
                        {"role": "user", "content": section},
                    ],
                    max_tokens=1200,
                    temperature=0.3,
                )
                summary = (result.choices[0].message.content or "").strip()
                summarized_sections.append(summary or section)
            except Exception as e:
                logger.warning(
                    "generate_podcast_script: falha ao resumir secao "
                    "(%d chars), usando texto original da secao: %s",
                    len(section), e,
                )
                summarized_sections.append(section)

        return "\n\n".join(summarized_sections)

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def estimate_cost(self, prompt_tokens: int = 0, completion_tokens: int = 0, model: str = "") -> float:
        m = model or self.model
        pricing = MODEL_PRICING.get(m, MODEL_PRICING["gpt-4o-mini"])
        return round(
            (prompt_tokens / 1_000_000) * pricing["input"]
            + (completion_tokens / 1_000_000) * pricing["output"],
            6,
        )


def sanitize_ai_error(error: Exception) -> str:
    msg = str(error)
    msg = re.sub(r"sk-[a-zA-Z0-9]{20,}", "[API_KEY_REDACTED]", msg)
    msg = re.sub(r"org-[a-zA-Z0-9]+", "[ORG_REDACTED]", msg)
    if len(msg) > 300:
        msg = msg[:300] + "..."
    return msg
