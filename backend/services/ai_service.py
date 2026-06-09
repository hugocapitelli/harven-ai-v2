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
    pass  # No DB type needed — token tracking uses in-memory cache

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
MAX_INTERACTIONS = 20

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

_user_token_cache: Dict[str, Dict[str, int]] = {}


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
        if not user_id:
            return
        today = date.today().isoformat()
        used = _user_token_cache.get(user_id, {}).get(today, 0)

        if used >= self.daily_token_limit:
            raise AIServiceError("Limite diario de tokens excedido. Tente novamente amanha.")

    def track_token_usage(self, user_id: Optional[str], tokens: int, db=None) -> None:
        if not user_id or tokens <= 0:
            return
        today = date.today().isoformat()
        _user_token_cache.setdefault(user_id, {})
        _user_token_cache[user_id][today] = _user_token_cache[user_id].get(today, 0) + tokens

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

        ``remaining = MAX - used`` (clamped >= 0); ``should_finalize`` once the
        current turn is the last permitted one (``used >= MAX - 1``).
        """
        remaining = max(0, MAX_INTERACTIONS - used)
        should_finalize = used >= (MAX_INTERACTIONS - 1)
        return {"remaining": remaining, "should_finalize": should_finalize}

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
    ) -> Dict[str, Any]:
        self.check_token_budget(user_id, db)

        iq = self._normalize_initial_question(initial_question)
        is_init = student_message == "__INIT__"

        # --- TPP-4: persist the student turn server-side (backend = source of
        # truth). Only when a real session + db are present; the __INIT__ pseudo
        # message is NOT a real student turn and is never persisted. ---
        repo = None
        if session_id and db is not None:
            try:
                repo = ChatRepository(db)
                if not is_init:
                    await run_in_threadpool(
                        repo.persist_turn,
                        session_id,
                        {"role": "user", "content": student_message, "agent_type": None,
                         "metadata": None},
                    )
            except Exception as exc:  # pragma: no cover - persistence is best-effort
                logger.warning("socratic_dialogue: student-turn persist failed (%s): %s",
                               session_id, exc)
                repo = repo  # keep repo for the read below if it still works

        # --- TPP-5: derive pacing from the PERSISTED user-message count when a
        # session exists; otherwise fall back to the client-supplied value
        # (ephemeral/no-session path, e.g. the concurrency suite). ---
        if repo is not None and session_id:
            try:
                used = await run_in_threadpool(repo.count_user_messages, session_id)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("socratic_dialogue: count_user_messages failed (%s): %s",
                               session_id, exc)
                used = max(0, MAX_INTERACTIONS - interactions_remaining)
            pacing = self._derive_pacing(used)
            remaining = pacing["remaining"]
            should_finalize = pacing["should_finalize"]
        else:
            # No persisted session: degrade to the legacy contract deterministically.
            remaining = max(0, interactions_remaining - 1)
            should_finalize = interactions_remaining <= 1

        context = (
            f"Pergunta em discussao: {iq.get('text', '')}\n"
            f"Resposta esperada: {iq.get('expected_answer') or 'nao especificada'}\n"
            f"Interacoes restantes: {remaining}\n\n"
            f"Conteudo de referencia:\n{chapter_content[:4000]}"
        )

        user_msg = (
            "Apresente-se brevemente e faca a primeira pergunta socratica."
            if is_init
            else student_message
        )
        history = conversation_history or []

        try:
            content, analytics = await self._generate_socratic_reply(
                context=context, user_msg=user_msg, history=history,
                user_id=user_id, db=db,
            )
        except AIServiceError as e:
            if "MOCK_MODE" in str(e):
                # Mock path: keep the persisted-pacing semantics. ``remaining`` is the
                # post-turn count; treat ``should_finalize`` as the closing trigger.
                mock = self._mock_socratic(
                    student_message,
                    1 if should_finalize else max(2, remaining),
                    is_init,
                )
                content = mock["response"]["content"]
                analytics = mock["analytics"]
            else:
                raise

        # --- TPP-7: optional Editor→Tester quality gate (default OFF). On any gate
        # failure we keep the best available reply (never block / never 5xx). ---
        if _editor_tester_gate_enabled():
            content = await self._run_editor_tester_gate(
                socrates_content=content, context=context, user_msg=user_msg,
                history=history, user_id=user_id, db=db,
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

        return {
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

    async def _generate_socratic_reply(
        self, *, context: str, user_msg: str, history: List[Dict[str, str]],
        user_id: Optional[str], db,
    ) -> tuple:
        """One Socrates pass. Returns ``(content, analytics_dict)``. Raises
        ``AIServiceError('MOCK_MODE')`` when no client is configured."""
        result = await self._call_openai(
            SOCRATES_PROMPT,
            f"CONTEXTO:\n{context}\n\nMENSAGEM DO ALUNO:\n{user_msg}",
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
        self, *, socrates_content: str, context: str, user_msg: str,
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
                        context=context, user_msg=user_msg, history=history,
                        user_id=user_id, db=db,
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

    def _mock_socratic(self, msg: str, remaining: int, is_init: bool) -> Dict[str, Any]:
        if is_init:
            content = (
                "Ola! Sou seu orientador socratico. Estou aqui para te ajudar a explorar "
                "esse tema atraves de perguntas.\n\n"
                "Para comecar: o que voce ja sabe sobre esse assunto? "
                "Qual aspecto mais chama sua atencao?"
            )
        elif remaining <= 1:
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
        }

    # ------------------------------------------------------------------
    # 3. Analyst — AI detection
    # ------------------------------------------------------------------

    async def detect_ai_content(
        self,
        text: str,
        context: Optional[Dict[str, Any]] = None,
        interaction_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
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
    ) -> Dict[str, Any]:
        try:
            result = await self._call_openai(
                EDITOR_PROMPT,
                f"Texto do orientador para editar:\n\n{orientador_response}",
                temperature=0.5,
            )
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
                return {
                    "edited_text": orientador_response,
                    "word_count": len(orientador_response.split()),
                    "paragraph_count": orientador_response.count("\n\n") + 1,
                    "ends_with_question": orientador_response.rstrip().endswith("?"),
                    "processing_time_ms": 30,
                    "model_used": "mock",
                    "tokens_used": {"prompt": 0, "completion": 0, "total": 0},
                }
            raise

    # ------------------------------------------------------------------
    # 5. Tester — quality validation
    # ------------------------------------------------------------------

    async def validate_response(
        self,
        edited_response: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        try:
            result = await self._call_openai(
                TESTER_PROMPT,
                f"Valide a resposta editada:\n\n{edited_response}",
                json_mode=True,
            )
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

        return {
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
                "started_at": session_data.get("started_at"),
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
                "score": {"raw": session_data.get("score", 0), "max": 100, "min": 0},
            },
            "verb": {"id": "http://adlnet.gov/expapi/verbs/experienced"},
            "metrics": {
                "total_words_student": student_words,
                "avg_ai_probability": 0.0,
                "flags_triggered": [],
            },
        }

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
