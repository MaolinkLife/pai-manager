# 💫 PAI / AI Companion System

### RU Adaptation — independently evolved fork

**System Version:** 0.6 
**Status:** Beta  
**License:** Maolink Noncommercial License 1.0.0  
**Original source project:** Z-Waif by SugarcaneDefender

---

## 1. Introduction

**Z-Waif / AI Companion System** is a modular platform for building and running a local-first AI companion with memory, voice, visualization, behavioral logic, and configurable runtime policies.

This project started as a fork of the original **Z-Waif**, but has since evolved into an independently developed system with its own architecture, module boundaries, config model, auth flow, memory workflows, and companion-oriented runtime behavior.

The current focus is not only dialogue generation, but also:

- persistent memory and retrieval
- role-aware interaction policies
- active character routing
- voice and synthesis pipelines
- diagnostics and traceability
- modular runtime orchestration
- groundwork for initiative and semi-autonomous behavior

---

## 2. Core Architecture

As of **v0.6**, the system follows a more explicit module-oriented design.

### Main architectural domains

- **core** — orchestration, startup, runtime coordination
- **system** — config/runtime facade and cross-module safe access
- **memory** — hybrid retrieval, anchors, associations, memory workflows
- **moral_matrix** — behavioral evaluation and fallback-safe moral reasoning
- **vision** — capture/inference pipeline
- **voice / tts / rvc** — voice control, synthesis, playback, model integration
- **synthesis** — image generation providers and routes

### Key platform principles

- **DB-first configuration**
- **active-character based routing**
- **owner/user role separation**
- **provider failover**
- **modular services instead of monolithic core logic**
- **runtime-safe wrappers and guarded interactions**

---

## 3. What is implemented in v0.6

### 3.1 Platform & Runtime
- Module-oriented boundaries between `core`, `memory`, `moral_matrix`, `vision`, and `system`
- `SystemModule` facade for runtime/config access
- Interaction policy layer for role-based capabilities
- Safer startup and readiness-first backend launch flow
- Better runtime stability and schema/bootstrap ordering

### 3.2 Auth, Users & Roles
- Full authentication flow:
  - register
  - login
  - refresh
  - logout
- First registered account becomes **owner**
- All next registrations default to **user**
- Frontend guards/interceptors and backend auth services integrated

### 3.3 DB-First Config & Character Management
- DB-first config model with split settings tables
- Runtime-safe config wrappers
- Character catalog endpoints and YAML import flow
- `active_character_id` stored in user settings
- Automatic fallback/backfill if active character is missing

### 3.4 Chat & Realtime Reliability
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

### 3.5 Memory & Moral Matrix
- Memory emulator for staged retrieval inspection/debugging
- Expanded knowledge layer:
  - anchors
  - associations
- Owner-scoped access control for memory-related actions
- Safer Moral Matrix provider path and degraded fallback responses

### 3.6 Voice / TTS / RVC
- Expanded voice settings UI with provider-aware controls
- RVC runtime assets and bootstrap services
- Model status / download / import flows
- Refactored TTS manager and provider selection lifecycle
- Safer preview and playback control

### 3.7 Synthesis (Image Generation)
- Dedicated synthesis module and backend routes
- Pluggable image providers
- `Z-Image-Turbo` provider
- Generic Diffusers-based local generation path

### 3.8 Frontend Platform
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

### 3.9 Storage & Paths
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
- local image generation support
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

### Stage 4 — Semi-Autonomy 🔄
- self-initiative
- notification-driven event handling
- time-aware behavior
- quiet hours / activity windows
- controlled proactive communication
- Telegram/social bridge
- external/public-source reflection

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
https://github.com/MaolinkLife/z-waif-ru-adaptation

**Telegram:** @MaolinkLife  
**Email:** maolink686@gmail.com