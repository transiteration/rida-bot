import os
import logging
import base64
from dotenv import load_dotenv
from typing import List, TypedDict, Optional

from langgraph.graph import StateGraph, END
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

load_dotenv()

GEMINI_MODEL = os.getenv("GEMINI_MODEL")
if not GEMINI_MODEL:
    raise ValueError("GEMINI_MODEL environment variable not set.")

llm = ChatGoogleGenerativeAI(model=GEMINI_MODEL, temperature=0)

try:
    prompt_path = os.path.join(os.path.dirname(__file__), "prompt.txt")
    with open(prompt_path, "r") as f:
        SYSTEM_PROMPT = f.read()
    logging.info("Successfully loaded the system prompt.")
except FileNotFoundError:
    logging.error(f"System prompt file not found at: {prompt_path}")
    raise


class GraphState(TypedDict):
    """
    Represents the state of our graph.

    Attributes:
        chat_history: The history of the conversation.
        question: The user's current question.
        generation: The AI's generated response.
        image_bytes: The bytes of the image provided by the user.
        image_mime_type: The MIME type of the image.
        language: The language for the response.
        report_id: The incremental ID for the report.
    """

    chat_history: List[BaseMessage]
    question: str
    generation: str
    image_bytes: Optional[bytes]
    image_mime_type: Optional[str]
    language: str
    report_id: Optional[int]


def generate_response(state: GraphState) -> dict:
    """
    Generates a response using the Gemini model based on the current state.

    Args:
        state: The current state of the graph.

    Returns:
        A dictionary with the updated state.
    """
    logging.info("Generating response...")
    chat_history = state.get("chat_history", [])
    question = state["question"]
    image_bytes = state.get("image_bytes")
    image_mime_type = state.get("image_mime_type")
    language = state.get("language", "English")
    report_id = state.get("report_id")

    system_prompt = SYSTEM_PROMPT
    if report_id is not None:
        formatted_report_id = f"{report_id:02d}"
        system_prompt = system_prompt.replace("{report_id}", formatted_report_id)

    language_instruction = f"IMPORTANT: You must provide your answer in {language}."
    final_system_prompt = f"{language_instruction}\n\n{system_prompt}"

    if image_bytes and image_mime_type:
        logging.info(f"Image detected (MIME type: {image_mime_type})")
        base64_image = base64.b64encode(image_bytes).decode("utf-8")
        user_message_content = [
            question,
            {
                "type": "image_url",
                "image_url": f"data:{image_mime_type};base64,{base64_image}",
            },
        ]
    else:
        user_message_content = question

    messages = [
        SystemMessage(content=final_system_prompt),
        *chat_history,
        HumanMessage(content=user_message_content),
    ]

    try:
        response = llm.invoke(messages)
        generation = response.content
        logging.info("Successfully generated response from the model.")
    except Exception as e:
        logging.error(f"Error during model invocation: {e}")
        generation = "Sorry, I encountered an error while processing your request. Please try again."

    human_message_for_history = question
    if image_bytes:
        if question:
            human_message_for_history = f"{question}\n(Image attached)"
        else:
            human_message_for_history = "(Image attached)"

    new_chat_history = chat_history + [
        HumanMessage(content=human_message_for_history),
        AIMessage(content=generation),
    ]

    return {
        "generation": generation,
        "question": question,
        "chat_history": new_chat_history,
        "image_bytes": None,
        "image_mime_type": None,
        "language": language,
        "report_id": report_id,
    }


def new_chat() -> GraphState:
    """
    Returns an empty state to start a new conversation.
    """
    return {
        "chat_history": [],
        "question": "",
        "generation": "",
        "image_bytes": None,
        "image_mime_type": None,
        "language": "English",
        "report_id": None,
    }


workflow = StateGraph(GraphState)
workflow.add_node("generate", generate_response)
workflow.set_entry_point("generate")
workflow.add_edge("generate", END)
app = workflow.compile()
logging.info("Graph compiled successfully.")
