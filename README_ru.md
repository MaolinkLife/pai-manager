# 💫 PAI / AI Companion System

### Русская адаптация — независимо развиваемый форк

**Версия системы:** 0.9.2  
**Статус:** Beta  
**Лицензия:** Maolink Noncommercial License 1.0.0  
**Оригинальный исходный проект:** Z-Waif by SugarcaneDefender

---

## 1. Введение

**PAI / AI Companion System** — это модульная платформа для запуска и развития локального AI-компаньона с памятью, голосом, визуальными модулями, поведенческой логикой и настраиваемой runtime-архитектурой.

Проект начинался как форк оригинального **Z-Waif**, но со временем эволюционировал в отдельную, самостоятельно развиваемую систему со своей архитектурой, собственными модулями, DB-first конфигурацией, авторизацией, активным персонажем, политиками взаимодействия и фундаментом для полуавтономного поведения.

Текущий фокус проекта — не только генерация диалога, но и:

- долговременный контекст и память
- role-aware политика взаимодействия
- маршрутизация через активного персонажа
- голосовые и synthesis-пайплайны
- диагностика и трассировка runtime
- модульная orchestration-архитектура
- Telegram bridge и notification-driven social runtime
- pipeline визуального самовыражения
- инициативное фоновое поведение (дневник, sleep consolidation, автономный Telegram)
- фундамент для более глубокой semi-autonomy

---

## 2. Архитектура системы

Начиная с **v0.9.2**, проект следует модульной структуре с чёткими доменными границами.

### Основные домены

- **core** — orchestration, startup, runtime-координация
- **system** — facade для config/runtime и безопасного межмодульного доступа
- **memory** — гибридный поиск, anchors, associations, memory workflows
- **moral_matrix** — поведенческая оценка, эмоциональные следы (угасание / прощение / шрамы), внутренний голос
- **validator / language_guard / confidence / factuality / self_watcher** — пост-генерационный compliance-пайплайн (opt-in, never-raise, вывод не модифицируется)
- **debug_vault** — курируемое хранилище аномалий с review-процессом
- **reminders** — напоминания и будильники (захват из чата + доставка по расписанию)
- **vision** — capture/inference pipeline, настраиваемые провайдеры
- **voice / tts / rvc** — голосовое управление, синтез, воспроизведение (Qwen3-TTS, sherpa-onnx STT)
- **llama_cpp** — встроенный llama-server как полноценный провайдер (генерация / analyzer / moral / vision)
- **synthesis** — генерация изображений и pluggable image providers
- **telegram** — notification-driven runtime, bridge, автономный inbox
- **web_runtime** — runtime endpoints для UI
- **visual_intent_composer / visual_profile_store / visual_prompt_builder** — pipeline визуального самовыражения
- **storage** — сервисный домен хранилища

### Ключевые принципы платформы

- **DB-first конфигурация**
- **маршрутизация через active character**
- **разделение ролей owner / user**
- **provider failover**
- **модульные сервисы вместо монолитной core-логики**
- **runtime-safe wrappers и guarded interactions**

---

## 3. Что реализовано

### 3.0. v0.8.0–0.9.2 — Эмоциональное ядро, compliance-пайплайн и напоминания

#### Эмоциональное ядро (0.8.0)
- Угасание эмоций: следы ослабевают по ночам с per-trace `decay_rate`, но не ниже `persistence_floor` — эмоции отпускаются, память остаётся
- Прощение: компенсирующее поведение пользователя смягчает старые негативные следы
- Эмоциональные шрамы: настраиваемые триггеры (интенты/тоны/ключевые слова) создают стойкие следы с усиленной интенсивностью
- Внутренний голос: одна короткая фраза от первого лица за ход о текущем чувстве

