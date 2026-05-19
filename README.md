# 💫 PAI / AI Companion System

### RU Adaptation — independently evolved fork

**System Version:** 0.7.1 
**Status:** Beta  
**License:** Maolink Noncommercial License 1.0.0  
**Original source project:** Z-Waif by SugarcaneDefender

---

## 1. Introduction

**PAI / AI Companion System** is a modular platform for building and running a local-first AI companion with memory, voice, visualization, behavioral logic, and configurable runtime policies.

This project started as a fork of the original **Z-Waif**, but has since evolved into an independently developed system with its own architecture, module boundaries, config model, auth flow, memory workflows, and companion-oriented runtime behavior.

The current focus is not only dialogue generation, but also:

- persistent memory and retrieval
- role-aware interaction policies
- active character routing
- voice and synthesis pipelines
- diagnostics and traceability
- modular runtime orchestration
- Telegram bridge and notification-driven social runtime
- visual self-expression pipeline
- initiative-driven background behavior (diary, sleep consolidation, autonomous Telegram)
- groundwork for deeper semi-autonomous behavior

---

## 2. Core Architecture

As of **v0.7.1**, the system follows a module-oriented design with well-defined domain boundaries.

### Main architectural domains

- **core** — orchestration, startup, runtime coordination
- **system** — config/runtime facade and cross-module safe access
- **memory** — hybrid retrieval, anchors, associations, memory workflows
- **moral_matrix** — behavioral evaluation and fallback-safe moral reasoning
- **vision** — capture/inference pipeline, configurable providers
- **voice / tts / rvc** — voice control, synthesis, playback, model integration
- **synthesis** — image generation providers and routes
- **telegram** — notification-driven runtime, bridge, autonomous inbox
- **web_runtime** — runtime endpoints for UI
- **visual_intent_composer / visual_profile_store / visual_prompt_builder** — visual self-expression pipeline
- **storage** — storage service domain

### Key platform principles

- **DB-first configuration**
- **active-character based routing**
- **owner/user role separation**
- **provider failover**
- **modular services instead of monolithic core logic**
- **runtime-safe wrappers and guarded interactions**

---

## 3. What is implemented

### 3.0 v0.7.1 — Unified Media Pipeline & ComfyUI

#### Unified Media/Image Pipeline
- Shared image pipeline used by Sandbox, Synthesis, main chat, and Telegram image flows
- LLM prompt-builder tracing: tool context, generated prompt, negative prompt, provider route, parameters, result media, and vision metadata
- Improved image prompt composition: raw system strings (dates, emotion labels) converted into visual cues; `emotionMood` included only when Moral Matrix has an actual emotion state

#### ComfyUI Provider
- ComfyUI integration with checkpoint discovery, endpoint/resource inspection, and txt2img generation
- ComfyUI-aware generation parameters: width, height, steps, CFG, sampler, scheduler, checkpoint, seed
- Split `sampler` and `scheduler` in Synthesis/Sandbox UI and API payloads
- Provider-level ComfyUI defaults instead of stale local UI defaults

#### Sandbox
- Image pipeline mode: shows generated prompt, tool context, generation route, parameters, traces, and output image
- Dedicated Vision mode for describing input images/screen context without triggering image generation
- Layout fix: panels remain pinned, scrolling contained inside controls/chat/process areas
- Provider/model loading for image generation, including ComfyUI checkpoint selection

#### Telegram
- Telegram generation forced through synchronous paths outside main chat streaming
- Routed Telegram image command, `take_photo`, and test-image flows through the shared media pipeline
- Meaningful image captions generated from vision context instead of generic test text
- Fast repeat-recovery path: reuses already-built context, disables thinking, avoids rerunning full Decision Layer
- Duplicate current-user message deduplication in Telegram history payloads

#### Chat Runtime & Streaming
- Fixed duplicate live-status rendering in main chat
- Fixed reasoning/status overlap during live final-answer streaming
- Longer Ollama stream read timeout; stream stalls converted to structured provider errors
- WebSocket generation errors now emit `run_status=error` and `typing_end` so the UI does not stay stuck

#### UI Polish
- Project UI checkboxes replacing ad-hoc controls
- Library and Sidebar icon/preview control cleanup
- Empty-state text for chat history and memory storage blocks

---

### 3.1 v0.7 — Telegram Runtime & Visual Self-Expression

#### Telegram Notification-Driven Runtime
- Reworked Telegram bridge to notification-first processing: event → normalized notification → sequential worker
- Hardened write safety with sender-level final gate and deny-by-default policy for public chats/channels
- Private-only public reflection delivery flow (read public source, deliver reflection to configured private target)
- Extended observability with outbound target diagnostics and policy-aware audit events

#### Social/Telegram UI & Policy Controls
- Expanded Social Settings: reflection targeting, source selection, quiet hours, initiative cadence, autonomous inbox, tool orchestration controls
- Chat catalog-based selection flows to reduce manual `chat_id` setup
- Improved localization coverage for Telegram/social sections

#### Visual Self-Expression Pipeline
- UI-first visual profile: composer + deterministic prompt builder + profile/history store for stateful image expression
- Visual intent integrated into synthesis and Telegram test-image path

#### Vision Provider Layer
- Configurable `ollama_vision` provider support in the vision module
- Provider capability probe/status endpoint and Vision UI status panel (`configured/supported/unavailable`)
- Ollama model list integration in Vision UI for provider model selection
- Improved Ollama vision error surfacing (HTTP/body diagnostics) and lightweight probe options

