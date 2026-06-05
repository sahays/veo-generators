# Conversational Interface & Multi-Agent Integration Plan

## Background & Motivation
We are brainstorming how to transform Veo Generators from a form-driven web application into a conversational, AI-driven workspace. Instead of a single chatbot, the system will utilize a **Multi-Agent Architecture** where specialized AI agents (e.g., Director, Editor, Marketing) collaborate to fulfill user requests via chat. 

## How We Will Create Agents

To implement agents without drastically altering the existing decoupled services, we will build an Agent Orchestration Layer in the FastAPI backend.

### 1. Orchestration with Google Agent Development Kit (ADK)
When coordinating multiple agents (Orchestrator, Editor, Marketer), managing the state, tool execution, and passing context between them manually becomes complex. 

**Recommendation:** We will use the **Google Agent Development Kit (ADK)** to orchestrate the agents.
- **Why Google ADK?** It is purpose-built for hierarchical orchestration and multi-agent systems, integrating perfectly with Vertex AI and the Gemini models we are already using.
- **Benefits for Veo Generators:**
  - **Hierarchical Orchestration:** Allows a primary "Router" agent to easily delegate sub-tasks to the specialized Video/Marketing agents.
  - **Built-in Tool Support:** We can easily expose our existing FastAPI Python services (like `promo_service.py`) as tools to the ADK agents.
  - **State & Context Management:** Automatically manages the conversation thread and shared context required when bouncing between agents.

### 2. Agent Architecture (Backend with Google ADK)
Using Google ADK, we will introduce an `api/agents/` module:
- **Agent State**: A shared state managed by the ADK containing the chat history, current active task, and collected form data (e.g., `source_video_url`).
- **Agents**: Each specialized agent is instantiated via the ADK with its own **System Prompt** and **Tools** (wrapping existing services like `reframe_service.py`).
- **Orchestrator**: The central ADK router that evaluates user intent and passes execution control to the correct agent.

### 3. Proposed Agent Roster
1. **The Orchestrator (Router) Agent**:
   - *Role*: The initial point of contact for the user. Analyzes intent and routes to the correct specialized agent.
2. **The Production Agent ("Director")**:
   - *Tools*: `create_production_project`, `generate_script`, `generate_storyboard`.
3. **The Editing Agent ("Editor")**:
   - *Tools*: `reframe_video`, `get_focal_paths`, `extract_key_moments`.
4. **The Marketing Agent ("Marketer")**:
   - *Tools*: `create_promo`, `adapt_prompts_for_platform`.

### 4. Input Validation & Requirement Gathering
When a user makes a vague request (e.g., *"Make a promo"*), the system needs a structured way to ask for the missing parameters (like `target_duration` or `source_video`).

**How Google ADK solves this:**
- The Orchestrator routes the request to the **Marketing Agent**.
- The ADK's built-in tool schema validation checks the Pydantic schema for `create_promo` and detects that `source_video` is missing.
- The agent utilizes ADK's self-correction/validation loop, pauses execution, and returns a `form_request` to the user: *"Which video would you like me to use? Please upload one or provide a link."*
- Once the user replies, the ADK state is updated, and execution resumes.

### 5. Execution Flow (How Agents Communicate)
1. User sends a message via the frontend UI: *"Make a 15-second vertical promo out of my latest video."*
2. The **ADK Orchestrator** updates the shared state and routes to the **Marketing Agent**.
3. The **Marketing Agent** checks requirements. If a source video is missing, it pauses and responds asking for it.
4. Once all inputs are valid, it calls the `create_promo` tool.
5. The ADK state is updated with the new `promo_id`.
6. The Orchestrator then transitions the state to the **Editing Agent** to ensure the final promo is reframed vertically using the `reframe_video` tool.
7. The combined result is sent back to the frontend to render the status and final video.

## UI Integration (Frontend)
- **Agent Indicators**: The chat UI will visually indicate which agent is currently "speaking" or "working" (e.g., showing an avatar for the Director vs. the Editor).
- **Rich Components**: When an agent finishes a task, it returns a structured payload. The frontend Chat Renderer will parse this payload and mount existing components (like `PromoWorkPage`'s video player or the `KeyMoments` list) directly inside the chat bubble.
- **Human-in-the-Loop (HIL) & Data Collection**: If an agent needs input (e.g., a file upload or choosing between multiple detected faces), it responds with a specialized `form_request` type. The frontend renders an inline form or upload dropzone within the chat bubble for the user to fulfill the requirement.

## Phased Brainstorming/Implementation Strategy
*(Note: Code implementation is currently paused until explicitly instructed by the user).*

1. **ADK Integration Phase**: Add Google ADK to the backend requirements and configure the basic connection to Vertex AI.
2. **Backend Engine Phase**: Build the Agent hierarchy using ADK. Wire it to a new `/api/chat` router.
3. **Frontend UI Phase**: Build the Zustand `useChatStore` and the base `ChatWidget` component.
4. **Integration Phase**: Connect the frontend to the backend and build out the Rich Message renderers for outputs like videos and forms.