#### Compliance и debug-инфраструктура (0.9.0)
- Audit-логи в БД (JSONL-фолбэк на boot-окно), `MODE=dev/prod`, ночная retention-политика по severity
- Пять opt-in never-raise проверок после генерации (вывод никогда не изменяется): **Validator** (LLM-судья соответствия инструкциям), **Language Guard** (проверка языка ответа без LLM), **Confidence** (уверенность в ответе), **Factuality** (сверка фактов с локальной памятью, без веба), **Self-Watcher** (ожидание-vs-реальность эмоций + ночной самоанализ в дневнике)
- DebugVault: курируемое хранилище аномалий с review-процессом + UI-таб
- Нарративный дневник: ночная запись получила свободный текст от первого лица на языке пользователя
- llama.cpp-паритет (генерация/analyzer/moral/vision), Qwen3-TTS, sherpa-onnx STT

#### UI Settings Pass (0.9.1)
- Все backend-настройки доступны из UI: moral (угасание/прощение/шрамы/внутренний голос), консолидация памяти и дневник, весь compliance-таб, llama.cpp-провайдеры, Qwen-TTS, sherpa STT, retention
- Разделение «язык интерфейса» (system.language) и «язык генерации» (User.language)

#### Напоминания, дневник в контексте и стабилизация (0.9.2)
- **Напоминания**: «разбуди в 7», «напомни через 2 часа» — захват из естественной фразы в чате (с учётом таймзоны пользователя), срабатывание по расписанию, доставка живой репликой персонажа в открытый чат, REST + страница «Напоминания»
- **Дневник в контексте**: последние дни (narrative + самоанализ + настроение) подмешиваются в контекст генерации — непрерывность «вчера/сегодня» без LLM-затрат
- **Auto-reroll**: провал Validator/LanguageGuard перегенерирует ответ с корректирующим хинтом до отправки (sync-путь, по умолчанию выключен)
- **Reasoning-модели**: разговорные пути без лимита токенов (`num_predict: -1`, паритет с open-webui — лечит хронические пустые ответы), сервисные вызовы — короткие лимиты без размышлений
- Compliance-бейджи в чате с тултипами, голосовой ввод в полном паритете с чатом, нотификации с мягким звуком вне страницы чата, таймстемпы логов в таймзоне пользователя

---

### 3.1. v0.7.1 — Единый медиапайплайн и ComfyUI

#### Единый медиапайплайн
- Общий image pipeline для Sandbox, Synthesis, основного чата и Telegram
- Трассировка prompt-builder: tool context, сгенерированный промпт, negative prompt, маршрут провайдера, параметры, результат, vision-метаданные
- Улучшенная композиция image prompt: системные строки (даты, метки эмоций) преобразуются в визуальные описательные cues; `emotionMood` включается только при наличии реального состояния из Moral Matrix

#### Провайдер ComfyUI
- Интеграция ComfyUI: обнаружение checkpoint'ов, инспекция endpoint/ресурсов, txt2img генерация
- ComfyUI-специфичные параметры генерации: width, height, steps, CFG, sampler, scheduler, checkpoint, seed
- Разделение `sampler` и `scheduler` в UI и API payloads Synthesis/Sandbox
- Используются дефолты ComfyUI на уровне провайдера вместо устаревших локальных значений

#### Sandbox
- Режим image pipeline: показывает сгенерированный промпт, tool context, маршрут генерации, параметры, трассы и итоговое изображение
- Отдельный Vision mode для описания изображений/экрана без запуска генерации
- Исправлен layout: панели остаются зафиксированными, скролл ограничен внутри областей controls/chat/process
- Загрузка провайдера/модели для генерации, включая выбор ComfyUI checkpoint

#### Telegram
- Генерация Telegram принудительно идёт через синхронные пути, минуя streaming чата
- Telegram image command, `take_photo` и test-image роутятся через единый media pipeline
- Осмысленные подписи к изображениям на основе vision context вместо generic-текста
- Быстрый повтор-recovery: переиспользует уже построенный context, отключает thinking, не перезапускает полный Decision Layer
- Дедупликация сообщений текущего пользователя в истории Telegram payloads