#### Diary/Memory
- Continued separation of runtime action logs vs semantic context for model inputs
- Stabilized diary/memory-facing runtime traces and message flow constraints

---

### 3.2 v0.6 — Platform Foundation

#### 3.2.1 Platform & Runtime
- Module-oriented boundaries between `core`, `memory`, `moral_matrix`, `vision`, and `system`
- `SystemModule` facade for runtime/config access
- Interaction policy layer for role-based capabilities
- Safer startup and readiness-first backend launch flow
- Better runtime stability and schema/bootstrap ordering

#### 3.2.2 Auth, Users & Roles
- Full authentication flow:
  - register
  - login
  - refresh
  - logout
- First registered account becomes **owner**
- All next registrations default to **user**
- Frontend guards/interceptors and backend auth services integrated

#### 3.2.3 DB-First Config & Character Management
- DB-first config model with split settings tables
- Runtime-safe config wrappers
- Character catalog endpoints and YAML import flow
- `active_character_id` stored in user settings
- Automatic fallback/backfill if active character is missing

#### 3.2.4 Chat & Realtime Reliability
- Hardened WebSocket pipeline
- Run IDs and stop semantics
- Runtime trace streaming
- Better reconnect/empty-state handling
- Per-run metadata persistence:
  - provider
  - model
  - usage
  - traces
  - timing

#### 3.2.5 Memory & Moral Matrix
- Memory emulator for staged retrieval inspection/debugging
- Expanded knowledge layer:
  - anchors
  - associations
- Owner-scoped access control for memory-related actions
- Safer Moral Matrix provider path and degraded fallback responses

#### 3.2.6 Voice / TTS / RVC
- Expanded voice settings UI with provider-aware controls
- RVC runtime assets and bootstrap services
- Model status / download / import flows
- Refactored TTS manager and provider selection lifecycle
- Safer preview and playback control

#### 3.2.7 Synthesis (Image Generation)
- Dedicated synthesis module and backend routes
- Pluggable image providers
- `Z-Image-Turbo` provider
- Generic Diffusers-based local generation path

#### 3.2.8 Frontend Platform
- New feature pages/modules:
  - auth
  - memory
  - matrix
  - synthesis
  - audit
  - diary
- Shared UI-kit components
- Expanded routing guards
- Updated config mappers for new backend schema

#### 3.2.9 Storage & Paths
- Consolidated model storage layout
- Aligned path constants
- Helper services for XTTS/RVC resources and model path resolution

---

## 4. Current Capabilities

The system already supports:

- local/cloud LLM orchestration
- hybrid memory retrieval
- configurable TTS/STT pipelines
- role-aware auth and access
- active character runtime switching
- diagnostics and runtime trace visibility
- voice model integration
- local image generation (Diffusers, ComfyUI, Z-Image-Turbo, SD-WebUI)
- Telegram bridge with notification-driven runtime and autonomous inbox
- visual self-expression tied to current character state and intent
- configurable vision providers (Ollama vision, Apple Vision)
- quiet hours, initiative cadence, and time-aware background behavior
- modular backend/frontend architecture

This is no longer just a UI wrapper around a model.  
It is becoming a configurable **AI companion runtime**.

---

## 5. Roadmap

### Stage 1 — Core Companion Runtime ✅
- dialogue
- TTS/STT
- memory
- modular backend/frontend
- diagnostics
- config system

### Stage 2 — Personalization & Control ✅
- roles/auth
- active characters
- interaction policy
- expanded voice controls
- localized UI and runtime messaging

### Stage 3 — Platform Maturity ✅ / in progress
- synthesis
- traceable realtime runs
- memory inspection tools
- stronger provider lifecycle
- safer config/runtime boundaries

### Stage 4 — Semi-Autonomy ✅ / in progress
- 🔄 self-initiative (initiative monitor active, continuing)
- ✅ notification-driven event handling
- ✅ time-aware behavior / quiet hours
- ✅ controlled proactive communication (autonomous Telegram)
- ✅ Telegram/social bridge
- ⏳ external/public-source reflection (private delivery exists, full flow in progress)

### Stage 5 — Full Companion Environment ⏳
- deeper autonomy
- stronger long-term continuity
- richer behavioral modeling
- controlled environment/tool interaction

---

## 6. Technical Highlights

- **DB-first config**
- **active character model**
- **owner/user role model**
- **interaction policy layer**
- **WebSocket trace streaming**
- **hybrid memory retrieval**
- **provider failover**
- **pluggable synthesis**
- **voice + RVC/XTTS integration**
- **module-oriented backend boundaries**

---

## 7. Project Positioning

This repository is best understood as an **independently evolving AI companion platform** that originated from a Z-Waif fork, but now follows its own architectural direction.

The project is focused on:
- companion behavior
- persistent context
- runtime safety
- modular orchestration
- future semi-autonomous flows

rather than being only a traditional chatbot frontend.

---

## 8. Licensing and Credits

### This repository
Most of the current codebase is distributed under:

**Maolink Noncommercial License 1.0.0**

Commercial use is not allowed.

### Original project
Original Z-Waif by **SugarcaneDefender**:  
https://github.com/SugarcaneDefender/z-waif

The original project remains a separate work under its own license.

### Derived / copied files
Some explicitly identified files may still retain origin from the source project and should be treated according to their original license terms.

---

## 9. Contacts

**Project / adaptation / current development:**  
https://github.com/MaolinkLife/pai-manager

**Telegram:** @MaolinkLife  
**Email:** maolink686@gmail.com