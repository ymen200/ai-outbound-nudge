"""
Temporal Client for Streamlit integration.
Provides helper functions to start workflows, check status, and send signals.
"""

import asyncio
from datetime import datetime
from typing import Optional, Dict, Any
from temporalio.client import Client

# Workflow import for type hints
from workflows.sequence_workflow import SequenceWorkflow


class SequenceTemporalClient:
    """
    Client for interacting with Temporal workflows from Streamlit.
    """
    
    def __init__(self, temporal_host: str = "localhost:7233"):
        self.temporal_host = temporal_host
        self._client: Optional[Client] = None
    
    async def _get_client(self) -> Client:
        """Get or create Temporal client connection."""
        if self._client is None:
            self._client = await Client.connect(self.temporal_host)
        return self._client
    
    async def start_sequence(
        self, 
        detective_data: dict,
        workflow_id: Optional[str] = None
    ) -> str:
        """
        Start a new sequence workflow.
        
        Args:
            detective_data: Output from Detective module (company, persona, ICP)
            workflow_id: Optional custom workflow ID
            
        Returns:
            Workflow ID that can be used to query status later
        """
        client = await self._get_client()
        
        # Generate workflow ID if not provided
        if workflow_id is None:
            company_key = detective_data.get("company_key", "unknown")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            workflow_id = f"sequence-{company_key}-{timestamp}"
        
        # Start workflow
        handle = await client.start_workflow(
            SequenceWorkflow.run,
            args=[detective_data],
            id=workflow_id,
            task_queue="sequence-task-queue"
        )
        
        return handle.id
    
    async def get_sequence_status(self, workflow_id: str) -> Dict[str, Any]:
        """
        Get current status of a sequence workflow.
        
        Returns:
            Full workflow state including steps, messages, status
        """
        client = await self._get_client()
        handle = client.get_workflow_handle(workflow_id)
        
        try:
            # Query workflow state
            state = await handle.query(SequenceWorkflow.get_full_state)
            return {
                "success": True,
                "state": state,
                "exists": True
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "exists": False
            }
    
    async def send_step(self, workflow_id: str, step_num: int) -> Dict[str, Any]:
        """
        Send a signal to execute a specific step.
        
        Args:
            workflow_id: Workflow ID
            step_num: Step number to send (1-indexed)
            
        Returns:
            Result of send operation
        """
        client = await self._get_client()
        handle = client.get_workflow_handle(workflow_id)
        
        try:
            await handle.signal(SequenceWorkflow.send_step, step_num)
            return {
                "success": True,
                "message": f"Signal sent to send step {step_num}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def skip_step(self, workflow_id: str, step_num: int) -> Dict[str, Any]:
        """Skip a specific step."""
        client = await self._get_client()
        handle = client.get_workflow_handle(workflow_id)
        
        try:
            await handle.signal(SequenceWorkflow.skip_step, step_num)
            return {
                "success": True,
                "message": f"Step {step_num} skipped"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def regenerate_step(
        self, 
        workflow_id: str, 
        step_num: int, 
        feedback: str
    ) -> Dict[str, Any]:
        """
        Regenerate a step with feedback.
        
        Args:
            workflow_id: Workflow ID
            step_num: Step number to regenerate
            feedback: User feedback for regeneration
        """
        client = await self._get_client()
        handle = client.get_workflow_handle(workflow_id)
        
        try:
            await handle.signal(SequenceWorkflow.regenerate_step, step_num, feedback)
            return {
                "success": True,
                "message": f"Regeneration signal sent for step {step_num}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def stop_sequence(self, workflow_id: str) -> Dict[str, Any]:
        """Stop the entire sequence."""
        client = await self._get_client()
        handle = client.get_workflow_handle(workflow_id)
        
        try:
            await handle.signal(SequenceWorkflow.stop_sequence)
            return {
                "success": True,
                "message": "Sequence stop signal sent"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def approve_sequence(self, workflow_id: str) -> Dict[str, Any]:
        """Approve the entire sequence (per_sequence mode)."""
        client = await self._get_client()
        handle = client.get_workflow_handle(workflow_id)
        
        try:
            await handle.signal(SequenceWorkflow.approve_sequence)
            return {
                "success": True,
                "message": "Sequence approved"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def approve_step(self, workflow_id: str, step_num: int) -> Dict[str, Any]:
        """Approve a specific step (per_step modes)."""
        client = await self._get_client()
        handle = client.get_workflow_handle(workflow_id)
        
        try:
            await handle.signal(SequenceWorkflow.approve_step, step_num)
            return {
                "success": True,
                "message": f"Step {step_num} approved"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def list_active_sequences(self) -> list:
        """
        List all active sequence workflows.
        Note: This is a simplified version - in production you'd use Temporal's list API.
        """
        # For now, return empty list - would need Temporal's workflow list API
        return []


# Note: Legacy sync wrappers removed as Streamlit is no longer used.
# Use the async methods directly in async contexts.