#### Чат Runtime & Streaming
- Исправлено дублирование live-status рендеринга в основном чате
- Исправлено перекрытие reasoning/status во время live final-answer streaming
- Увеличен таймаут чтения Ollama stream; зависания стрима конвертируются в структурированные ошибки провайдера
- Ошибки генерации WebSocket теперь эмитят `run_status=error` и `typing_end`, чтобы UI не зависал в running состоянии

#### UI-полировка
- Замена ad-hoc чекбоксов на проектные UI checkboxes
- Cleanup иконок и превью в Library и Sidebar
- Empty-state текст для блоков истории чата и памяти

---

### 3.2. v0.7 — Telegram Runtime и визуальное самовыражение

#### Notification-Driven Telegram Runtime
- Переработан Telegram bridge на notification-first обработку: event → normalized notification → sequential worker
- Усиленная write safety: sender-level final gate и deny-by-default для публичных чатов/каналов
- Private-only reflection delivery (читаем публичный источник, доставляем рефлексию в приватный таргет)
- Расширенная observability: диагностика outbound target, policy-aware audit events

#### Social/Telegram UI и политики
- Расширенные Social Settings: таргет рефлексии, выбор источника, quiet hours, каденция инициативы, автономный inbox, контроль tool orchestration
- Выбор чатов через catalog вместо ручного ввода `chat_id`
- Улучшенная локализация Telegram/social секций

#### Pipeline визуального самовыражения
- UI-first visual profile: composer + deterministic prompt builder + profile/history store для stateful image expression
- Visual intent интегрирован в synthesis и Telegram test-image path

#### Vision Provider Layer
- Настраиваемый провайдер `ollama_vision` в модуле vision
- Capability probe/status endpoint и статус-панель в Vision UI (`configured/supported/unavailable`)
- Список моделей Ollama в Vision UI для выбора модели провайдера
- Улучшенная диагностика ошибок Ollama vision (HTTP/body diagnostics) и облегчённый probe

#### Дневник и память
- Продолжено разделение runtime action logs и семантического контекста для модельных входов
- Стабилизированы runtime traces и ограничения message flow в Telegram-путях

---

### 3.3. v0.6 — Фундамент платформы

#### 3.2.1. Платформа и runtime
- Модульные границы между `core`, `memory`, `moral_matrix`, `vision` и `system`
- `SystemModule` facade для runtime/config доступа
- Interaction policy layer для role-based capabilities
- Более безопасный startup pipeline и readiness-first запуск backend
- Улучшенная устойчивость runtime и bootstrap/schema ordering

#### 3.2.2. Авторизация, пользователи и роли
- Полный auth flow:
  - регистрация
  - вход
  - refresh
  - logout
- Первый зарегистрированный аккаунт становится **owner**
- Все последующие по умолчанию получают роль **user**
- Frontend guards/interceptors и backend auth services интегрированы

#### 3.2.3. DB-first config и управление персонажами
- DB-first модель конфигурации с разделёнными таблицами настроек
- Runtime-safe wrappers для доступа к настройкам
- Character catalog endpoints и YAML import flow
- `active_character_id` в пользовательских настройках
- Fallback/backfill логика, если активный персонаж отсутствует

#### 3.2.4. Чат и realtime-надёжность
- Усилен WebSocket pipeline
- Run IDs и stop semantics
- Runtime trace streaming
- Улучшено reconnect / empty-state поведение
- Сохранение метаданных по каждому run:
  - provider
  - model
  - usage
  - traces
  - timing

#### 3.2.5. Memory и Moral Matrix
- Memory emulator для staged retrieval inspection и отладки
- Расширенный knowledge layer:
  - anchors
  - associations
- Owner-scoped access control для memory-related действий
- Более безопасный Moral Matrix provider path и degraded fallback responses

#### 3.2.6. Voice / TTS / RVC
- Расширен voice settings UI с provider-aware controls
- Добавлены runtime assets и bootstrap-сервисы для RVC
- Model status / download / import flows
- Переработан TTS manager и lifecycle выбора провайдера
- Более безопасная генерация preview и playback control

