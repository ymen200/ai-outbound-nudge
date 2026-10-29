import google.generativeai as genai
import time
from typing import Optional, Dict, Any, List
import json
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception
from .config import settings
from .models import (
    Signal, Strategy, Personality, CompanyDetails,
    SelectedOffer, Channel, Intent, Stage
)
from .observability import prompt_store, PromptRecord, get_runtime_config
from .middleware.token_counter import TokenCounter

class LLMService:
    """Service for interacting with Google Gemini API"""

    def __init__(self):
        genai.configure(api_key=settings.GOOGLE_API_KEY)
        model_config = {
            "temperature": settings.GEMINI_TEMPERATURE,
            "max_output_tokens": settings.GEMINI_MAX_TOKENS,
        }
        self.model = genai.GenerativeModel(
            model_name=settings.GEMINI_MODEL,
            generation_config=model_config
        )
        self.fallback_model = genai.GenerativeModel(
            model_name=settings.GEMINI_FALLBACK_MODEL,
            generation_config=model_config
        )
        self._token_counter = TokenCounter()
        self._start_time = time.time()

    def _is_rate_limit_error(self, exc: Exception) -> bool:
        """Detect 429 / quota errors from Gemini"""
        msg = str(exc).lower()
        return "429" in msg or "quota" in msg or "resource_exhausted" in msg

    @retry(
        retry=retry_if_exception(lambda e: "429" in str(e) or "quota" in str(e).lower() or "resource_exhausted" in str(e).lower()),
        wait=wait_exponential(multiplier=1, min=20, max=120),
        stop=stop_after_attempt(4),
        reraise=True
    )
    def _call_llm(self, prompt: str, system_instruction: Optional[str] = None, agent_step: str = "unknown") -> str:
        """Call primary model, fall back to fallback_model on any error.
        
        Records every call (prompt, response, tokens, latency) in the PromptStore
        for observability by the Outreach Orchestrator / global orchestrator.
        """
        full_prompt = f"{system_instruction}\n\n{prompt}" if system_instruction else prompt
        call_start = time.time()
        model_used = "primary"
        response_text = None
        error_msg = None
        success = True
        try:
            response = self.model.generate_content(full_prompt)
            response_text = response.text
            # ── Record actual provider token usage ──
            # SDK v0.3.2: output tokens not reliably on candidates[0].token_count,
            # so estimate from text length (~4 chars/token for English).
            tokens_out = len(response_text) // 4 if response_text else 0
            tokens_in = len(full_prompt) // 4
            latency_ms = (time.time() - call_start) * 1000
            prompt_store.record(PromptRecord(
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                module="message_generator",
                agent_step=agent_step,
                prompt=full_prompt,
                system_instruction=system_instruction,
                response=response_text,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                model_used=model_used,
                latency_ms=round(latency_ms, 2),
                success=True,
            ))
            return response_text
        except Exception as primary_err:
            model_used = "fallback"
            try:
                response = self.fallback_model.generate_content(full_prompt)
                response_text = response.text
                # ── Record actual provider token usage ──
                tokens_out = len(response_text) // 4 if response_text else 0
                tokens_in = len(full_prompt) // 4
                latency_ms = (time.time() - call_start) * 1000
                prompt_store.record(PromptRecord(
                    timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    module="message_generator",
                    agent_step=agent_step,
                    prompt=full_prompt,
                    system_instruction=system_instruction,
                    response=response_text,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    model_used=model_used,
                    latency_ms=round(latency_ms, 2),
                    success=True,
                ))
                return response_text
            except Exception as fallback_err:
                success = False
                error_msg = f"Both models failed. Primary: {primary_err} | Fallback: {fallback_err}"
                raise Exception(error_msg)

    def _parse_json(self, raw: str) -> dict:
        """
        Uses json5 to parse potentially sloppy JSON from the LLM.
        json5 is much more tolerant of syntax errors like trailing commas,
        unquoted keys, single quotes, etc.
        """
        import json5  # Import it here

        # 1. Strip markdown fences and whitespace
        cleaned = raw.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        
        # 2. Attempt to parse with the more lenient json5 library
        try:
            return json5.loads(cleaned)
        except Exception as e:
            # If even json5 fails, we have a major problem.
            raise ValueError(
                f"Failed to parse LLM response even with json5. Error: {str(e)}. Raw response: <<< {raw} >>>"
            )

    def _build_personality_block(self, personality: Personality, stage: Stage) -> str:
        """Convert personality config into a plain English instruction block for the LLM"""
        stage_override = personality.stage_instructions.get(stage.value, "")
        lines = [f"BASE STYLE: {personality.base_template.value}"]
        if personality.custom_template_description: lines.append(f"CUSTOM STYLE DESCRIPTION: {personality.custom_template_description}")
        if personality.personality_traits: lines.append(f"PERSONALITY TRAITS: {', '.join(personality.personality_traits)}")
        if personality.always_include_phrases: lines.append(f"MUST INCLUDE THESE PHRASES (use naturally): {', '.join(personality.always_include_phrases)}")
        if personality.never_use_phrases: lines.append(f"NEVER USE THESE PHRASES: {', '.join(personality.never_use_phrases)}")
        lines.append(f"TOUCHDOWNS PER MESSAGE: Hit exactly {personality.touchdowns_per_message} distinct value or hook points")
        if personality.enabled_hook_types: lines.append(f"ALLOWED HOOK TYPES: {', '.join(personality.enabled_hook_types)}")
        lines.append(f"URGENCY LEVEL: {personality.urgency_level}/10 (1=no urgency, 10=extremely urgent)")
        lines.append(f"SELF DEPRECATION: {personality.self_deprecation}/10 (1=none, 10=a lot)")
        lines.append(f"HUMOR/SARCASM: {personality.humor_sarcasm}/10 (1=very serious, 10=very funny)")
        if stage_override: lines.append(f"STAGE SPECIFIC INSTRUCTION: {stage_override}")
        return "\n".join(lines)

    def _build_company_block(self, company: CompanyDetails) -> str:
        """Convert company details into a plain English block"""
        lines = [f"SENDER COMPANY: {company.company_name}"]
        if company.website: lines.append(f"WEBSITE: {company.website}")
        if company.industry: lines.append(f"INDUSTRY: {company.industry}")
        if company.elevator_pitch: lines.append(f"ELEVATOR PITCH: {company.elevator_pitch}")
        if company.value_props: lines.append(f"VALUE PROPS:\n" + "\n".join(f"  - {v}" for v in company.value_props))
        if company.social_proof: lines.append(f"SOCIAL PROOF:\n" + "\n".join(f"  - {s}" for s in company.social_proof))
        return "\n".join(lines)

    def _build_offer_block(self, offer: SelectedOffer) -> str:
        """Convert selected offer into a plain English block"""
        lines = [f"OFFER: {offer.offer_name}"]
        if offer.pain_points: lines.append(f"PAIN POINTS IT SOLVES:\n" + "\n".join(f"  - {p}" for p in offer.pain_points))
        if offer.solution_summary: lines.append(f"SOLUTION SUMMARY: {offer.solution_summary}")
        if offer.proof_points: lines.append(f"PROOF POINTS:\n" + "\n".join(f"  - {p}" for p in offer.proof_points))
        if offer.cta: lines.append(f"CALL TO ACTION TO USE: {offer.cta}")
        return "\n".join(lines)

    def _build_channel_instructions(self, channel: Channel, stage: Stage, intent: Intent) -> str:
        """Build channel and context specific writing rules with full format specifications"""
        
        CHANNEL_SPECIFICATIONS = {
            Channel.LINKEDIN_DM: {
                "max_chars": 300,
                "greeting": "Informal (e.g., 'Hi [Name],')",
                "structure": "1. Specific observation/hook, 2. Value/Context, 3. Low-friction question.",
                "formatting": "Max 2 short paragraphs. No subject line. No signature.",
                "tone": "Peer-to-peer, conversational, zero sales breath.",
                "cta_style": "Open-ended question (e.g., 'Worth a look?')",
            },
            Channel.LINKEDIN_INMAIL: {
                "max_chars": 600,
                "subject_line": "Required",
                "greeting": "Semi-formal (e.g., 'Hi [Name],')",
                "structure": "1. Curiosity-driven subject, 2. Why them/Why now, 3. Brief value prop, 4. CTA.",
                "formatting": "Bullet points allowed for value prop. Max 150 words.",
                "tone": "Professional, authoritative yet approachable.",
                "cta_style": "Specific request (e.g., 'Open to a brief chat next Tuesday?')",
            },
            Channel.EMAIL: {
                "max_chars": 800,
                "subject_line": "Required",
                "greeting": "Professional (e.g., 'Hi [Name],' or 'Hello [Name],')",
                "structure": "1. Problem-first hook, 2. Social proof/Benefit, 3. Clear CTA.",
                "formatting": "Standard email format. Proper signature block required.",
                "tone": "Warm, professional, helpful.",
                "cta_style": "Interest-based (e.g., 'Mind if I send over a 2-minute video on this?')",
            }
        }
        
        specs = CHANNEL_SPECIFICATIONS.get(channel, CHANNEL_SPECIFICATIONS[Channel.LINKEDIN_DM])
        format_block = "\n".join([f"  - {k.upper()}: {v}" for k, v in specs.items()])
        
        stage_rules = {Stage.FIRST_TOUCH: "Build curiosity, be human.", Stage.SECOND_TOUCH: "Reference first message, add new value.", Stage.THIRD_TOUCH: "Be more direct."}
        intent_rules = {Intent.DIRECT_OUTREACH: "Respect their time.", Intent.FOLLOW_UP: "Reference past interaction.", Intent.REFERRAL: "Lead with mutual connection.", Intent.RE_ENGAGEMENT: "Acknowledge the gap.", Intent.EVENT_BASED: "Reference the trigger."}
        
        return "\n".join([
            f"CHANNEL FORMAT REQUIREMENTS (CRITICAL - FOLLOW EXACTLY):\n{format_block}",
            f"STAGE RULES: {stage_rules.get(stage, '')}",
            f"INTENT RULES: {intent_rules.get(intent, '')}"
        ])

    def _build_voice_block(self, voice_samples: List[str]) -> str:
        """
        Build a voice-matching block from the sender's past messages.
        Tells the LLM to extract and replicate their natural writing patterns.
        """
        if not voice_samples:
            return ""

        samples_text = "\n".join(
            f"  Sample {i+1}: \"{s.strip()}\""
            for i, s in enumerate(voice_samples[:5])  # cap at 5
        )
        return f"""SENDER VOICE — CRITICAL: Study these real messages written by the sender and match their style exactly.
{samples_text}
Extract and replicate:
- Their sentence length and rhythm (short punchy vs longer flowing)
- Punctuation habits (do they use em dashes, ellipses, exclamation marks or avoid them?)
- Vocabulary level (casual slang, professional, technical?)
- How they open (do they jump straight in or warm up first?)
- How they close (soft question, direct ask, statement?)
- Any recurring phrases or patterns unique to them
The final message must sound like IT WAS WRITTEN BY THIS SPECIFIC PERSON, not a generic AI copywriter."""

    def _build_memory_block(self, times_contacted_before: int, last_message_sent: Optional[str]) -> str:
        """Convert memory data into instructions for the LLM"""
        lines = []
        if times_contacted_before > 0:
            lines.append(f"PREVIOUS CONTACT: This prospect has been contacted {times_contacted_before} time(s) before.")
        else:
            lines.append("PREVIOUS CONTACT: This is the first time contacting this prospect.")
        if last_message_sent:
            lines.append(f"LAST MESSAGE SENT TO THEM:\n  \"{last_message_sent}\"")
            lines.append("IMPORTANT: Your new message must be clearly different from the last one sent.")
        return "\n".join(lines) if lines else "NO PRIOR CONTACT HISTORY"

    # ------------------------------------------------------------------
    # PUBLIC METHODS
    # ------------------------------------------------------------------

    def analyze_research_signals(
        self,
        signals: List[Signal],
        prospect_name: str,
        company: str,
        personality: Personality,
        hooks_already_used: List[str] = None,
        best_performing_hooks: List[str] = None,
        best_performing_angles: List[str] = None,
        worst_performing_hooks: List[str] = None,
    ) -> Dict[str, Any]:
        if hooks_already_used is None: hooks_already_used = []
        if best_performing_hooks is None: best_performing_hooks = []
        if best_performing_angles is None: best_performing_angles = []
        if worst_performing_hooks is None: worst_performing_hooks = []
        filtered_signals = signals
        if personality.enabled_hook_types:
            filtered_signals = [s for s in signals if s.type in personality.enabled_hook_types] or signals
        signals_text = "\n".join([f"- [{s.strength.upper()}] {s.type}: {s.content} (Why relevant: {s.why_relevant})" for s in filtered_signals])
        memory_context = ""
        if hooks_already_used: memory_context += "\n\nHOOKS ALREADY USED with this prospect (do NOT pick these again):\n" + "\n".join(f"  - {h}" for h in hooks_already_used)
        if best_performing_hooks: memory_context += "\n\nBEST PERFORMING HOOKS system-wide (prefer similar approaches):\n" + "\n".join(f"  - {h}" for h in best_performing_hooks)
        if worst_performing_hooks: memory_context += "\n\nWORST PERFORMING HOOKS system-wide (avoid these approaches):\n" + "\n".join(f"  - {h}" for h in worst_performing_hooks)
        if best_performing_angles: memory_context += "\n\nBEST PERFORMING ANGLES system-wide (consider similar approaches):\n" + "\n".join(f"  - {a}" for a in best_performing_angles)
        prompt = f"""You are a sales strategy expert analyzing research signals about {prospect_name} at {company}.
RESEARCH SIGNALS:
{signals_text}
ALLOWED HOOK TYPES: {', '.join(personality.enabled_hook_types) if personality.enabled_hook_types else 'All types allowed'}{memory_context}
Your task:
1. Identify the BEST primary hook (most timely, relevant, personal)
2. Identify a good secondary hook
3. Explain your reasoning
Return JSON: {{"primary_hook": "...", "secondary_hook": "...", "reasoning": "...", "confidence": "..."}}"""
        try:
            response = self._call_llm(prompt, system_instruction="You are an expert sales strategist. Always return valid JSON only. All JSON string values must be properly escaped. No markdown.", agent_step="researcher")
            return self._parse_json(response)
        except Exception as e:
            return {"primary_hook": signals[0].content if signals else "General interest", "secondary_hook": signals[1].content if len(signals) > 1 else "Industry trends", "reasoning": f"Fallback due to error: {str(e)}", "confidence": "low"}

    def create_strategy(
        self,
        primary_hook: str,
        secondary_hook: str,
        prospect_name: str,
        company: str,
        prospect_role: Optional[str],
        personality: Personality,
        company_details: CompanyDetails,
        selected_offer: SelectedOffer,
        channel: Channel,
        intent: Intent,
        stage: Stage,
        angles_already_tried: List[str] = None,
        offer_best_angles: List[str] = None,
        language: Optional[str] = None,
    ) -> Strategy:
        if angles_already_tried is None: angles_already_tried = []
        if offer_best_angles is None: offer_best_angles = []
        role_context = f"({prospect_role})" if prospect_role else ""
        memory_context = ""
        if angles_already_tried: memory_context += f"\n\nANGLES ALREADY TRIED (use a DIFFERENT angle):\n" + "\n".join(f"  - {a}" for a in angles_already_tried)
        if offer_best_angles: memory_context += f"\n\nBEST ANGLES FOR THIS OFFER historically (consider these):\n" + "\n".join(f"  - {a}" for a in offer_best_angles)
        language_instruction = ""
        if language and language != "en":
            language_instruction = f"\nOUTPUT LANGUAGE: All strategy text (angle, reasoning) must be written in {language} (ISO 639-1 code). Do NOT write in English."
        prompt = f"""You are a sales messaging strategist.
TARGET: {prospect_name} {role_context} at {company}
PRIMARY HOOK: {primary_hook}
SECONDARY HOOK: {secondary_hook}
STYLE: {personality.base_template.value} | CHANNEL: {channel.value} | STAGE: {stage.value}
SENDER: {company_details.company_name}{f" — {company_details.elevator_pitch}" if company_details.elevator_pitch else ""}
OFFER: {selected_offer.offer_name}{f" — {selected_offer.solution_summary}" if selected_offer.solution_summary else ""}
{self._build_channel_instructions(channel, stage, intent)}{memory_context}{language_instruction}
Return a concise strategy. Reasoning must be under 80 words.
Return JSON: {{"angle": "...", "reasoning": "..."}}"""
        try:
            response = self._call_llm(prompt, system_instruction="You are a sales strategy expert. Always return valid JSON only. All JSON string values must be properly escaped. No markdown.", agent_step="strategist")
            result = self._parse_json(response)
            return Strategy(primary_hook=primary_hook, secondary_hook=secondary_hook, angle=result.get("angle", "Peer-to-peer"), tone=personality.base_template.value, cta_style=selected_offer.cta or "soft_question", reasoning=result.get("reasoning", ""))
        except Exception as e:
            return Strategy(primary_hook=primary_hook, secondary_hook=secondary_hook, angle="Peer-to-peer", tone=personality.base_template.value, cta_style=selected_offer.cta or "soft_question", reasoning=f"Fallback strategy: {str(e)}")

    def write_message(
        self,
        strategy: Strategy,
        prospect_name: str,
        company: str,
        prospect_role: Optional[str],
        personality: Personality,
        company_details: CompanyDetails,
        selected_offer: SelectedOffer,
        channel: Channel,
        intent: Intent,
        stage: Stage,
        times_contacted_before: int = 0,
        last_message_sent: Optional[str] = None,
        is_revision: bool = False,
        previous_draft: Optional[str] = None,
        feedback_from_critic: Optional[str] = None,
        user_notes: Optional[str] = None,
        language: Optional[str] = None
    ) -> Dict[str, Any]:
        channel_limits = {Channel.LINKEDIN_DM: (50, 300), Channel.LINKEDIN_INMAIL: (100, 600), Channel.EMAIL: (100, 800)}
        min_len, max_len = channel_limits.get(channel, (50, 300))
        include_subject = channel in [Channel.LINKEDIN_INMAIL, Channel.EMAIL]
        role_context = f"({prospect_role})" if prospect_role else ""
        memory_block = self._build_memory_block(times_contacted_before, last_message_sent)
        voice_block = self._build_voice_block(personality.voice_samples)

        # --- NEW: Build the revision block if applicable ---
        revision_block = ""
        if is_revision and previous_draft and feedback_from_critic:
            prev_len = len(previous_draft)
            revision_block = f"""REVISION REQUIRED — your previous draft was rejected.
PREVIOUS DRAFT ({prev_len} chars): "{previous_draft}"

FEEDBACK (fix in priority order):
{feedback_from_critic}

Fix the issues above. Keep what works. Stay within {min_len}-{max_len} characters. Do not rewrite from scratch."""

        # User notes: runtime human feedback injected at call time
        user_notes_block = f"\nUSER NOTES: {user_notes}" if user_notes else ""

        # Language instruction: tell Gemini to write the message in the target language
        language_block = ""
        if language and language != "en":
            language_block = f"\nOUTPUT LANGUAGE: Write the ENTIRE message (body, subject line, all text) in {language} (ISO 639-1 language code). Do NOT write in English. The prospect speaks {language}."

        prompt = f"""Write a personalized outreach message.
{revision_block}
{voice_block}
{user_notes_block}
{language_block}
TARGET: {prospect_name} {role_context} at {company}
HOOK: {strategy.primary_hook}
{f"SECONDARY HOOK: {strategy.secondary_hook}" if strategy.secondary_hook else ""}
ANGLE: {strategy.angle}
{f"REASONING: {strategy.reasoning}" if strategy.reasoning else ""}
{f"CTA STYLE: {strategy.cta_style}" if strategy.cta_style else ""}
STYLE: {personality.base_template.value} | URGENCY: {personality.urgency_level}/10 | HUMOR: {personality.humor_sarcasm}/10
{f"TRAITS: {', '.join(personality.personality_traits)}" if personality.personality_traits else ""}
{f"MUST USE: {', '.join(personality.always_include_phrases)}" if personality.always_include_phrases else ""}
{f"NEVER USE: {', '.join(personality.never_use_phrases)}" if personality.never_use_phrases else ""}
SENDER: {company_details.company_name}{f" — {company_details.elevator_pitch}" if company_details.elevator_pitch else ""}
OFFER: {selected_offer.offer_name}{f" — {selected_offer.solution_summary}" if selected_offer.solution_summary else ""}
{f"SOCIAL PROOF (use these exact names/numbers, never invent placeholders): {' | '.join(company_details.social_proof)}" if company_details.social_proof else "NO SOCIAL PROOF PROVIDED — do not invent company names, results, or placeholders like [Similar Company] or [Client Name]. Omit social proof entirely if you have none."}
CTA: {selected_offer.cta or "soft question"}
CHANNEL: {channel.value} | STAGE: {stage.value}
{self._build_channel_instructions(channel, stage, intent)}
{memory_block}
HARD REQUIREMENTS:
- Length: {min_len}-{max_len} characters (STRICT — count every character including spaces. The message will be AUTOMATICALLY REJECTED if it exceeds {max_len} chars. When in doubt, write shorter.)
- TARGET LENGTH: Aim for {int(max_len * 0.7)} characters. Maximum is {max_len} characters.
- Exactly {personality.touchdowns_per_message} distinct touchpoints
- Never use: {', '.join(personality.never_use_phrases) if personality.never_use_phrases else 'nothing banned'}
- Must include naturally: {', '.join(personality.always_include_phrases) if personality.always_include_phrases else 'no required phrases'}
- NEVER use placeholder text like [Company], [Name], [Result], or any bracketed stand-ins. Use only real data provided above.
- NEVER say "I've attached", "see attached", "I'm sending", "I'll send", "check out the link", or imply you are sending files, links, or attachments. You are writing a plain text message only.
- FOLLOW ALL CHANNEL FORMAT REQUIREMENTS ABOVE EXACTLY: greeting style, paragraph structure, signature rules, and CTA format. Messages violating format rules will be rejected.
{"- Include a subject line" if include_subject else "- No subject line"}
Return JSON: {{"body": "...", "subject": {"\"...\"" if include_subject else "null"}, "sentence_breakdown": [{{"text": "...", "purpose": "hook|credibility|value|cta", "driven_by": [...]}}]}}"""
        try:
            response = self._call_llm(prompt, system_instruction="You are an expert sales copywriter. Write authentic human messages. Always return valid JSON only. All JSON string values must be properly escaped. No markdown.", agent_step="writer")
            result = self._parse_json(response)

            # Hard trim: if LLM still overshoots, cut at last sentence boundary within limit
            body = result.get("body", "")
            if len(body) > max_len:
                trimmed = body[:max_len]
                # Try to cut at last sentence-ending punctuation to avoid mid-sentence cuts
                for punct in ("?", "!", "."):
                    last = trimmed.rfind(punct)
                    if last > min_len:
                        trimmed = trimmed[:last + 1]
                        break
                # If trim produced a broken ending (no proper sentence terminator), signal failure for retry
                if not trimmed.rstrip().endswith((".", "?", "!")):
                    raise ValueError(f"Message was {len(body)} chars, trimming produced broken ending. Retry needed.")
                result["body"] = trimmed

            return result
        except Exception:
            # Let exception propagate to the caller (agents.py writer function)
            # which handles retry logic properly. Never return a fallback garbage message.
            raise

    def validate_message(
        self,
        message: str,
        prospect_name: str,
        channel: Channel,
        personality: Personality
    ) -> Dict[str, Any]:
        channel_limits = {Channel.LINKEDIN_DM: (50, 300), Channel.LINKEDIN_INMAIL: (100, 600), Channel.EMAIL: (100, 800)}
        min_len, max_len = channel_limits.get(channel, (50, 300))
        char_count = len(message)

        # --- Run hard rule checks FIRST, before touching the LLM ---
        hard_failures: List[str] = []
        if char_count > max_len:
            hard_failures.append(f"Too long: {char_count} chars, max is {max_len}. Shorten by {char_count - max_len} characters.")
        if char_count < min_len:
            hard_failures.append(f"Too short: {char_count} chars, min is {min_len}. Add at least {min_len - char_count} characters.")
        for phrase in personality.never_use_phrases:
            if phrase.lower() in message.lower():
                hard_failures.append(f"Banned phrase used: '{phrase}'. Remove it.")

        # If hard rules already fail, skip the LLM call entirely — save tokens
        if hard_failures:
            penalty = min(len(hard_failures) * 20, 60)
            return {
                "score": max(0, 100 - penalty),
                "warnings": hard_failures,
                "suggested_fixes": " | ".join(hard_failures),
                "valid": False
            }

        # --- Only call LLM when hard rules pass ---
        banned = ', '.join(personality.never_use_phrases) if personality.never_use_phrases else "none"
        required = ', '.join(personality.always_include_phrases) if personality.always_include_phrases else "none"
        prompt = f"""Evaluate this outreach message for quality.
MESSAGE: {message}
CHANNEL: {channel.value} | CHAR COUNT: {char_count} | REQUIRED: {min_len}-{max_len} chars
BANNED PHRASES: {banned} | REQUIRED PHRASES: {required} | TOUCHDOWNS REQUIRED: {personality.touchdowns_per_message}
Check ONLY: missing required phrases, CTA clarity, authenticity, correct touchdown count.
Do NOT flag: length (already verified), style preferences, word choice, tone subjectivity.
Only flag issues that would make a real sales rep embarrassed to send this message.
IMPORTANT: If score >= {settings.MIN_QUALITY_SCORE}, you MUST set valid to true. Only set valid to false if there is a concrete, fixable problem (missing CTA, wrong touchdown count, required phrase absent, placeholder text).
Score 0-100.
Return JSON: {{"score": 85, "warnings": ["concrete issues only, empty list if none"], "suggested_fixes": "one concise actionable sentence, or null if none", "valid": true}}"""

        try:
            response = self._call_llm(prompt, system_instruction="You are a message quality expert. Return valid JSON only. No markdown.", agent_step="critic")
            result = self._parse_json(response)
            # LLM's valid opinion wins, but a low score always overrides to False
            if result.get("score", 0) < settings.MIN_QUALITY_SCORE:
                result["valid"] = False
            return result
        except Exception as e:
            return {"score": 70, "warnings": [f"Validation LLM failed: {str(e)}"], "suggested_fixes": "Manual review needed", "valid": False}

llm_service = LLMService()
