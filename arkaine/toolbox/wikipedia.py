from typing import Any, Dict, List, Optional

import wikipedia

from arkaine.agent import BackendAgent
from arkaine.backends.base import BaseBackend
from arkaine.backends.react import ReActBackend
from arkaine.llms.llm import LLM
from arkaine.tools.tool import Argument, Tool
from arkaine.tools.wrappers.top_n import TopN
from arkaine.utils.documents import (
    InMemoryEmbeddingStore,
    chunk_text_by_sentences,
)
from arkaine.utils.templater import PromptTemplate

TOPIC_QUERY_TOOL_NAME = "wikipedia_search_pages"
PAGE_CONTENT_TOOL_NAME = "wikipedia_get_page"


class WikipediaTopicQuery(Tool):

    def __init__(self):
        super().__init__(
            TOPIC_QUERY_TOOL_NAME,
            "Search Wikipedia for articles that match a given query topic -"
            + " returns a list of titles of Wiki pages that possibly match. "
            + f"Follow this function call with a {PAGE_CONTENT_TOOL_NAME} "
            + "function to get the content of the chosen title",
            [
                Argument(
                    name="query",
                    type="string",
                    description=(
                        "A simple query to search associated Wikipedia pages "
                        + "for"
                    ),
                    required=True,
                ),
            ],
            self.topic_query,
        )

    def topic_query(self, query: str) -> List[str]:
        topics = wikipedia.search(query)
        if len(topics) == 0:
            return "No topics match this query"

        out = "The following are titles to pages that match your query:\n"
        for topic in topics:
            out += topic + "\n"

        return out


class WikipediaPage(Tool):

    def __init__(self):
        super().__init__(
            PAGE_CONTENT_TOOL_NAME,
            (
                "Get the content of a Wikipedia page based on its title. "
                + "Content is returned as a dictionary with section titles as "
                + "keys and the content of that section as values."
            ),
            [
                Argument(
                    name="title",
                    type="string",
                    description="The title of the Wikipedia page - "
                    + "returns 'None' if the page does not exist",
                    required=True,
                )
            ],
            self.get_page,
        )

    def __break_down_content(self, content: str) -> Dict[str, str]:
        """
        Break down Wikipedia content into sections and their corresponding
        chunks.

        Wikipedia content is separated by section headers marked with '='
        characters. This method splits the content into sections and chunks
        each section's text into smaller, sentence-based segments.

        Args:
            content (str): Raw Wikipedia page content

        Returns:
            Dict[str, str]: Dictionary where keys are section titles and
                values the text from that section. Note we do not have nesting
                (subsections) - it's all one level deep.
        """
        # For cleanliness we're adding a fake title if none exists
        content = "= Title =\n\n" + content

        sections: Dict[str, str] = {}
        current_section = []
        current_title = ""

        for line in content.split("\n"):
            if line.strip() == "":
                continue

            if line[0] == "=" and line[-1] == "=":
                if len(current_section) > 0:
                    sections[current_title] = " ".join(current_section)
                    current_section = []
                current_title = line.strip(" =")
            else:
                current_section.append(line)

        # Don't forget the last section
        if len(current_section) > 0:
            sections[current_title] = " ".join(current_section)

        return sections

    def get_page(self, title: str) -> Dict[str, str]:
        content = wikipedia.page(title).content

        sections = self.__break_down_content(content)

        return sections


class WikipediaPageTopN(TopN):
    def __init__(
        self,
        name: Optional[str] = None,
        wp: Optional[WikipediaPage] = None,
        embedder: Optional[InMemoryEmbeddingStore] = None,
        n: int = 5,
    ):
        if wp is None:
            wp = WikipediaPage()

        if name is None:
            name = "wikipedia_page"

        if embedder is None:
            embedder = InMemoryEmbeddingStore()

        description = (
            "Get the content of a Wikipedia page based on its title. "
            + "Content is returned as a dictionary with section titles as "
            + "keys and the content of that section as values."
        )
        query_description = (
            "The query to search that specified Wikipedia to narrow results "
            + "to related history."
        )

        super().__init__(
            wp,
            5,
            embedder,
            name=name,
            description=description,
            query_description=query_description,
        )


class WikipediaSearch(BackendAgent):
    """
    A tool agent that searches Wikipedia to answer questions using either
    direct page content or semantically relevant sections.

    This agent combines Wikipedia search and content retrieval capabilities. It
    can either return full Wikipedia articles or use semantic search to return
    the most relevant sections based on the query.

    Args:
        llm (Optional[LLM]): Language model to use for processing. Required if
            no backend is specified.
        name (str): Name of the agent. Defaults to "wikipedia_search". backend
        (Optional[BaseBackend]): Custom backend to use. If not provided,
            creates a ReActBackend with the specified LLM.
        compress_article (bool): If True, uses semantic search to return
            relevant sections. If False, returns full articles. Defaults to
            True.
        embedder (Optional[InMemoryEmbeddingStore]): Embedding store for
            semantic search when compress_article is True. If not provided and
            needed, creates a new store default InMemoryEmbeddingStore.

    Raises:
        ValueError: If no LLM is provided when backend is not specified.
    """

    def __init__(
        self,
        llm: Optional[LLM] = None,
        name: str = "wikipedia_search",
        backend: Optional[BaseBackend] = None,
        compress_article: bool = True,
        embedder: Optional[InMemoryEmbeddingStore] = None,
    ):
        description = (
            "Searches for an answer to the question by utilizing Wikipedia"
        )

        if not backend:
            if llm is None:
                raise ValueError("LLM is required if not specifying a backend")
            backend = ReActBackend(
                llm,
                [WikipediaPageTopN(embedder=embedder), WikipediaTopicQuery()],
                description,
            )
        else:
            backend.add_tool(WikipediaTopicQuery())
            if compress_article:
                if embedder is None:
                    embedder = InMemoryEmbeddingStore()
                backend.add_tool(WikipediaPageTopN(embedder=embedder))
            else:
                backend.add_tool(WikipediaPage())
        super().__init__(
            name,
            description,
            [
                Argument(
                    "question",
                    "Your question you want answered",
                    "string",
                    required=True,
                )
            ],
            backend,
        )

    def prepare_for_backend(self, **kwargs) -> Dict[str, Any]:
        question = f"Answer the following question: {kwargs['question']}\n"

        return {"task": question}
