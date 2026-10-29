"""
Temporal Sequence Workflow.

Orchestrates the execution of an outreach sequence with human-in-the-loop
approval modes and per-step message generation.
"""

from datetime import timedelta
from temporalio import workflow
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field


@dataclass
class StepState:
    """State of a single sequence step."""
    step_num: int
    action_type: str
    channel: str
    scheduled_timestamp_utc: str
    wait_delay_seconds: int
    status: str = "pending"  # pending, ready, sent, skipped, failed
    message: Optional[Dict[str, Any]] = None
    quality_score: Optional[int] = None
    error: Optional[str] = None
    sent_at: Optional[str] = None
    day_offset: int = 0
    time_of_day: str = "10h"
    strategy_notes: str = ""


@dataclass
class WorkflowState:
    """Complete workflow state."""
    status: str = "initializing"  # initializing, researching, generating_strategy, parsing_strategy, generating_messages, ready, in_progress, completed, stopped, failed
    company_name: str = ""
    persona: Dict[str, Any] = field(default_factory=dict)
    detected_language: Optional[str] = None
    approval_mode: str = "per_sequence"
    total_steps: int = 0
    steps: List[StepState] = field(default_factory=list)
    gemini_strategy: Optional[Dict[str, Any]] = None
    personality_analysis: Optional[str] = None
    linkedin_activity_score: int = 0
    best_time_of_day: str = "10h"
    current_step: int = 0
    error: Optional[str] = None


