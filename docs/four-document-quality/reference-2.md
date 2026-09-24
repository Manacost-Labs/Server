# Manacost Design Quality System
## HearthPulse / hs-manacost.ru

## Цель

Построить систему, в которой Codex и другие AI-агенты:

- не придумывают стили заново при каждом изменении;
- сохраняют единые цвета, spacing, typography и компоненты;
- аккуратно используют игровые ассеты;
- не ломают существующий дизайн при небольших правках;
- автоматически проверяют responsive, SVG, CSS, contrast и visual regressions;
- тратят минимум LLM-токенов на задачи, которые можно проверить обычными инструментами.

Главный принцип:

> AI должен не “рисовать интерфейс с нуля”, а работать внутри жёстко определённой визуальной системы.

---

# 1. Итоговый pipeline

```text
UI task
   ↓
Design context
   ↓
Component registry
   ↓
Design tokens
   ↓
Asset rules
   ↓
Codex implementation
   ↓
TypeScript / CSS checks
   ↓
Storybook
   ↓
Playwright screenshots
   ↓
Visual diff
   ↓
Computed-style checks
   ↓
Accessibility
   ↓
Only failures → Codex
```

---

# 2. Design System как единый источник истины

Для каждого проекта должен существовать обязательный design contract.

Пример:

```text
design/
├── tokens/
├── typography/
├── components/
├── icons/
├── motion/
├── layouts/
├── assets/
└── DESIGN-SYSTEM.md
```

`DESIGN-SYSTEM.md` должен содержать:

- основные цвета;
- semantic colors;
- typography;
- spacing scale;
- border-radius;
- shadows;
- container widths;
- breakpoints;
- component states;
- animation rules;
- image/asset rules;
- запрещённые визуальные паттерны.

Codex читает этот файл перед UI-задачей.

---

# 3. Design Tokens

Не использовать случайные значения:

```css
padding: 17px;
color: #17283a;
border-radius: 11px;
transition: 237ms;
```

Использовать токены:

```css
padding: var(--space-4);
color: var(--surface-card);
border-radius: var(--radius-md);
transition-duration: var(--motion-default);
```

Пример базовой шкалы:

```css
--space-1: 4px;
--space-2: 8px;
--space-3: 12px;
--space-4: 16px;
--space-5: 20px;
--space-6: 24px;
--space-8: 32px;
--space-10: 40px;

--radius-sm: 6px;
--radius-md: 10px;
--radius-lg: 16px;

--font-xs: 12px;
--font-sm: 14px;
--font-md: 16px;
--font-lg: 20px;
--font-xl: 24px;
```

Рекомендуемый инструмент:

Style Dictionary  
https://github.com/style-dictionary/style-dictionary

---

# 4. Semantic Tokens

Использовать трёхуровневую структуру:

```text
primitive
↓
semantic
↓
component
```

Пример:

```text
blue-500
↓
accent-primary
↓
button-primary-background
```

Это позволяет менять тему сайта без ручной замены HEX по проекту.

---

# 5. Component Registry

Codex не должен создавать новую кнопку, если уже есть `Button`.

Создать реестр:

```text
Button
Card
Badge
Tabs
Tooltip
Modal
Dropdown
Table
Pagination
ArticleCard
DeckCard
StatCard
Hero
SearchInput
FilterBar
```

Перед созданием нового UI:

```text
есть подходящий компонент?
↓
да → переиспользовать
нет → создать новый
```

Рекомендуемый инструмент:

Storybook  
https://github.com/storybookjs/storybook

---

# 6. Shared Manacost Design System

Имеет смысл вынести общие primitives в пакет:

```text
@manacost/design-system
```

Структура:

```text
packages/design-system/
├── tokens/
├── components/
├── typography/
├── icons/
├── motion/
├── layouts/
└── utilities/
```

HearthPulse и hs-manacost могут иметь разные темы, но одинаковую базовую систему.

---

# 7. CSS Quality Gate

Проверять CSS автоматически.

Pipeline:

```text
Stylelint
↓
raw-color check
↓
spacing check
↓
specificity check
↓
!important check
↓
duplicate declarations
↓
invalid tokens
```

Stylelint  
https://github.com/stylelint/stylelint

Можно написать собственные правила:

```text
запрет:
#123456
padding: 13px
border-radius: 17px
transition: 333ms
!important
```

если значение не входит в design system.

