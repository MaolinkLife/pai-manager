# 💫 PAI / AI Companion System

### Русская адаптация — независимо развиваемый форк

**Версия системы:** 0.6  
**Статус:** Beta  
**Лицензия:** Maolink Noncommercial License 1.0.0  
**Оригинальный исходный проект:** Z-Waif by SugarcaneDefender

---

## 1. Введение

**Z-Waif / AI Companion System** — это модульная платформа для запуска и развития локального AI-компаньона с памятью, голосом, визуальными модулями, поведенческой логикой и настраиваемой runtime-архитектурой.

Проект начинался как форк оригинального **Z-Waif**, но со временем эволюционировал в отдельную, самостоятельно развиваемую систему со своей архитектурой, собственными модулями, DB-first конфигурацией, авторизацией, активным персонажем, политиками взаимодействия и фундаментом для полуавтономного поведения.

Текущий фокус проекта — не только генерация диалога, но и:

- долговременный контекст и память
- role-aware политика взаимодействия
- маршрутизация через активного персонажа
- голосовые и synthesis-пайплайны
- диагностика и трассировка runtime
- модульная orchestration-архитектура
- фундамент для инициативности и semi-autonomy

---

## 2. Архитектура системы

Начиная с **v0.6**, проект следует более выраженной модульной структуре.

### Основные домены

- **core** — orchestration, startup, runtime-координация
- **system** — facade для config/runtime и безопасного межмодульного доступа
- **memory** — гибридный поиск, anchors, associations, memory workflows
- **moral_matrix** — поведенческая оценка и моральный слой
- **vision** — capture/inference pipeline
- **voice / tts / rvc** — голосовое управление, синтез, воспроизведение, интеграция голосовых моделей
- **synthesis** — генерация изображений и pluggable image providers

### Ключевые принципы платформы

- **DB-first конфигурация**
- **маршрутизация через active character**
- **разделение ролей owner / user**
- **provider failover**
- **модульные сервисы вместо монолитной core-логики**
- **runtime-safe wrappers и guarded interactions**

---

## 3. Что реализовано в v0.6

### 3.1. Платформа и runtime
- Модульные границы между `core`, `memory`, `moral_matrix`, `vision` и `system`
- `SystemModule` facade для runtime/config доступа
- Interaction policy layer для role-based capabilities
- Более безопасный startup pipeline и readiness-first запуск backend
- Улучшенная устойчивость runtime и bootstrap/schema ordering

### 3.2. Авторизация, пользователи и роли
- Полный auth flow:
  - регистрация
  - вход
  - refresh
  - logout
- Первый зарегистрированный аккаунт становится **owner**
- Все последующие по умолчанию получают роль **user**
- Frontend guards/interceptors и backend auth services интегрированы

### 3.3. DB-first config и управление персонажами
- DB-first модель конфигурации с разделёнными таблицами настроек
- Runtime-safe wrappers для доступа к настройкам
- Character catalog endpoints и YAML import flow
- `active_character_id` в пользовательских настройках
- Fallback/backfill логика, если активный персонаж отсутствует

### 3.4. Чат и realtime-надёжность
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

### 3.5. Memory и Moral Matrix
- Memory emulator для staged retrieval inspection и отладки
- Расширенный knowledge layer:
  - anchors
  - associations
- Owner-scoped access control для memory-related действий
- Более безопасный Moral Matrix provider path и degraded fallback responses

### 3.6. Voice / TTS / RVC
- Расширен voice settings UI с provider-aware controls
- Добавлены runtime assets и bootstrap-сервисы для RVC
- Model status / download / import flows
- Переработан TTS manager и lifecycle выбора провайдера
- Более безопасная генерация preview и playback control

### 3.7. Synthesis (генерация изображений)
- Выделен отдельный synthesis module и backend routes
- Поддержка pluggable image providers
- Добавлен `Z-Image-Turbo`
- Добавлен generic Diffusers-based путь для локальной генерации

### 3.8. Frontend-платформа
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

### 3.9. Storage и пути
- Упорядочена структура хранения моделей
- Согласованы path constants
- Добавлены helper-сервисы для XTTS/RVC ресурсов и model path resolution

---

## 4. Текущие возможности

Система уже поддерживает:

- orchestration локальных и облачных LLM
- гибридную память и retrieval
- настраиваемые TTS/STT пайплайны
- role-aware auth и access control
- runtime switching активного персонажа
- диагностику и runtime trace visibility
- интеграцию голосовых моделей
- локальную генерацию изображений
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

### Этап 4 — Semi-Autonomy 🔄
- self-initiative
- notification-driven event handling
- поведение с учётом времени суток
- quiet hours / activity windows
- controlled proactive communication
- Telegram / social bridge
- рефлексия на внешние источники

### Этап 5 — Полноценная companion environment ⏳
- более глубокая автономность
- усиленная долговременная непрерывность
- richer behavioral modeling
- controlled environment/tool interaction

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
**A:** Да. Начиная с v0.6 есть synthesis module с pluggable providers, включая `Z-Image-Turbo` и локальный Diffusers-based путь.

**Q10: Это уже автономный AI-компаньон?**  
**A:** Не полностью. Текущее состояние ближе к платформе для AI-компаньона с фундаментом под semi-autonomy: память, поведенческие политики, runtime orchestration, инициативность и social/notification-driven сценарии находятся в активной разработке.

---

## 10. Контакты

**Текущий проект / адаптация / разработка:**  
https://github.com/MaolinkLife/z-waif-ru-adaptation

**Telegram:** @MaolinkLife  
**Email:** maolink686@gmail.com