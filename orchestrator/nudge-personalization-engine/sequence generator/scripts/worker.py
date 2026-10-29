import sys
import os
from pathlib import Path

# Add parent directory ("sequence generator") to sys.path so that
# the "workflows" package can be imported when running this script directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
from temporalio.client import Client
from temporalio.worker import Worker

# Import new sequence workflow only
from workflows.sequence_workflow import SequenceWorkflow

# Import activities
from workflows.message_activities import (
    research_company_activity,
    generate_strategy_activity,
    parse_gemini_strategy_activity,
    generate_message_activity,
    send_message_activity,
)

async def main():
    # 1. Connexion au serveur Temporal local
    client = await Client.connect("localhost:7233")

    # 2. Configuration du Worker
    worker = Worker(
        client,
        task_queue="sequence-task-queue",
        workflows=[SequenceWorkflow],
        activities=[
            research_company_activity,
            generate_strategy_activity,
            parse_gemini_strategy_activity,
            generate_message_activity,
            send_message_activity,
        ],
    )

    print("Worker démarré !")
    print("   - File: sequence-task-queue")
    print("   - Workflows: SequenceWorkflow")
    print("   - Activities: Research, Strategy, Parse, Generate, Send")
    print("\nEn attente de tâches...")
    await worker.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nWorker arrêté.")