---

# 8. Computed Style Validator

Очень полезный собственный инструмент.

Playwright открывает страницу и получает:

```js
getComputedStyle(element)
```

Проверяет реальные значения.

Пример:

```text
Button standard

expected:
height: 40px
radius: 10px
font-size: 14px
padding-x: 16px

actual:
height: 43px ❌
radius: 11px ❌
font-size: 15px ❌
```

Это позволяет ловить визуальную рассинхронизацию без LLM.

---

# 9. Visual Regression

Перед изменением:

```text
desktop screenshot
tablet screenshot
mobile screenshot
```

После изменения:

```text
new screenshots
↓
visual diff
```

Использовать:

Playwright  
https://github.com/microsoft/playwright

или:

Lost Pixel  
https://github.com/lost-pixel/lost-pixel

BackstopJS  
https://github.com/garris/BackstopJS

---

# 10. Screenshot-driven workflow

Для любой значимой UI-задачи:

```text
BEFORE
↓
screenshots
↓
implement
↓
AFTER
↓
screenshots
↓
visual diff
```

Codex получает только проблемные области.

Это гораздо дешевле, чем просить AI заново анализировать всю страницу.

---

# 11. Typography Guard

Зафиксировать:

```text
font families
font weights
font sizes
line heights
letter spacing
heading scale
body scale
caption scale
```

Пример:

```text
H1: 32/38
H2: 26/32
H3: 22/28
Body: 16/24
Small: 14/20
Caption: 12/16
```

Не разрешать случайные `15px`, `18px`, `21px`, если для них нет token.

---

# 12. Spacing Guard

Использовать ограниченную шкалу:

```text
4
8
12
16
20
24
32
40
48
64
```

AI не должен создавать:

```text
13px
17px
29px
37px
```

без явной причины.

---

# 13. Button Consistency

Все кнопки должны идти через единый компонент.

Пример variants:

```text
primary
secondary
ghost
danger
link
```

Sizes:

```text
sm
md
lg
```

States:

```text
default
hover
active
focus
disabled
loading
```

Нельзя создавать отдельные CSS-классы кнопок внутри страниц.

---

# 14. Icon / SVG System

Все SVG должны проходить общий pipeline.

```text
SVG
↓
SVGO
↓
normalize viewBox
↓
remove metadata
↓
normalize dimensions
↓
replace colors with currentColor where possible
↓
Icon component
```

SVGO  
https://github.com/svg/svgo

Правила:

```text
16px
20px
24px
32px
```

Для UI-иконок использовать один визуальный стиль.

---

# 15. Motion System

Анимации тоже должны быть частью design system.

Пример:

```css
--motion-fast: 120ms;
--motion-default: 180ms;
--motion-slow: 280ms;

--ease-standard: cubic-bezier(...);
--ease-enter: cubic-bezier(...);
--ease-exit: cubic-bezier(...);
```

Codex не должен создавать:

```css
transition: all 437ms ease;
```

---

# 16. Motion Rules

Использовать animation только когда она:

- объясняет изменение состояния;
- показывает появление/исчезновение;
- помогает понять hierarchy;
- улучшает navigation feedback.

Не использовать animation только ради “красивости”.

Учитывать:

```css
@media (prefers-reduced-motion: reduce)
```

---

# 17. Responsive Guard

Проверять как минимум:

```text
375 px
768 px
1024 px
1440 px
```

Для HearthPulse особенно проверять:

- таблицы;
- deck/stat cards;
- filters;
- navigation;
- hero;
- charts;
- long Hearthstone names;
- mobile cards.

---

# 18. Layout Constraints

Заранее определить:

```text
container max width
page gutters
grid
sidebar width
content width
section spacing
card gap
```

Например:

```text
mobile gutter: 16px
tablet gutter: 24px
desktop gutter: 32px
content max-width: 1280px
```

AI не должен каждый раз выбирать их самостоятельно.

---

# 19. Accessibility Guard

Использовать:

axe-core  
https://github.com/dequelabs/axe-core

Автоматически проверять:

```text
contrast
ARIA
labels
keyboard navigation
heading hierarchy
buttons/links
focus states
```

---

# 20. Asset Integration Pipeline

Для HearthPulse особенно важна отдельная система работы с игровыми ассетами.

Не:

```text
<img src="hero.jpg">
```

а:

```text
game asset
↓
classification
↓
focal point
↓
crop
↓
background removal if needed
↓
color extraction
↓
contrast treatment
↓
design preset
↓
responsive variants
↓
WebP / AVIF
```

---

# 21. Asset Roles

Каждый asset получает роль:

```text
hero
background
character-cutout
card-art
portrait
icon
decorative-overlay
texture
```

От роли зависит обработка.

---

# 22. Asset Presets

Создать стандартные presets.

## hero-art

```text
smart crop
dark gradient
text safe zone
slight saturation control
edge fade
responsive crop
```

## character-cutout

```text
background removal
transparent output
subject padding
drop shadow
responsive scaling
```

## card-background

```text
crop
blur/tint
contrast reduction
overlay
```

## portrait

```text
fixed aspect ratio
focal point
consistent crop
```

## decorative-overlay

```text
low opacity
pointer-events none
controlled blend
```

---

# 23. Asset Processing Tools

## imgproxy

Smart resize/crop, WebP/AVIF, focal points.

https://github.com/imgproxy/imgproxy

## Sharp

Image compositing, resize, gradients, overlays.

https://github.com/lovell/sharp

## rembg

Background removal.

https://github.com/danielgatis/rembg

## SVGO

SVG processing.

https://github.com/svg/svgo

---

# 24. GameAsset Component

Создать единый компонент:

```tsx
<GameAsset
  src={asset}
  role="hero"
  focalPoint="auto"
  harmonize
  contrastGuard
/>
```

Компонент сам выбирает:

```text
crop
overlay
gradient
image quality
sizes
srcset
position
fallback
```

---

# 25. Asset Color Harmonization

Из изображения можно получать:

```text
dominant color
accent color
average luminance
```

И использовать для:

```text
background tint
gradient
border accent
glow
```

Но нельзя позволять картинке полностью менять design system.

Правило:

```text
asset colors influence UI
but do not replace semantic design tokens
```

---

# 26. Text Safe Zones

Для hero/game art хранить:

```text
focal point
subject box
text safe zone
```

Пример:

```json
{
  "focalPoint": [0.72, 0.42],
  "safeText": "left"
}
```

Это позволит автоматически размещать текст рядом с персонажем, а не поверх лица.

---

# 27. Asset Metadata

Хранить рядом с asset:

```json
{
  "role": "hero",
  "focalPoint": [0.7, 0.4],
  "dominantColor": "#...",
  "safeText": "left",
  "backgroundRemoval": false
}
```

AI не должен определять это повторно при каждом использовании.

---

# 28. Design Context для Codex

Перед UI-задачей формировать компактный пакет:

```text
task
+
relevant design tokens
+
relevant components
+
screenshots
+
target component source
+
asset metadata
+
responsive rules
```

Не передавать весь Storybook или весь CSS.

---

# 29. UI Context Retrieval

Добавить в `context-economy`:

```text
design-context
```

Он должен уметь:

```text
find component
find design tokens
find related Storybook story
find screenshots
find asset preset
find responsive rules
```

---

# 30. Component Similarity Search

Перед созданием компонента:

```text
"нужна карточка статистики"
```

Система ищет:

```text
StatCard
MetricCard
DeckStat
HeroStat
```

и отдаёт Codex самый похожий существующий компонент.

Это предотвращает десятки почти одинаковых компонентов.

---

# 31. Screenshot Reference Search

Хранить screenshots компонентов.

Codex может получить:

```text
Button primary screenshot
ArticleCard screenshot
Hero screenshot
StatsCard screenshot
```

вместо чтения большого CSS.

---

# 32. Design Review без большого LLM-контекста

Reviewer получает:

```text
task
before screenshot
after screenshot
visual diff
changed component
design rules violated
```

Не получает весь frontend.

---

# 33. UI Quality Gate

Итоговый pipeline:

```text
TypeScript
↓
Biome / ESLint
↓
Stylelint
↓
token validator
↓
SVG validator
↓
Storybook tests
↓
Playwright
↓
visual regression
↓
computed-style validator
↓
axe
```

Только если что-то падает:

```text
small diagnostic packet → Codex
```

---

# 34. CSS / Next.js инструменты

## Biome

https://github.com/biomejs/biome

## ESLint

https://github.com/eslint/eslint

## Stylelint

https://github.com/stylelint/stylelint

## Storybook

https://github.com/storybookjs/storybook

