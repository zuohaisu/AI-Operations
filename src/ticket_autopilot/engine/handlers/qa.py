"""Script-driver entrypoint for the independent QA connector (AIO-7)."""

from ticket_autopilot.connectors.qa import run_qa


def qa(plan=None, result=None, ticket_context=None):
    return run_qa(plan=plan, result=result, ticket_context=ticket_context)
