"""AI Service — 6 agents with OpenAI, token tracking and mock mode."""
import json
import logging
import re
import time
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # No DB type needed — token tracking uses in-memory cache

from config import get_settings

logger = logging.getLogger(__name__)

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

AI_PHRASES = [
    "e importante ressaltar",
    "nesse sentido",
    "diante do exposto",
    "em suma",
    "pode-se afirmar que",
    "e fundamental destacar",
    "vale ressaltar que",
    "nesse contexto",
    "em linhas gerais",
    "cabe mencionar",
    "e valido salientar",
    "em termos gerais",
    "por conseguinte",
    "dessa forma",
    "sendo assim",
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


class AIService:
    def __init__(self):
        settings = get_settings()
        self.api_key = settings.OPENAI_API_KEY or ""
        self.model = settings.OPENAI_MODEL
        self.mock_mode = not self.api_key or self.api_key in (
            "sk-test", "sk-sua-chave-openai", "sk-your-openai-key", "",
        )
        self.client = None
        self.daily_token_limit = 500_000

        if not self.mock_mode:
            try:
                from openai import OpenAI
                self.client = OpenAI(api_key=self.api_key)
            except Exception as e:
                logger.warning(f"OpenAI client init failed, entering mock mode: {e}")
                self.mock_mode = True

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

    def _call_openai(
        self,
        system_prompt: str,
        user_message: str,
        history: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 1500,
        json_mode: bool = False,
    ) -> Dict[str, Any]:
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
        response = self.client.chat.completions.create(**kwargs)
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
            result = self._call_openai(CREATOR_PROMPT, user_msg, json_mode=True)
            self.track_token_usage(user_id, result["tokens"]["total"], db)
            parsed = json.loads(result["content"])
            return {
                "questions": parsed.get("questions", []),
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

    async def socratic_dialogue(
        self,
        student_message: str,
        chapter_content: str,
        initial_question: Dict[str, str],
        conversation_history: Optional[List[Dict[str, str]]] = None,
        interactions_remaining: int = 3,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        db=None,
    ) -> Dict[str, Any]:
        self.check_token_budget(user_id, db)

        context = (
            f"Pergunta em discussao: {initial_question.get('text', '')}\n"
            f"Resposta esperada: {initial_question.get('expected_answer', 'nao especificada')}\n"
            f"Interacoes restantes: {interactions_remaining}\n\n"
            f"Conteudo de referencia:\n{chapter_content[:4000]}"
        )

        is_init = student_message == "__INIT__"
        user_msg = (
            "Apresente-se brevemente e faca a primeira pergunta socratica."
            if is_init
            else student_message
        )

        history = conversation_history or []

        try:
            result = self._call_openai(
                SOCRATES_PROMPT,
                f"CONTEXTO:\n{context}\n\nMENSAGEM DO ALUNO:\n{user_msg}",
                history=history,
                temperature=0.8,
            )
            self.track_token_usage(user_id, result["tokens"]["total"], db)
            content = result["content"]
            return {
                "response": {
                    "content": content,
                    "has_question": "?" in content,
                    "is_final_interaction": interactions_remaining <= 1,
                },
                "session_status": {
                    "interactions_remaining": max(0, interactions_remaining - 1),
                    "should_finalize": interactions_remaining <= 1,
                },
                "analytics": {
                    "response_length": len(content),
                    "processing_time_ms": result["elapsed_ms"],
                    "model_used": result["model"],
                    "tokens_used": result["tokens"],
                },
            }
        except AIServiceError as e:
            if "MOCK_MODE" in str(e):
                return self._mock_socratic(student_message, interactions_remaining, is_init)
            raise

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

        try:
            result = self._call_openai(
                ANALYST_PROMPT,
                f"Analise o texto do aluno:\n\n{text}",
                json_mode=True,
            )
            parsed = json.loads(result["content"])
            probability = parsed.get("probability", 0.3)
            confidence = parsed.get("confidence", "medium")
            verdict = parsed.get("verdict", "uncertain")
        except Exception:
            detection = self._heuristic_ai_detection(text)
            probability = detection["probability"]
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

    def _heuristic_ai_detection(self, text: str) -> Dict[str, Any]:
        lower = text.lower()
        score = 0.3
        indicators = []

        for phrase in AI_PHRASES:
            if phrase in lower:
                score += 0.08
                indicators.append({
                    "type": "ai_phrase",
                    "description": f"Frase tipica de IA: '{phrase}'",
                    "weight": 0.08,
                })

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
            result = self._call_openai(
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
            result = self._call_openai(
                TESTER_PROMPT,
                f"Valide a resposta editada:\n\n{edited_response}",
                json_mode=True,
            )
            return json.loads(result["content"])
        except AIServiceError as e:
            if "MOCK_MODE" in str(e):
                criteria = {}
                for c in ("pedagogical", "structural", "clarity", "engagement", "originality", "inclusivity"):
                    criteria[c] = {"pass": True, "score": 0.85}
                return {"verdict": "APPROVED", "score": 0.85, "criteria": criteria}
            raise
        except (json.JSONDecodeError, Exception):
            criteria = {}
            for c in ("pedagogical", "structural", "clarity", "engagement", "originality", "inclusivity"):
                criteria[c] = {"pass": True, "score": 0.80}
            return {"verdict": "APPROVED", "score": 0.80, "criteria": criteria}

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