## Playwright

https://github.com/microsoft/playwright

## Lost Pixel

https://github.com/lost-pixel/lost-pixel

## axe-core

https://github.com/dequelabs/axe-core

## Knip

https://github.com/webpro-nl/knip

---

# 35. Рекомендуемая структура проекта

```text
design/
├── DESIGN-SYSTEM.md
├── tokens/
│   ├── colors.json
│   ├── spacing.json
│   ├── typography.json
│   ├── radius.json
│   └── motion.json
│
├── components/
│   └── registry.json
│
├── assets/
│   ├── presets.json
│   └── metadata/
│
└── rules/
    ├── css.md
    ├── svg.md
    ├── responsive.md
    └── motion.md
```

---

# 36. Design Guard

Добавить сервис:

```text
design-guard
```

Команды:

```bash
design-guard tokens
design-guard css
design-guard components
design-guard svg
design-guard screenshots
design-guard responsive
design-guard accessibility
design-guard assets
```

И общую:

```bash
design-guard verify
```

---

# 37. Asset CLI

Можно добавить:

```bash
asset prepare hero image.png
asset prepare character image.png
asset prepare card image.png
```

Результат:

```text
optimized AVIF
WebP fallback
metadata
dominant colors
focal point
responsive variants
```

---

# 38. Workflow изменения UI

Пример задачи:

```text
"переделай блок рейтинга HearthPulse"
```

Pipeline:

```text
1. find existing component
2. read relevant design tokens
3. load current screenshot
4. inspect related Storybook story
5. get asset metadata
6. Codex changes scoped component
7. TypeScript
8. Stylelint
9. token validator
10. screenshots
11. visual diff
12. mobile checks
13. axe
14. only failures → Codex
```

---

# 39. Что даст наибольший эффект

## P0

1. Design tokens
2. Component registry
3. Storybook
4. Playwright screenshots
5. Visual regression
6. Stylelint custom rules
7. SVG normalization

## P1

8. Computed-style validator
9. Asset presets
10. GameAsset component
11. Responsive guard
12. Typography/spacing validator

## P2

13. Automatic focal-point detection
14. dominant-color extraction
15. screenshot/component retrieval
16. advanced visual AI review

---

# 40. Что не делать

Не стоит:

- позволять Codex создавать новые цвета без причины;
- создавать новые Button/Card на каждой странице;
- хранить SVG с inline случайными цветами;
- использовать arbitrary spacing повсюду;
- просить LLM вручную искать CSS-проблемы;
- отдавать LLM весь frontend ради одного компонента;
- вставлять игровые арты напрямую без preset;
- смешивать дизайн игры и UI сайта без обработки;
- использовать visual AI review вместо visual regression для каждой мелкой правки.

---

# 41. Как это встроить в Manacost-Labs/Server

Итоговая структура:

```text
context-economy/
├── code-context
├── docs-context
├── reference-search
└── design-context

quality-gates/
├── nextjs
├── go
└── ui
    ├── css
    ├── tokens
    ├── components
    ├── typography
    ├── svg
    ├── motion
    ├── responsive
    ├── screenshots
    ├── accessibility
    └── assets
```

---

# 42. Финальная архитектура

```text
                 UI request
                     ↓
               Design Context
                     ↓
        ┌────────────┼─────────────┐
        ↓            ↓             ↓
     Tokens      Components      Assets
        ↓            ↓             ↓
        └────────────┼─────────────┘
                     ↓
                   Codex
                     ↓
        ┌────────────┼──────────────┐
        ↓            ↓              ↓
      CSS         Visual         Accessibility
     checks       regression       checks
        ↓            ↓              ↓
        └────────────┼──────────────┘
                     ↓
             minimal diagnostics
                     ↓
                   Codex
```

---

# Итог

Для HearthPulse и hs-manacost.ru ключевая задача — не искать “AI, который лучше делает дизайн”.

Нужно построить систему, в которой хороший дизайн становится ограничением среды:

1. единые design tokens;
2. единая библиотека компонентов;
3. жёсткие CSS/SVG правила;
4. visual regression;
5. computed-style checks;
6. responsive checks;
7. asset presets;
8. единый `GameAsset` component;
9. screenshot-based review;
10. Codex получает только небольшой design context.

Тогда даже небольшие изменения сайта будут сохранять визуальную целостность и требовать значительно меньше ручных исправлений.
