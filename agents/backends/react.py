from __future__ import annotations

import json
import pathlib
from os import path
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel

from agents.backends.base import BaseBackend
from agents.llms.llm import LLM, Prompt
from agents.templater import PromptTemplate
from agents.tools.tool import Tool
from agents.tools.types import ToolArguments, ToolResults


class ReActResponse(BaseModel):
    Thought: str
    Action: Optional[str] = None
    ActionInput: Optional[Dict[str, Any]] = None
    Answer: Optional[str] = None


class ReActBackend(BaseBackend):

    def __init__(
        self,
        llm: LLM,
        tools: List[Tool],
        agent_explanation: str,
    ):
        super().__init__(llm, tools, max_simultaneous_tools=1)

        self.agent_explanation = agent_explanation
        self.__templater = PromptTemplate.from_file(
            path.join(
                pathlib.Path(__file__).parent,
                "prompts",
                "react.prompt",
            )
        )

    def __parse(self, text: str) -> ReActResponse:
        lines = text.strip().split("\n")
        results: Dict[str, Optional[Union[str, Dict]]] = {
            "Thought": None,
            "Action": None,
            "Action Input": None,
            "Answer": None,
        }

        # Extract Thought
        if lines and lines[0].startswith("Thought:"):
            results["Thought"] = lines.pop(0).split("Thought:", 1)[1].strip()
        else:
            raise FormatException

        # Extract Action and Action Input
        while lines:
            line = lines.pop(0)
            if not line.strip():
                continue
            if line.startswith("Action:"):
                results["Action"] = line.split("Action:", 1)[1].strip()
            elif line.startswith("Action Input:"):
                action_input_str = line.split("Action Input:", 1)[1].strip()
                try:
                    # Attempt to parse Action Input as JSON
                    results["Action Input"] = json.loads(action_input_str)
                except json.JSONDecodeError:
                    results["Action Input"] = action_input_str
            elif line.startswith("Answer:"):
                # Found the answer, capture it and any remaining lines
                results["Answer"] = (
                    line.split("Answer:", 1)[1].strip()
                    + "\n"
                    + "\n".join(lines)
                )
                break  # Stop processing after finding the answer

        # Validation
        if results["Action"] is not None and results["Action Input"] is None:
            raise ValueError("Action specified without Action Input")

        # Handle missing Answer if Action is present - necessary for
        # pydantic
        if results["Action"] is not None and results["Answer"] is None:
            results["Answer"] = ""

        # Convert Action Input to ActionInput for pydantic
        results["ActionInput"] = results["Action Input"]
        del results["Action Input"]

        # Use Pydantic for final validation and parsing
        return ReActResponse(**results)

    def parse_for_result(self, text: str) -> str:
        return self.__parse(text).Answer

    def parse_for_tool_calls(
        self, text: str, stop_at_first_tool: bool = False
    ) -> List[Tuple[str, ToolArguments]]:
        response = self.__parse(text)

        return (
            []
            if not response.Action
            else [
                (
                    response.Action,
                    response.ActionInput,
                )
            ]
        )

    def tool_results_to_prompts(
        self, prompt: Prompt, results: ToolResults
    ) -> List[Prompt]:
        for name, args, result in results:
            out = f"---\n{name}("

            first_tool = True
            for arg, value in args.items():
                if first_tool:
                    first_tool = False
                else:
                    out += ", "
                out += f"{arg}="
                if isinstance(value, str):
                    out += f'"{value}"'
                else:
                    out += f"{value}"
            out += f") returned:\n{result}\n"
            prompt.append(
                {
                    "role": "system",
                    "content": out,
                }
            )
        return prompt

    def prepare_prompt(self, **kwargs) -> Prompt:
        # Create the tools block
        tools_block = ""
        for _, tool in self.tools.items():
            tools_block += f"{tool}\n"

        return self.__templater.render(
            {
                # "agent_explanation": self.agent_explanation,
                "tools_block": tools_block,
                "task": kwargs["task"],
            }
        )


class FormatException(Exception):
    pass


class ResponseException(Exception):
    pass


class ToolException(Exception):
    pass