#### 3.2.7. Synthesis (генерация изображений)
- Выделен отдельный synthesis module и backend routes
- Поддержка pluggable image providers
- Добавлен `Z-Image-Turbo`
- Добавлен generic Diffusers-based путь для локальной генерации

#### 3.2.8. Frontend-платформа
- Новые feature-модули и страницы:
  - auth
  - memory
  - matrix
  - synthesis
  - audit
  - diary
- Общий UI-kit
- Расширенные routing guards
- Обновлённые config mappers под новую backend schema

#### 3.2.9. Storage и пути
- Упорядочена структура хранения моделей
- Согласованы path constants
- Добавлены helper-сервисы для XTTS/RVC ресурсов и model path resolution

---

## 4. Текущие возможности

Система уже поддерживает:

- orchestration локальных и облачных LLM
- гибридную память и retrieval
- эмоциональное состояние с угасанием, прощением, шрамами и внутренним голосом
- compliance-пайплайн после генерации (validator, language guard, confidence, factuality, self-watcher) с бейджами в чате и опциональным auto-reroll
- напоминания и будильники из естественных фраз в чате с доставкой in-character
- день-к-дню непрерывность через дневник в контексте генерации
- настраиваемые TTS/STT пайплайны (Qwen3-TTS, XTTS/RVC, sherpa-onnx, faster-whisper)
- role-aware auth и access control
- runtime switching активного персонажа
- диагностику и runtime trace visibility
- интеграцию голосовых моделей
- локальную генерацию изображений (Diffusers, ComfyUI, Z-Image-Turbo, SD-WebUI)
- Telegram bridge с notification-driven runtime и автономным inbox
- визуальное самовыражение, привязанное к состоянию и намерению активного персонажа
- настраиваемые vision-провайдеры (Ollama vision, Apple Vision)
- quiet hours, каденцию инициативы и time-aware фоновое поведение
- модульную backend/frontend архитектуру

Это уже не просто UI-обвязка вокруг модели.  
Проект постепенно становится **runtime-системой для AI-компаньона**.

---

## 5. Дорожная карта

### Этап 1 — Базовый runtime компаньона ✅
- диалог
- TTS/STT
- память
- модульный backend/frontend
- диагностика
- config system

### Этап 2 — Персонализация и контроль ✅
- роли и auth
- active characters
- interaction policy
- расширенное voice control
- локализация интерфейса и runtime messaging

### Этап 3 — Зрелость платформы ✅ / в процессе
- synthesis
- traceable realtime runs
- memory inspection tools
- более надёжный provider lifecycle
- безопасные config/runtime boundaries

### Этап 4 — Semi-Autonomy ✅ / в процессе
- 🔄 self-initiative (initiative monitor активен, продолжается)
- ✅ notification-driven event handling
- ✅ поведение с учётом времени суток / quiet hours
- ✅ controlled proactive communication (автономный Telegram)
- ✅ Telegram / social bridge
- ✅ напоминания / будильники с доставкой in-character
- ✅ ночной самоанализ (Self-Watcher → дневник)
- ⏳ рефлексия на внешние источники (приватная доставка есть, полный flow в разработке)

### Этап 5 — Полноценная companion environment ⏳
- более глубокая автономность
- осознание собственных возможностей и уточняющие вопросы
- action-команды («напомни И сделай»)
- privacy-разделение данных owner в социальных каналах
- усиленная долговременная непрерывность (retrieval graph, memory snapshots)
- richer behavioral modeling
- controlled environment/tool interaction (canvas / co-editing, sandboxed execution)

---

## 6. Технические особенности

- **DB-first config**
- **модель active character**
- **ролевая модель owner / user**
- **interaction policy layer**
- **WebSocket trace streaming**
- **гибридная память**
- **provider failover**
- **pluggable synthesis**
- **voice + RVC/XTTS integration**
- **модульные backend boundaries**

