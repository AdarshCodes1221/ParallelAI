class Planner:
    """Creates an execution plan from the required tools."""
    
    @staticmethod
    def create_plan(required_tools: list[str]) -> list[dict]:
        plan = []
        for t in required_tools:
            plan.append({"tool": t, "status": "pending"})
        return plan
