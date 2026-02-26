from dotenv import load_dotenv
load_dotenv()

import anthropic
import json
import math
from conditions.store import ConditionStore
from tools.tools import ( query_conditions, correct_condition )
from conditions.store import ConditionStore
from pathlib import Path

# Pre-load the data
data_path = Path(__file__).resolve().parent.parent / "data" / "conditions.json"
data = json.loads(data_path.read_text())
store = ConditionStore()
mid = math.ceil(len(data) / 2)
store.ingest_batch(data[:mid], "day1")
store.ingest_batch(data[mid:], "day2")
store.mark_ingestion_complete()

client = anthropic.Anthropic()

# Define the tools for Claude
tools = [
    {
        "name": "query_conditions",
        "description": "Search the patient's medical conditions",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "condition to search for"},
                "active_only": {"type": "boolean", "description": "only active conditions"},
            }
        }
    },
    {
        "name": "correct_condition",
        "description": "Remove a condition the patient says they don't have",
        "input_schema": {
            "type": "object",
            "properties": {
                "concept": {"type": "string", "description": "condition to retract"},
            },
            "required": ["concept"]
        }
    },
]

# Tool dispatcher
def run_tool(name, inputs):
    if name == "query_conditions":
        return query_conditions(store, **inputs)
    elif name == "correct_condition":
        return correct_condition(store, **inputs)

# Chat loop
messages = []
print("Chat with Claude about your conditions. Type 'quit' to exit.\n")

while True:
    user_input = input("You: ")
    if user_input.lower() == "quit":
        break

    messages.append({"role": "user", "content": user_input})

    # Agentic loop - Claude may call tools multiple times
    while True:
        response = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=1024,
            system="You are a helpful medical assistant. Use the available tools to answer questions about the patient's conditions.",
            tools=tools,
            messages=messages,
        )

        # If Claude wants to use a tool
        if response.stop_reason == "tool_use":
            # Add Claude's response to history
            messages.append({"role": "assistant", "content": response.content})

            # Run each tool Claude asked for
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    print(f"  [calling {block.name}({block.input})]")
                    result = run_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    })

            # Feed results back to Claude
            messages.append({"role": "user", "content": tool_results})

        # Claude is done, print final response
        else:
            final = next(b.text for b in response.content if hasattr(b, "text"))
            print(f"\nClaude: {final}\n")
            messages.append({"role": "assistant", "content": final})
            break