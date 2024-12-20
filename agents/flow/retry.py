from agents.tools.tool import Tool, Context
from typing import Optional, Type, Union, List
import time


class Retry(Tool):
    """
    A wrapper tool that retries failed executions of another tool.

    This tool will catch exceptions and retry the execution up to a specified
    number of times. It can be configured to only retry on specific exception
    types and to wait between retries.

    Args:
        tool (Tool): The base tool to wrap and retry on failure
        max_retries (int): Maximum number of retry attempts (not counting
        initial try)
        exceptions (Union[Type[Exception], List[Type[Exception]]], optional):
            Specific exception type(s) to retry on. If None, retries on any
            Exception.
        delay (float, optional): Time in seconds to wait between retries.
            Defaults to 0 (no delay).
        name (str, optional): Custom name for the tool.
            Defaults to "{tool.name}::retry_{max_retries}".
        description (str, optional): Custom description.
            Defaults to base tool's description.
    """

    def __init__(
        self,
        tool: Tool,
        max_retries: int,
        exceptions: Optional[
            Union[Type[Exception], List[Type[Exception]]]
        ] = None,
        delay: float = 0,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ):
        self._tool = tool
        self._max_retries = max_retries
        self._delay = delay

        # Handle single exception or list of exceptions
        if exceptions is None:
            self._exceptions = (Exception,)
        elif isinstance(exceptions, list):
            self._exceptions = tuple(exceptions)
        else:
            self._exceptions = (exceptions,)

        if not name:
            name = f"{tool.name}::retry_{max_retries}"

        if not description:
            description = tool.description

        super().__init__(
            name=name,
            args=tool.args,
            description=description,
            func=self.retry_invoke,
            examples=tool.examples,
        )

    def retry_invoke(self, context: Context, **kwargs):
        """
        Execute the wrapped tool with retry logic.

        Args:
            context (Context): The execution context
            **kwargs: Arguments to pass to the wrapped tool

        Returns:
            Any: The result from a successful execution

        Raises:
            Exception: The last exception encountered after all retries are exhausted
        """
        attempts = 0
        last_exception = None

        while attempts <= self._max_retries:
            try:
                return self._tool.invoke(context, **kwargs)
            except self._exceptions as e:
                last_exception = e
                attempts += 1

                if attempts <= self._max_retries:
                    if self._delay > 0:
                        time.sleep(self._delay)
                    continue
                break

        # If we get here, we've exhausted all retries
        raise last_exception