---

## 7. Позиционирование проекта

Этот репозиторий лучше понимать как **самостоятельно развивающуюся платформу AI-компаньона**, выросшую из форка Z-Waif, но уже идущую по собственной архитектурной траектории.

Фокус проекта сейчас — это:

- поведение компаньона
- долговременный контекст
- runtime-безопасность
- модульная orchestration-архитектура
- фундамент для semi-autonomous flow

а не просто интерфейс для обычного чат-бота.

---

## 8. Лицензирование и благодарности

### Код этого репозитория
Основная часть текущей кодовой базы распространяется по лицензии:

**Maolink Noncommercial License 1.0.0**

Коммерческое использование запрещено.

### Оригинальный проект
Оригинальный Z-Waif от **SugarcaneDefender**:  
https://github.com/SugarcaneDefender/z-waif

Оригинальный проект продолжает существовать как отдельная работа и распространяется по собственной лицензии.

### Производные / заимствованные файлы
Отдельные явно указанные файлы могут сохранять происхождение от исходного проекта и должны рассматриваться в рамках условий их исходной лицензии.

---

## 9. FAQ

**Q1: Нужно ли вручную редактировать конфиги?**  
**A:** В большинстве случаев — нет. Основные настройки доступны через UI. При этом система уже использует DB-first конфигурацию, поэтому ручная правка файлов не является основным способом управления.

**Q2: Какие LLM-провайдеры поддерживаются?**  
**A:** Локальные и внешние. Базовый сценарий — локальная работа через **Ollama**, при необходимости можно использовать внешние API и fallback-цепочки провайдеров.

**Q3: Поддерживается ли русский язык?**  
**A:** Да. Проект изначально активно адаптировался под RU-сценарий: интерфейс, часть runtime-сообщений, STT/TTS-пайплайны и общая работа с русскоязычным контекстом.

**Q4: Может ли система работать без интернета?**  
**A:** Да, частично или полностью — зависит от выбранных провайдеров. При локальном сценарии с Ollama и локальными модулями проект может работать офлайн. Внешние API, облачный TTS или внешняя генерация, разумеется, требуют сеть.

**Q5: Это всё ещё просто форк оригинального Z-Waif?**  
**A:** Нет, проект давно ушёл дальше простой адаптации. Он вырос в отдельно развиваемую систему со своей архитектурой, DB-first config, auth flow, role model, active character routing, synthesis, memory workflows и собственным roadmap.

**Q6: Что такое active character?**  
**A:** Это активный персонаж, через которого сейчас маршрутизируется runtime: история, поведение, настройки и связанный контекст привязываются к текущему выбранному character profile.

**Q7: Для чего нужны роли owner / user?**  
**A:** Для разграничения доступа и возможностей. Первый зарегистрированный пользователь становится owner, а дальнейшие аккаунты получают роль user. Это используется в interaction policy и доступе к некоторым действиям/данным.

**Q8: Есть ли в проекте память?**  
**A:** Да. Система уже использует memory workflows, hybrid retrieval, knowledge layer (`anchors`, `associations`) и инструменты отладки вроде memory emulator.

**Q9: Поддерживается ли генерация изображений?**  
**A:** Да. Synthesis module с pluggable providers: `Z-Image-Turbo`, Diffusers, ComfyUI, SD-WebUI. Начиная с v0.7.1 все пути генерации (Sandbox, Synthesis, чат, Telegram) объединены в единый media pipeline.

**Q10: Это уже автономный AI-компаньон?**  
**A:** Не полностью. Текущее состояние ближе к платформе для AI-компаньона с фундаментом под semi-autonomy: память, поведенческие политики, runtime orchestration, инициативность и social/notification-driven сценарии находятся в активной разработке.

---

## 10. Контакты

**Текущий проект / адаптация / разработка:**  
https://github.com/MaolinkLife/pai-manager

**Telegram:** @MaolinkLife  
**Email:** maolink686@gmail.com