@workflow.defn
class SequenceWorkflow:
    """
    Temporal workflow for executing outreach sequences.
    
    Supports three approval modes:
    - per_sequence: Approve entire plan once, then execute all steps
    - per_step: Approve before each step execution
    - per_step_and_message: Approve step plan AND generated message before send
    """
    
    def __init__(self):
        self._state = WorkflowState()
        self._sequence_approved = False
        self._approved_steps = set()
        self._skip_steps = set()
        self._regenerate_steps = {}  # step_num -> feedback
        self._stop_requested = False
    
    @workflow.run
    async def run(self, detective_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main workflow entry point.
        
        Args:
            detective_data: Enriched data from detective module
            
        Returns:
            Final workflow state
        """
        workflow.logger.info("Starting sequence workflow")
        
        try:
            # Extract basic info
            self._state.company_name = detective_data.get("company_name", "Unknown")
            self._state.persona = detective_data.get("selected_persona", {})
            self._state.status = "researching"
            
            # Step 1: Research company (using Gemini)
            research_result = await workflow.execute_activity(
                "research_company_activity",
                detective_data,
                start_to_close_timeout=timedelta(seconds=60)
            )
            
            # Step 2: Generate strategy
            self._state.status = "generating_strategy"
            strategy_result = await workflow.execute_activity(
                "generate_strategy_activity",
                {
                    "detective_data": detective_data,
                    "research_result": research_result
                },
                start_to_close_timeout=timedelta(seconds=120)
            )
            
            # Step 3: Parse strategy into steps
            self._state.status = "parsing_strategy"
            parse_result = await workflow.execute_activity(
                "parse_gemini_strategy_activity",
                strategy_result,
                start_to_close_timeout=timedelta(seconds=60)
            )
            
            # Extract parsed data
            self._state.gemini_strategy = strategy_result
            self._state.personality_analysis = strategy_result.get("personality_analysis")
            self._state.linkedin_activity_score = strategy_result.get("linkedin_activity_score", 0)
            self._state.best_time_of_day = strategy_result.get("best_time_of_day", "10h")
            self._state.detected_language = parse_result.get("detected_language")
            self._state.approval_mode = parse_result.get("approval_mode", "per_sequence")
            
            # Build step states
            steps_data = parse_result.get("steps", [])
            self._state.total_steps = len(steps_data)
            self._state.steps = [
                StepState(
                    step_num=s.get("step_num", i + 1),
                    action_type=s.get("action_type", "EMAIL_1"),
                    channel=s.get("channel", "email"),
                    scheduled_timestamp_utc=s.get("scheduled_timestamp_utc", ""),
                    wait_delay_seconds=s.get("wait_delay_seconds", 0),
                    day_offset=s.get("day_offset", 0),
                    time_of_day=s.get("time_of_day", "10h"),
                    strategy_notes=s.get("strategy_notes", "")
                )
                for i, s in enumerate(steps_data)
            ]
            
            # Step 4: Human approval gate based on approval_mode
            if self._state.approval_mode == "per_sequence":
                # Wait for entire sequence approval
                self._state.status = "ready"
                await workflow.wait_condition(
                    lambda: self._sequence_approved or self._stop_requested
                )
                
                if self._stop_requested:
                    self._state.status = "stopped"
                    return self._get_state_dict()
            
            # Step 6: Execute steps
            self._state.status = "in_progress"
            for step in self._state.steps:
                if self._stop_requested:
                    self._state.status = "stopped"
                    break
                
                self._state.current_step = step.step_num
                
                # Per-step approval mode
                if self._state.approval_mode in ["per_step", "per_step_and_message"]:
                    step.status = "pending"
                    await workflow.wait_condition(
                        lambda s=step: s.step_num in self._approved_steps or 
                                      s.step_num in self._skip_steps or
                                      self._stop_requested
                    )
                    
                    if self._stop_requested:
                        self._state.status = "stopped"
                        break
                    
                    if step.step_num in self._skip_steps:
                        step.status = "skipped"
                        continue
                
                # JIT: Generate message for this step if not already generated or if regeneration requested
                if step.step_num in self._regenerate_steps or not step.message:
                    feedback = self._regenerate_steps.get(step.step_num)
                    message_result = await workflow.execute_activity(
                        "generate_message_activity",
                        {
                            "step_num": step.step_num,
                            "action_type": step.action_type,
                            "channel": step.channel,
                            "detective_data": detective_data,
                            "strategy": strategy_result,
                            "feedback": feedback
                        },
                        start_to_close_timeout=timedelta(seconds=90)
                    )
                    
                    if message_result.get("success"):
                        step.message = {
                            "message": message_result.get("message"),
                            "subject": message_result.get("subject"),
                            "warnings": message_result.get("warnings", [])
                        }
                        step.quality_score = message_result.get("score")
                        step.status = "ready"
                    else:
                        step.status = "failed"
                        step.error = message_result.get("error", "Message generation failed")
                        # Skip sending if message generation failed
                        continue
                
                # Wait for scheduled time
                if step.wait_delay_seconds > 0:
                    await workflow.sleep(timedelta(seconds=step.wait_delay_seconds))
                
                # Send message
                send_result = await workflow.execute_activity(
                    "send_message_activity",
                    {
                        "step_num": step.step_num,
                        "message": step.message,
                        "persona": self._state.persona,
                        "channel": step.channel
                    },
                    start_to_close_timeout=timedelta(seconds=60)
                )
                
                if send_result.get("success"):
                    step.status = "sent"
                    step.sent_at = send_result.get("sent_at")
                else:
                    step.status = "failed"
                    step.error = send_result.get("error", "Send failed")
            
            # Complete
            if not self._stop_requested:
                self._state.status = "completed"
            
            return self._get_state_dict()
            
        except Exception as e:
            workflow.logger.error(f"Workflow failed: {e}")
            self._state.status = "failed"
            self._state.error = str(e)
            return self._get_state_dict()
    
    @workflow.query
    def get_full_state(self) -> Dict[str, Any]:
        """Query: Return complete workflow state."""
        return self._get_state_dict()
    
    @workflow.signal
    async def approve_sequence(self):
        """Signal: Approve the entire sequence (per_sequence mode)."""
        workflow.logger.info("Sequence approved")
        self._sequence_approved = True
    
    @workflow.signal
    async def approve_step(self, step_num: int):
        """Signal: Approve a specific step (per_step modes)."""
        workflow.logger.info(f"Step {step_num} approved")
        self._approved_steps.add(step_num)
    
    @workflow.signal
    async def send_step(self, step_num: int):
        """Signal: Send a specific step immediately."""
        workflow.logger.info(f"Step {step_num} send requested")
        self._approved_steps.add(step_num)
    
    @workflow.signal
    async def skip_step(self, step_num: int):
        """Signal: Skip a specific step."""
        workflow.logger.info(f"Step {step_num} skip requested")
        self._skip_steps.add(step_num)
    
    @workflow.signal
    async def regenerate_step(self, step_num: int, feedback: str = ""):
        """Signal: Regenerate a step's message with optional feedback."""
        workflow.logger.info(f"Step {step_num} regeneration requested with feedback: {feedback}")
        self._regenerate_steps[step_num] = feedback
        self._approved_steps.add(step_num)  # Auto-approve after regeneration
    
    @workflow.signal
    async def stop_sequence(self):
        """Signal: Stop the entire sequence."""
        workflow.logger.info("Sequence stop requested")
        self._stop_requested = True
    
    def _get_state_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary."""
        return {
            "status": self._state.status,
            "company_name": self._state.company_name,
            "persona": self._state.persona,
            "detected_language": self._state.detected_language,
            "approval_mode": self._state.approval_mode,
            "total_steps": self._state.total_steps,
            "current_step": self._state.current_step,
            "steps": [
                {
                    "step_num": s.step_num,
                    "action_type": s.action_type,
                    "channel": s.channel,
                    "scheduled_timestamp_utc": s.scheduled_timestamp_utc,
                    "wait_delay_seconds": s.wait_delay_seconds,
                    "status": s.status,
                    "message": s.message,
                    "quality_score": s.quality_score,
                    "error": s.error,
                    "sent_at": s.sent_at,
                    "day_offset": s.day_offset,
                    "time_of_day": s.time_of_day,
                    "strategy_notes": s.strategy_notes
                }
                for s in self._state.steps
            ],
            "gemini_strategy": self._state.gemini_strategy,
            "personality_analysis": self._state.personality_analysis,
            "linkedin_activity_score": self._state.linkedin_activity_score,
            "best_time_of_day": self._state.best_time_of_day,
            "error": self._state.error
        }
