from strands import Agent, tool


@tool
def run_query(sql: str) -> str:
    return sql


run_query = Agent(tools=[run_query])
